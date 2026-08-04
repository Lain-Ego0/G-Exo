"""RagService: incremental indexing, Chinese retrieval, PDF extraction."""
from __future__ import annotations

from pathlib import Path

import pytest

from gexo_web_agent.config import RagConfig
from gexo_web_agent.rag_service import RagService, _chunk_text, _split_markdown_sections


@pytest.fixture()
def corpus(tmp_path: Path) -> Path:
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "guide.md").write_text(
        "# 穿戴指南\n\n"
        "穿戴设备时，先固定腰部绑带，再依次固定左右大腿和小腿绑带。"
        "确认四个 IMU 全部在线并完成标定后才可开机。\n\n"
        "# 电池说明\n\n"
        "设备使用 6S 锂电池，标称电压 22.2V。电量低于 20% 时应尽快更换电池。"
        "双电池支持热插拔轮换。\n\n"
        "# 阻尼训练\n\n"
        "阻尼训练模式下电机对人体运动产生阻力，适用于高抬腿等训练场景。",
        encoding="utf-8",
    )
    (docs / "faq.txt").write_text(
        "问：助力多大合适？答：建议从 50% 开始，按 10% 逐步调整，范围 30% 到 100%。",
        encoding="utf-8",
    )
    return docs


def make_service(tmp_path: Path, corpus_dir: Path) -> RagService:
    cfg = RagConfig(
        corpus_dirs=[str(corpus_dir)],
        db_path=str(tmp_path / "index.db"),
        chunk_size=200,
        chunk_overlap=40,
        top_k=3,
    )
    return RagService(cfg, base_dir=tmp_path)


def test_index_and_chinese_two_char_query(tmp_path, corpus):
    svc = make_service(tmp_path, corpus)
    stats = svc.build_index()
    assert stats["indexed"] == 2 and stats["errors"] == 0

    hits = svc.search("电池")  # 2-char word — the trigram tokenizer would miss this
    assert hits and any("锂电池" in h.text or "电池" in h.text for h in hits)

    hits = svc.search("怎么穿戴设备")
    assert hits and "绑带" in hits[0].text
    assert hits[0].file == "guide.md"
    assert hits[0].section  # heading captured

    svc.close()


def test_top_k_limit(tmp_path, corpus):
    svc = make_service(tmp_path, corpus)
    svc.build_index()
    assert len(svc.search("设备", top_k=2)) <= 2
    svc.close()


def test_no_hits_for_unrelated(tmp_path, corpus):
    svc = make_service(tmp_path, corpus)
    svc.build_index()
    assert svc.search("量子计算优化算法") == []
    svc.close()


def test_incremental_skip_unchanged(tmp_path, corpus):
    svc = make_service(tmp_path, corpus)
    first = svc.build_index()
    assert first["indexed"] == 2
    second = svc.build_index()
    assert second["indexed"] == 0 and second["skipped"] == 2
    svc.close()


def test_modified_file_reindexed(tmp_path, corpus):
    svc = make_service(tmp_path, corpus)
    svc.build_index()
    f = corpus / "guide.md"
    f.write_text(f.read_text(encoding="utf-8") + "\n\n# 新章节\n\n全新的维护保养内容。", encoding="utf-8")
    stats = svc.build_index()
    assert stats["indexed"] == 1
    hits = svc.search("维护保养")
    assert hits and hits[0].section == "新章节"
    svc.close()


def test_deleted_file_removed(tmp_path, corpus):
    svc = make_service(tmp_path, corpus)
    svc.build_index()
    (corpus / "faq.txt").unlink()
    stats = svc.build_index()
    assert stats["removed"] == 1
    assert all(h.file != "faq.txt" for h in svc.search("助力多大"))
    svc.close()


def test_rebuild(tmp_path, corpus):
    svc = make_service(tmp_path, corpus)
    svc.build_index()
    stats = svc.build_index(rebuild=True)
    assert stats["indexed"] == 2
    assert svc.search("电池")
    svc.close()


def test_pdf_extraction(tmp_path, corpus):
    # generate a minimal text-layer PDF with pypdf
    from pypdf import PdfWriter

    writer = PdfWriter()
    page = writer.add_blank_page(width=595, height=842)
    # pypdf cannot draw text; simulate a scanned page → should be skipped, not crash
    pdf_path = corpus / "scan.pdf"
    with open(pdf_path, "wb") as fh:
        writer.write(fh)

    svc = make_service(tmp_path, corpus)
    stats = svc.build_index()
    assert stats["errors"] == 0  # scanned pdf skipped gracefully
    svc.close()


def test_missing_corpus_dir_no_crash(tmp_path):
    cfg = RagConfig(corpus_dirs=[str(tmp_path / "nope")], db_path=str(tmp_path / "i.db"))
    svc = RagService(cfg, base_dir=tmp_path)
    stats = svc.build_index()
    assert stats["indexed"] == 0
    svc.close()


class TestChunking:
    def test_split_sections(self):
        secs = _split_markdown_sections("前言\n\n# A\n\n内容甲\n\n## B\n\n内容乙")
        titles = [t for t, _ in secs]
        assert titles == ["", "A", "B"]

    def test_chunk_overlap(self):
        text = "字" * 1000
        chunks = list(_chunk_text(text, 300, 100))
        assert all(len(c) <= 300 for c in chunks)
        # consecutive chunks overlap
        assert chunks[0][-100:] == chunks[1][:100]

    def test_empty(self):
        assert list(_chunk_text("   ", 300, 100)) == []
