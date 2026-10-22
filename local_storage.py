"""Atomic filesystem storage for offline lab experiments, not a cloud emulator."""

import os
from pathlib import Path
import tempfile

from storage import StorageError


class LocalStorageProvider:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, path):
        target = (self.root / path.lstrip("/")).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise StorageError("Path outside storage root.", code="path")
        return target

    def put(self, path, data, *, overwrite=False):
        target = self._path(path)
        temp = None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as handle:
                temp = Path(handle.name)
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if overwrite:
                os.replace(temp, target)
            else:
                os.link(temp, target)
        except OSError as exc:
            raise StorageError("Local write failed.", code="local") from exc
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def get(self, path):
        try:
            return self._path(path).read_bytes()
        except OSError as exc:
            raise StorageError("Local read failed.", code="local") from exc

    def list_files(self, folder=""):
        try:
            root = self.root if folder in ("", "/") else self._path(folder)
            return ["/" + p.relative_to(self.root).as_posix() for p in root.iterdir() if p.is_file()]
        except OSError as exc:
            raise StorageError("Local listing failed.", code="local") from exc

    def delete(self, path):
        try:
            self._path(path).unlink()
        except OSError as exc:
            raise StorageError("Local deletion failed.", code="local") from exc
