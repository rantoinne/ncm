"""CLI entry: load Go artifacts into the graph and run concept tagging."""

from __future__ import annotations

import argparse
import json
import sys

from brain.api.main import _ingest_bundle, get_store, set_store
from brain.graph.store import InMemoryGraphStore, create_store
from brain.logging_config import get_logger, setup_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m brain.ingest",
        description="Load NCM artifacts from a data directory into the graph store and tag concepts.",
    )
    parser.add_argument(
        "--data",
        default="./data",
        help="Path to artifact directory (manifest.json, files/, graph.json, git.json)",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Force in-memory store (ignore Neo4j)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print result as JSON",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    setup_logging(level="DEBUG" if args.verbose else None)
    log = get_logger("ncm.ingest")
    log.info("brain ingest starting data=%s memory=%s", args.data, args.memory)

    if args.memory:
        store = InMemoryGraphStore()
        store.connect()
        set_store(store)
    else:
        set_store(create_store(prefer_neo4j=True))

    try:
        result = _ingest_bundle(args.data)
    except FileNotFoundError as exc:
        log.error("missing artifacts: %s", exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        log.exception("ingest failed")
        print(f"ingest failed: {exc}", file=sys.stderr)
        return 1
    finally:
        try:
            get_store().close()
        except Exception:
            pass

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"Indexed repo={result['repo_id']} "
            f"nodes={result['nodes_ingested']} edges={result['edges_ingested']} "
            f"files={result['files']} concepts={result['concepts_tagged']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
