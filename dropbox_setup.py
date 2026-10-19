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

SCOPES = ["files.metadata.read", "files.content.read", "files.content.write"]
SERVICE = "custom-transport-dropbox"


class SetupError(Exception):
    """An actionable configuration or verification failure."""


def app_key():
    """Read the Dropbox app key from the environment and check that it is set."""
    value = os.environ.get("DROPBOX_APP_KEY", "").strip()
    if not value:
        raise SetupError("Set DROPBOX_APP_KEY in .env (see .env.example).")
    return value


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


def client(key):
    """Create a Dropbox client using a refresh token from the environment or credential store."""
    token = os.environ.get("DROPBOX_REFRESH_TOKEN")
    if not token and os.environ.get("CREDENTIALS_DIRECTORY"):
        try:
            token = (Path(os.environ["CREDENTIALS_DIRECTORY"]) / "dropbox_token").read_text().strip()
        except OSError as exc:
            raise SetupError("Cannot read the service credential; check LoadCredential configuration.") from exc
    if not token:
        try:
            token = keyring.get_password(SERVICE, key)
        except Exception as exc:
            raise SetupError("Cannot read the OS credential store. Run in a regular local terminal or supply DROPBOX_REFRESH_TOKEN through your secret manager.") from exc
    if not token:
        raise SetupError("No refresh token found. Run: python dropbox_setup.py auth")
    return dropbox.Dropbox(
        oauth2_refresh_token=token, app_key=key, timeout=15,
        max_retries_on_error=0, max_retries_on_rate_limit=0
    )


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
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["auth", "verify", "list"])
    args = parser.parse_args(argv)
    try:
        key = app_key()
        if args.command == "auth":
            authenticate(key)
        else:
            with client(key) as dbx:
                if args.command == "verify":
                    verify(dbx)
                    upload_local_file(
                        dbx,
                        r"C:\Users\Thomas\Documents\BC Public Service\work\Custom_Transport_Dropbox\test.txt",
                        "/test2.txt",
                        
                    )
                else:
                    for item in entries(dbx):
                        print(item.path_display)
    except AuthError:
        print("Authentication failed or was revoked. Run auth again.", file=sys.stderr)
        return 1
    except ApiError as exc:
        print(f"Dropbox API request failed (request ID {exc.request_id}). Check permissions and App Folder access in App Console.", file=sys.stderr)
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
