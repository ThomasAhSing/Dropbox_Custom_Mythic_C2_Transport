"""Run with sudo inside each VM; prompt privately and configure systemd credentials."""

import getpass
import os
from pathlib import Path
import re
import sys
from uuid import UUID

import dropbox
from dropbox_setup import SCOPES


def main():
    if os.geteuid() != 0:
        raise SystemExit("Run with sudo inside the gateway VM.")
    key = input("Dropbox app key: ").strip()
    run_id = input("Lab run UUID (same on both gateways and app A): ").strip()
    if not re.fullmatch(r"[A-Za-z0-9]+", key) or str(UUID(run_id)) != run_id:
        raise SystemExit("Invalid app key or run UUID.")
    token = getpass.getpass("Refresh token (hidden; leave empty for browser authorization): ").strip()
    if not token:
        flow = dropbox.DropboxOAuth2FlowNoRedirect(key, use_pkce=True,
                                                  token_access_type="offline", scope=SCOPES)
        print("Open this public authorization URL in your host browser:\n" + flow.start())
        code = getpass.getpass("Authorization code (hidden): ").strip()
        try:
            result = flow.finish(code)
        except Exception:
            raise SystemExit("Authorization failed; retry without logging provider exception details.") from None
        if not result.refresh_token or not set(SCOPES).issubset(set((result.scope or "").split())):
            raise SystemExit("Refresh token or required permissions missing.")
        token = result.refresh_token
    if not token or "\n" in token:
        raise SystemExit("A refresh token is required.")
    os.umask(0o077)
    root = Path("/etc/dropbox-lab")
    root.mkdir(mode=0o700, exist_ok=True)
    for name, content in [("token", token), ("config", f"DROPBOX_APP_KEY={key}\nLAB_RUN_ID={run_id}\n")]:
        path = root / name
        # No token travels through shell arguments, shell history, or service logs.
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
    print("Credentials configured. Start with: sudo systemctl start dropbox-lab")
    return 0


if __name__ == "__main__":
    sys.exit(main())
