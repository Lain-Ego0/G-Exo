#!/usr/bin/env python3
"""Build / rebuild the RAG index from the command line.

    python scripts/build_rag_index.py            # incremental
    python scripts/build_rag_index.py --rebuild  # full rebuild
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gexo_web_agent.config import PACKAGE_ROOT, load_settings  # noqa: E402
from gexo_web_agent.rag_service import RagService  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="drop and rebuild the index")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    settings = load_settings(args.config)
    svc = RagService(settings.rag, base_dir=PACKAGE_ROOT)
    stats = svc.build_index(rebuild=args.rebuild)
    print(f"done: {stats}")
    svc.close()


if __name__ == "__main__":
    main()
