"""Dropbox SDK adapter for the application storage contract."""

import random
import time

import requests
from dropbox.exceptions import AuthError, DropboxException, HttpError, RateLimitError
from dropbox.files import FileMetadata, WriteMode

from storage import StorageError


class DropboxStorageProvider:
    """Use an authenticated Dropbox client; the caller owns its lifetime."""

    def __init__(self, dbx, *, attempts=3, sleep=time.sleep, on_retry=None):
        if not 1 <= attempts <= 5:
            raise ValueError("attempts must be between 1 and 5")
        self.dbx = dbx
        self.attempts = attempts
        self.sleep = sleep
        self.on_retry = on_retry or (lambda action, attempt: None)
        self.on_attempt = lambda action: None
        self.on_failure = lambda action: None
        self._blocked_until = 0

    def _operation(self, action, operation, *, safe_to_retry=True):
        """Bound transient retries; never log SDK error bodies or credentials."""
        if time.monotonic() < self._blocked_until:
            raise StorageError("Dropbox rate limit cooldown is still active.", code="rate_limit", retryable=True)
        for attempt in range(1, self.attempts + 1):
            self.on_attempt(action)
            try:
                return operation()
            except (DropboxException, requests.RequestException) as exc:
                self.on_failure(action)
                auth = isinstance(exc, AuthError)
                transient = not auth and (
                    isinstance(exc, (requests.Timeout, requests.ConnectionError, RateLimitError))
                    or isinstance(exc, HttpError) and exc.status_code >= 500
                )
                code = "authentication" if auth else "transient" if transient else "api"
                delay = min(2 ** (attempt - 1) + random.uniform(0, .25), 8)
                if isinstance(exc, RateLimitError) and exc.backoff:
                    # Do not retry early if the server asks for a longer wait.
                    if exc.backoff > 8:
                        self._blocked_until = time.monotonic() + exc.backoff
                        raise StorageError("Dropbox rate limited; try again later.",
                                           code="rate_limit", retryable=True) from exc
                    delay = max(delay, exc.backoff)
                if not transient or not safe_to_retry or attempt == self.attempts:
                    if isinstance(exc, RateLimitError) and exc.backoff:
                        self._blocked_until = time.monotonic() + exc.backoff
                    message = ("Dropbox authorization failed; run dropbox_setup.py auth again."
                               if auth else f"Dropbox {action} failed ({code}; attempts={attempt}).")
                    raise StorageError(message, code=code, retryable=transient) from exc
                self.on_retry(action, attempt)
                self.sleep(delay)

    def put(self, path: str, data: bytes, *, overwrite: bool = False) -> None:
        """Upload bytes, optionally replacing the existing destination."""
        self._operation("upload", lambda: self.dbx.files_upload(
                data, path,
                mode=WriteMode.overwrite if overwrite else WriteMode.add,
                autorename=False, strict_conflict=not overwrite,
            ), safe_to_retry=overwrite)

    def get(self, path: str) -> bytes:
        """Download bytes and always close the HTTP response."""
        def download():
            _, response = self.dbx.files_download(path)
            try:
                return response.content
            finally:
                response.close()
        return self._operation("download", download)

    def list_files(self, folder: str = "") -> list[str]:
        """Collect files from every listing page, excluding folders."""
        def listing():
            page = self.dbx.files_list_folder(folder)
            paths = []
            while True:
                paths.extend(item.path_lower for item in page.entries if isinstance(item, FileMetadata))
                if not page.has_more:
                    return paths
                page = self.dbx.files_list_folder_continue(page.cursor)
        return self._operation("listing", listing)

    def delete(self, path: str) -> None:
        """Delete the specified file."""
        self._operation("deletion", lambda: self.dbx.files_delete_v2(path), safe_to_retry=False)
