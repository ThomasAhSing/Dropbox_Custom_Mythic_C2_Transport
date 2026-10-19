import json
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import requests
from dropbox.files import FileMetadata, FolderMetadata, WriteMode

from dropbox_storage import DropboxStorageProvider
from messages import MessageTransport, MessageValidationError, TestMessage
from storage import StorageError


class MemoryStorage:
    """A second storage implementation proving messaging needs no Dropbox client."""

    def __init__(self):
        self.files = {}

    def put(self, path, data, *, overwrite=False):
        if path in self.files and not overwrite:
            raise StorageError("Already exists")
        self.files[path] = data

    def get(self, path):
        return self.files[path]

    def list_files(self, folder=""):
        return list(self.files)

    def delete(self, path):
        del self.files[path]


class MessageTests(unittest.TestCase):
    def test_exchange_without_dropbox(self):
        storage = MemoryStorage()
        transport = MessageTransport(storage)
        sent = transport.send("Hello, café!")
        storage.files["/unrelated.txt"] = b"ignore"
        storage.files["/message-invalid.json"] = b"ignore"
        self.assertEqual(transport.receive(sent.message_id), sent)
        self.assertEqual(transport.list_ids(), [sent.message_id])
        self.assertEqual(json.loads(next(iter(storage.files.values())))["version"], 1)
        self.assertNotEqual(transport.send("Another").message_id, sent.message_id)
        transport.delete(sent.message_id)
        self.assertNotIn(sent.message_id, transport.list_ids())

    def test_invalid_fields(self):
        valid = json.loads(TestMessage.create("Hello").to_bytes())
        for field, value in [("version", 2), ("version", True), ("message_id", "../bad"),
                             ("timestamp", "2026-01-01"), ("timestamp", None),
                             ("timestamp", "invalidZ"), ("text", " "),
                             ("text", 123), ("text", "x" * 10001)]:
            with self.subTest(field=field, value=str(value)[:40]):
                with self.assertRaises(MessageValidationError):
                    TestMessage.from_bytes(json.dumps({**valid, field: value}).encode())

    def test_malformed_json_and_fields(self):
        valid = TestMessage.create("Hello").to_bytes()
        for data in [b"\xff", b"not json", b"[]", b"{}",
                     valid[:-1] + b', "extra": 1}',
                     valid[:-1] + b', "version": 1}']:
            with self.subTest(data=data):
                with self.assertRaises(MessageValidationError):
                    TestMessage.from_bytes(data)

    def test_reject_mismatched_identity_and_path_traversal(self):
        storage = MemoryStorage()
        transport = MessageTransport(storage)
        first = transport.send("First")
        second = transport.send("Second")
        storage.files[transport._path(first.message_id)] = second.to_bytes()
        with self.assertRaises(MessageValidationError):
            transport.receive(first.message_id)
        with self.assertRaises(MessageValidationError):
            transport.delete("../other-file")


class DropboxStorageTests(unittest.TestCase):
    def test_create_and_overwrite_modes(self):
        dbx = Mock()
        provider = DropboxStorageProvider(dbx)
        provider.put("/file", b"first")
        self.assertEqual(dbx.files_upload.call_args.kwargs["mode"], WriteMode.add)
        self.assertTrue(dbx.files_upload.call_args.kwargs["strict_conflict"])
        provider.put("/file", b"second", overwrite=True)
        self.assertEqual(dbx.files_upload.call_args.kwargs["mode"], WriteMode.overwrite)
        self.assertFalse(dbx.files_upload.call_args.kwargs["autorename"])

    def test_download_closes_response(self):
        dbx = Mock()
        response = Mock(content=b"contents")
        dbx.files_download.return_value = (None, response)
        self.assertEqual(DropboxStorageProvider(dbx).get("/file"), b"contents")
        response.close.assert_called_once()

    def test_listing_paginates_and_excludes_folders(self):
        dbx = Mock()
        file = FileMetadata(name="file", id="id:1", client_modified=datetime.now(),
                            server_modified=datetime.now(), rev="123456789", size=1,
                            path_lower="/file")
        folder = FolderMetadata(name="folder", id="id:2", path_lower="/folder")
        dbx.files_list_folder.return_value = SimpleNamespace(entries=[folder], has_more=True, cursor="next")
        dbx.files_list_folder_continue.return_value = SimpleNamespace(entries=[file], has_more=False)
        self.assertEqual(DropboxStorageProvider(dbx).list_files(), ["/file"])
        dbx.files_list_folder_continue.assert_called_once_with("next")

    def test_all_operations_translate_network_errors(self):
        for sdk_method, operation in [
            ("files_upload", lambda p: p.put("/file", b"data")),
            ("files_download", lambda p: p.get("/file")),
            ("files_list_folder", lambda p: p.list_files()),
            ("files_delete_v2", lambda p: p.delete("/file")),
        ]:
            with self.subTest(method=sdk_method):
                dbx = Mock()
                error = requests.ConnectionError("offline")
                getattr(dbx, sdk_method).side_effect = error
                with self.assertRaises(StorageError) as caught:
                    operation(DropboxStorageProvider(dbx, attempts=1))
                self.assertIs(caught.exception.__cause__, error)


if __name__ == "__main__":
    unittest.main()
