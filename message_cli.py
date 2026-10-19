"""Compose Dropbox storage with provider-independent messaging for manual use."""

import argparse
from pathlib import Path

from dotenv import load_dotenv

from dropbox_setup import SetupError, app_key, client
from dropbox_storage import DropboxStorageProvider
from messages import MessageTransport, MessageValidationError
from storage import StorageError


def main(argv=None):
    """Run a message command using the existing Dropbox credentials."""
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("send").add_argument("text")
    commands.add_parser("list")
    for command in ("receive", "delete"):
        commands.add_parser(command).add_argument("message_id")
    args = parser.parse_args(argv)
    load_dotenv(Path(__file__).with_name(".env"))
    try:
        with client(app_key()) as dbx:
            transport = MessageTransport(DropboxStorageProvider(dbx))
            if args.command == "send":
                print(transport.send(args.text).message_id)
            elif args.command == "receive":
                print(transport.receive(args.message_id).to_bytes().decode("utf-8"))
            elif args.command == "list":
                for message_id in transport.list_ids():
                    print(message_id)
            else:
                transport.delete(args.message_id)
                print("Message deleted.")
    except (SetupError, StorageError, MessageValidationError) as exc:
        parser.exit(1, f"Error: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
