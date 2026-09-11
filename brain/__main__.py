"""Allow `python -m brain` to show help / run the API."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m brain", description="Neural Codebase Memory brain")
    sub = parser.add_subparsers(dest="cmd")

    ingest_p = sub.add_parser("ingest", help="Load artifacts and tag concepts")
    ingest_p.add_argument("--data", default="./data")
    ingest_p.add_argument("--memory", action="store_true")
    ingest_p.add_argument("--json", action="store_true")

    serve_p = sub.add_parser("serve", help="Run the FastAPI server")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--reload", action="store_true")

    args = parser.parse_args(argv)
    if args.cmd == "ingest":
        from brain.ingest import main as ingest_main

        flags = ["--data", args.data]
        if args.memory:
            flags.append("--memory")
        if args.json:
            flags.append("--json")
        return ingest_main(flags)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run(
            "brain.api.main:app",
            host=args.host,
            port=args.port,
            reload=args.reload,
        )
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
