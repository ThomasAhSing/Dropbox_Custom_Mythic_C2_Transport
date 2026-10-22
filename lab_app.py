"""Run an independent lab endpoint with Dropbox or local storage."""

import argparse
from contextlib import ExitStack
import json
import sqlite3
import time
from pathlib import Path

from dotenv import load_dotenv

from dropbox_setup import SetupError, app_key, client
from dropbox_storage import DropboxStorageProvider
from lab_node import LabNode
from local_storage import LocalStorageProvider
from storage import StorageError
from messages import MessageValidationError


def main(argv=None, *, default_node=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", choices=["node-a", "node-b"], default=default_node, required=default_node is None)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--state", required=True, help="Separate persistent SQLite file for each worker")
    parser.add_argument("--provider", choices=["dropbox", "local"], default="dropbox")
    parser.add_argument("--root", default="lab-data/store", help="Storage folder for local provider")
    parser.add_argument("--heartbeats", type=int, default=3)
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--heartbeat-interval", type=float, default=1)
    parser.add_argument("--poll", type=float, default=2)
    args = parser.parse_args(argv)
    if (not 0 <= args.heartbeats <= 1000 or not 0 < args.duration <= 86400
            or not .05 <= args.poll <= 60 or not 0 <= args.heartbeat_interval <= 60):
        parser.error("heartbeats: 0–1000; duration: (0,86400]; poll: 0.05–60 seconds")
    load_dotenv(Path(__file__).with_name(".env"))
    try:
        with ExitStack() as stack:
            if args.provider == "local":
                storage = LocalStorageProvider(args.root)
            else:
                dbx = stack.enter_context(client(app_key()))
                storage = DropboxStorageProvider(dbx)
            node = LabNode(storage, args.state, args.node, args.run_id)
            stack.callback(node.close)
            if args.provider == "dropbox":
                storage.on_retry = lambda action, attempt: node.record("retry", code=action)
                storage.on_attempt = lambda action: node.record("storage_attempt", code=action)
                storage.on_failure = lambda action: node.record("storage_attempt_failure", code=action)
            node.seed(args.heartbeats, args.heartbeat_interval)
            end = time.monotonic() + args.duration
            while time.monotonic() < end:
                node.tick()
                time.sleep(args.poll)
            summary = node.summary()
            print(json.dumps(summary), flush=True)
            return 0 if sum(summary["heartbeat_status"].values()) == summary["heartbeat_status"].get("acknowledged", 0) else 2
    except (SetupError, StorageError, MessageValidationError, ValueError, OSError, sqlite3.Error) as exc:
        # Never render chained provider exceptions, environment values, or paths.
        message = (str(exc) if isinstance(exc, (SetupError, StorageError, MessageValidationError))
                   else "Local configuration or state error; check arguments, disk access, and state identity.")
        print(json.dumps(dict(event="fatal", code=getattr(exc, "code", type(exc).__name__), message=message)), flush=True)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
