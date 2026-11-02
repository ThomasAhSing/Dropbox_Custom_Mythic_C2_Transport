"""Development CLI for Dropbox authorization, diagnostics, and manual uploads."""

import argparse
import getpass
import os
import sys
import uuid
import webbrowser
from pathlib import Path

import dropbox
import keyring
import requests
from dotenv import load_dotenv
from dropbox.exceptions import ApiError, AuthError, DropboxException
from dropbox.files import WriteMode

from dropbox_client import SCOPES, SERVICE, SetupError, app_key, client


def authenticate(key):
    """Guide browser authorization and save a refresh token for unattended runs."""
    flow = dropbox.DropboxOAuth2FlowNoRedirect(
        key, use_pkce=True, token_access_type="offline", scope=SCOPES
    )
    url = flow.start()
    print("Open this URL and allow the requested App Folder access:\n" + url, flush=True)
    webbrowser.open(url)
    code = getpass.getpass("Paste the authorization code (hidden): ").strip()
    if not code:
        raise SetupError("No authorization code entered.")
    result = flow.finish(code)
    if not result.refresh_token:
        raise SetupError("Dropbox did not issue a refresh token; run auth again.")
    if not set(SCOPES).issubset(set((result.scope or "").split())):
        raise SetupError("Required scopes missing. Enable all three in App Console, then retry.")
    try:
        keyring.set_password(SERVICE, key, result.refresh_token)
    except Exception as exc:
        raise SetupError("Cannot save to the OS credential store. Run auth in a regular local terminal with credential-store access.") from exc
    print("Authenticated. Refresh token saved in the OS credential store.")


def entries(dbx, path=""):
    """List all items in a Dropbox folder, following pagination; default to the App Folder root."""
    page = dbx.files_list_folder(path)
    yield from page.entries
    while page.has_more:
        page = dbx.files_list_folder_continue(page.cursor)
        yield from page.entries


def verify(dbx):
    """Check upload, listing, download, and deletion using a temporary file and its exact revision."""
    path = f"/dropbox-api-test-{uuid.uuid4().hex}.txt"
    payload = f"Dropbox API verification\n{uuid.uuid4().hex}\n".encode()
    uploaded = None
    deleted = False
    try:
        uploaded = dbx.files_upload(
            payload, path, mode=WriteMode.add, autorename=False, strict_conflict=True
        )
        print("PASS upload", flush=True)
        if not any(item.id == uploaded.id for item in entries(dbx)):
            raise SetupError("Uploaded file not found in folder listing.")
        print("PASS listing", flush=True)
        _, response = dbx.files_download(uploaded.id)
        try:
            if response.content != payload:
                raise SetupError("Downloaded contents differ from the uploaded bytes.")
        finally:
            response.close()
        print("PASS download (contents match)", flush=True)
        dbx.files_delete_v2(uploaded.id, parent_rev=uploaded.rev)
        deleted = True
        if any(item.id == uploaded.id for item in entries(dbx)):
            raise SetupError("Deleted test file still appears in listing.")
        print("PASS deletion (confirmed absent)\nPASS all Dropbox file checks", flush=True)
    finally:
        if uploaded is not None and not deleted:
            try:
                dbx.files_delete_v2(uploaded.id, parent_rev=uploaded.rev)
            except (DropboxException, requests.RequestException):
                print(f"Cleanup failed; inspect test file {path}", file=sys.stderr)


def main(argv=None):
    """Load configuration, run the requested command, and report errors with an exit code."""
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("auth", "verify", "list"):
        commands.add_parser(name)
    upload = commands.add_parser("upload", help="Explicitly upload a local file")
    upload.add_argument("local_path", type=Path)
    upload.add_argument("dropbox_path")
    args = parser.parse_args(argv)
    try:
        key = app_key()
        if args.command == "auth":
            authenticate(key)
        else:
            with client(key) as dbx:
                if args.command == "verify":
                    verify(dbx)
                elif args.command == "upload":
                    upload_local_file(dbx, args.local_path, args.dropbox_path)
                else:
                    for item in entries(dbx):
                        print(item.path_display)
    except AuthError:
        print("Authentication failed or was revoked. Run auth again.", file=sys.stderr)
        return 1
    except ApiError as exc:
        print(f"Dropbox API request failed (request ID {exc.request_id}). Check permissions and App Folder access in App Console.", file=sys.stderr)
        return 1
    except OSError:
        print("Cannot read the local upload file.", file=sys.stderr)
        return 1
    except (SetupError, keyring.errors.KeyringError) as exc:
        print(f"Setup error: {exc}", file=sys.stderr)
        return 1
    except (DropboxException, requests.RequestException):
        print("Dropbox request failed. Check connectivity and retry; for auth, use a fresh code.", file=sys.stderr)
        return 1
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.", file=sys.stderr)
        return 130
    return 0

def upload_local_file(dbx, local_path, dropbox_path):
    """Upload a local file, replacing any existing file at the same Dropbox path."""
    with open(local_path, "rb") as file:
        return dbx.files_upload(
            file.read(),
            dropbox_path,
            mode=WriteMode.overwrite,
            autorename=False,
        )


if __name__ == "__main__":
    sys.exit(main())
