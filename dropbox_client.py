"""Reusable Dropbox configuration, credentials, and authenticated client creation."""

import os
from pathlib import Path

import dropbox
import keyring

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
        raise SetupError("No refresh token found. Run: python -m dev.tools.dropbox_setup auth")
    return dropbox.Dropbox(
        oauth2_refresh_token=token, app_key=key, timeout=15,
        max_retries_on_error=0, max_retries_on_rate_limit=0
    )


