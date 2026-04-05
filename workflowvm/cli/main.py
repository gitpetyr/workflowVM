import argparse
import sys


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--config", default="accounts.yml",
        help="Path to accounts.yml (default: accounts.yml)"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="workflowvm",
        description="WorkflowVM server CLI",
    )
    sub = parser.add_subparsers(dest="command")

    serve_p = sub.add_parser("serve", help="Start the WorkflowVM server")
    _add_config_arg(serve_p)

    setup_p = sub.add_parser("setup", help="Check and initialize runner repos")
    _add_config_arg(setup_p)

    args = parser.parse_args()

    if args.command == "setup":
        from workflowvm.cli.setup_cmd import run_setup_sync
        run_setup_sync(args.config)

    elif args.command == "serve" or args.command is None:
        config = getattr(args, "config", "accounts.yml")
        import asyncio
        from workflowvm.server.main import main_async
        asyncio.run(main_async(config))

    else:
        parser.print_help()
        sys.exit(1)
