import argparse
import getpass
import json
import sys
import time

import keyring
from keyring.errors import PasswordDeleteError

from .access import SERVICES


def main():
    parser = argparse.ArgumentParser(prog="ya-webmaster")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("serve", help="Start the MCP stdio server")
    for name in ("connect", "disconnect"):
        cmd = actions.add_parser(name)
        cmd.add_argument("service", choices=SERVICES)
    watch = actions.add_parser(
        "watch", help="Print a baseline or changes as JSON lines"
    )
    watch.add_argument("site_url")
    watch.add_argument("--host-id")
    watch.add_argument("--counter-id", type=int)
    watch.add_argument(
        "--every",
        type=int,
        metavar="SECONDS",
        help="Repeat until stopped, at least 60 seconds",
    )
    args = parser.parse_args()
    if args.action == "serve":
        from .server import mcp

        mcp.run()
    elif args.action == "connect":
        if not sys.stdin.isatty():
            parser.error("Enter credentials in a local interactive terminal")
        value = getpass.getpass(f"{args.service} credential: ").strip()
        if not value:
            parser.error("Empty credential")
        keyring.set_password("grebennikov-site-desk", args.service, value)
        print("Saved in the operating system credential store.")
    elif args.action == "disconnect":
        try:
            keyring.delete_password("grebennikov-site-desk", args.service)
        except PasswordDeleteError:
            pass
        print(
            "Local credential removed. If an environment override is in use, unset it separately."
        )
    else:
        from .watch import check

        if args.every is not None and args.every < 60:
            parser.error("--every must be at least 60")
        while True:
            try:
                result = check(args.site_url, args.host_id, args.counter_id)
            except Exception as exc:  # noqa: BLE001 - one failed poll must not stop the scheduler
                # Avoid printing request URLs containing keys.
                result = {
                    "state": "error",
                    "error": str(exc)
                    if isinstance(exc, ValueError)
                    else type(exc).__name__,
                }
            if result["state"] != "unchanged" or not args.every:
                print(json.dumps(result, ensure_ascii=True), flush=True)
            if not args.every:
                return int(result["state"] in ("error", "incomplete"))
            time.sleep(args.every)


if __name__ == "__main__":
    sys.exit(main())
