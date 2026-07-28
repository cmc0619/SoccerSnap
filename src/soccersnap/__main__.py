from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="soccersnap", description="SoccerSnap control plane")
    sub = parser.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Run full product demo (rig + process + portal)")
    demo.add_argument("--host", default=None)
    demo.add_argument("--port", type=int, default=None)

    sub.add_parser("version", help="Print version")

    args = parser.parse_args(argv)

    if args.command == "version":
        from soccersnap import __version__

        print(__version__)
        return

    if args.command == "demo":
        import uvicorn

        from soccersnap.config import settings

        host = args.host or settings.host
        port = args.port or settings.port
        uvicorn.run("soccersnap.demo.app:create_demo_app", factory=True, host=host, port=port, reload=False)
        return

    parser.print_help()
    sys.exit(1)


if __name__ == "__main__":
    main()
