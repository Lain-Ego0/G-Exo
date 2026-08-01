"""Lightweight local RAG: jieba segmentation + SQLite FTS5 + BM25.

Why this combination: FTS5's stock tokenizers do not segment Chinese (a whole
sentence becomes one token) and the trigram tokenizer misses the very common
2-character words (助力, 电池).  Segmenting both documents AND queries with
jieba, storing the space-joined tokens in the FTS column, makes unicode61 +
built-in bm25() just work.  The raw chunk text is kept in a companion column
for display.

Supports .md / .txt (heading-aware chunking) and .pdf (text layer via pypdf,
per-page; scanned pages are skipped with a log line).  Index is incremental:
files are keyed by (path, mtime, size) and unchanged files are skipped.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

from .config import RagConfig

logger = logging.getLogger(__name__)

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class RagHit:
    file: str
    section: str
    text: str
    score: float


def _segment(text: str) -> str:
    """jieba-cut text into space-joined tokens for FTS5 unicode61."""
    import jieba  # lazy: first import builds its dictionary cache (~1s)

    return " ".join(t.strip() for t in jieba.cut(text) if t.strip())


def _chunk_text(text: str, chunk_size: int, overlap: int) -> Iterable[str]:
    """Greedy fixed-size chunking with overlap."""
    text = text.strip()
    if not text:
        return
    step = max(chunk_size - overlap, 1)
    for start in range(0, len(text), step):
        chunk = text[start : start + chunk_size]
        if len(chunk) < 50 and start > 0:  # tail fragment already covered by overlap
            break
        yield chunk


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Split .md/.txt by headings → [(section_title, body)]."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [("", text)]
    sections: list[tuple[str, str]] = []
    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections.append(("", preamble))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[m.end() : end].strip()
        if body:
            sections.append((m.group(2).strip(), body))
    return sections


class RagService:
    def __init__(self, cfg: RagConfig, base_dir: Path) -> None:
        self._cfg = cfg
        self._base_dir = base_dir
        self._db_path = self._resolve(cfg.db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._init_schema()

    def _resolve(self, p: str) -> Path:
        path = Path(p)
        return path if path.is_absolute() else (self._base_dir / path).resolve()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # ------------------------------------------------------------- schema

    def _init_schema(self) -> None:
        with self._lock, self._conn:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS files (
                    path TEXT PRIMARY KEY,
                    mtime REAL NOT NULL,
                    size INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY,
                    path TEXT NOT NULL,
                    section TEXT NOT NULL,
                    raw TEXT NOT NULL
                );
                CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
                    seg,
                    tokenize='unicode61'
                );
                """
            )

    # ------------------------------------------------------------ indexing

    def build_index(self, rebuild: bool = False) -> dict[str, int]:
        """Incrementally (re)index all corpus dirs. Returns counters."""
        stats = {"indexed": 0, "skipped": 0, "removed": 0, "errors": 0}
        seen: set[str] = set()

        if rebuild:
            with self._lock, self._conn:
                self._conn.execute("DELETE FROM files")
                self._conn.execute("DELETE FROM chunks")
                self._conn.execute("DELETE FROM chunks_fts")

        for corpus_dir in self._cfg.corpus_dirs:
            root = self._resolve(corpus_dir)
            if not root.is_dir():
                logger.warning("RAG corpus dir missing: %s", root)
                continue
            for path in sorted(root.rglob("*")):
                if path.suffix.lower() not in (".md", ".txt", ".pdf") or not path.is_file():
                    continue
                key = str(path)
                seen.add(key)
                stat = path.stat()
                with self._lock:
                    row = self._conn.execute(
                        "SELECT mtime, size FROM files WHERE path=?", (key,)
                    ).fetchone()
                if row is not None and row[0] == stat.st_mtime and row[1] == stat.st_size:
                    stats["skipped"] += 1
                    continue
                try:
                    n = self._index_file(path)
                    stats["indexed"] += 1
                    logger.info("indexed %s (%d chunks)", path.name, n)
                except Exception:
                    stats["errors"] += 1
                    logger.exception("failed to index %s", path)

        # drop entries for deleted files
        with self._lock, self._conn:
            for (old_path,) in self._conn.execute("SELECT path FROM files").fetchall():
                if old_path not in seen:
                    self._remove_file_locked(old_path)
                    stats["removed"] += 1
        return stats

    def _index_file(self, path: Path) -> int:
        sections = (
            self._extract_pdf(path)
            if path.suffix.lower() == ".pdf"
            else _split_markdown_sections(path.read_text(encoding="utf-8", errors="replace"))
        )
        rows: list[tuple[str, str, str, str]] = []
        for section, body in sections:
            for chunk in _chunk_text(body, self._cfg.chunk_size, self._cfg.chunk_overlap):
                rows.append((str(path), section, chunk, _segment(chunk)))

        stat = path.stat()
        with self._lock, self._conn:
            self._remove_file_locked(str(path))
            for p, section, raw, seg in rows:
                cur = self._conn.execute(
                    "INSERT INTO chunks(path, section, raw) VALUES(?,?,?)", (p, section, raw)
                )
                self._conn.execute(
                    "INSERT INTO chunks_fts(rowid, seg) VALUES(?,?)", (cur.lastrowid, seg)
                )
            self._conn.execute(
                "INSERT OR REPLACE INTO files(path, mtime, size) VALUES(?,?,?)",
                (str(path), stat.st_mtime, stat.st_size),
            )
        return len(rows)

    def _remove_file_locked(self, path: str) -> None:
        ids = [r[0] for r in self._conn.execute("SELECT id FROM chunks WHERE path=?", (path,))]
        for chunk_id in ids:
            self._conn.execute("DELETE FROM chunks_fts WHERE rowid=?", (chunk_id,))
        self._conn.execute("DELETE FROM chunks WHERE path=?", (path,))
        self._conn.execute("DELETE FROM files WHERE path=?", (path,))

    @staticmethod
    def _extract_pdf(path: Path) -> list[tuple[str, str]]:
        from pypdf import PdfReader  # lazy

        sections: list[tuple[str, str]] = []
        reader = PdfReader(str(path))
        for i, page in enumerate(reader.pages, start=1):
            try:
                text = (page.extract_text() or "").strip()
            except Exception:
                text = ""
            if len(text) < 20:
                continue  # scanned/empty page
            sections.append((f"第{i}页", text))
        if not sections:
            logger.warning("PDF has no extractable text layer (scanned?): %s", path.name)
        return sections

    # ------------------------------------------------------------- search

    def search(self, query: str, top_k: Optional[int] = None) -> list[RagHit]:
        k = top_k or self._cfg.top_k
        terms = [t for t in _segment(query).split() if t]
        if not terms:
            return []
        # quote each term to disarm FTS5 query syntax; OR for recall
        fts_query = " OR ".join(f'"{t}"' for t in terms)
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT c.path, c.section, c.raw, bm25(chunks_fts) AS score
                FROM chunks_fts
                JOIN chunks c ON c.id = chunks_fts.rowid
                WHERE chunks_fts MATCH ?
                ORDER BY score
                LIMIT ?
                """,
                (fts_query, k),
            ).fetchall()
        return [
            RagHit(file=Path(p).name, section=section, text=raw, score=score)
            for p, section, raw, score in rows
        ]
