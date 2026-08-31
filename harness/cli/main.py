"""Command-line argument parsing and application startup."""

import argparse
import json
import os
import sys
from pathlib import Path

from harness import config
from harness.main import run


def main() -> None:
    """Parse command-line options and start the Harness REPL."""
    # Configuration is a subcommand-like convenience kept compatible with the
    # existing argument parser. It is available before packaging as well.
    if len(sys.argv) > 1 and sys.argv[1] == "configure":
        config._try_load_dotenv()
        config.configure()
        return

    parser = argparse.ArgumentParser(description="CLI coding agent")
    parser.add_argument("--yes", action="store_true", help="approve all file edits")
    parser.add_argument("--dry-run", action="store_true", help="show edits without applying them")
    parser.add_argument(
        "--reload", action="store_true",
        help="resume the previous persisted conversation",
    )
    parser.add_argument(
        "--request", "-r", default="",
        help="run one request non-interactively, then exit",
    )
    parser.add_argument("--scenario", help="load the request from eval_scenarios/manifest.json")
    parser.add_argument(
        "--manifest", default=str(Path(__file__).resolve().parent.parent.parent / "eval_scenarios" / "manifest.json"),
        help=argparse.SUPPRESS,
    )
    args = parser.parse_args()
    if args.scenario and not args.request:
        try:
            manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
            scenario = manifest[args.scenario]
            args.request = scenario["task"]
            # A scenario is self-contained: use its workspace/history unless
            # the caller explicitly supplied either environment variable.
            os.environ.setdefault("HARNESS_WORKSPACE", scenario["workspace"])
            os.environ.setdefault(
                "HARNESS_HISTORY_FILE",
                str(Path(scenario["workspace"]) / "history.txt"),
            )
        except (OSError, json.JSONDecodeError, KeyError) as exc:
            parser.error(f"could not load scenario {args.scenario!r}: {exc}")
    if args.yes:
        os.environ["HARNESS_AUTO_APPROVE"] = "1"
    if args.dry_run:
        os.environ["HARNESS_DRY_RUN"] = "1"
    config.init()
    request = args.request
    if not request and not sys.stdin.isatty():
        request = sys.stdin.read().strip()
    run(request, reload=args.reload)


if __name__ == "__main__":
    main()
