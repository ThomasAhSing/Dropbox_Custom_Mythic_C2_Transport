import json
from datetime import datetime, timedelta
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import requests
import dropbox
from dropbox.exceptions import AuthError, HttpError, RateLimitError

from dropbox_storage import DropboxStorageProvider
import dropbox_setup
from lab_node import LabNode
from lab_protocol import Envelope
from lab_report import report
from local_storage import LocalStorageProvider
from messages import MessageValidationError
from storage import StorageError


class LabTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.storage = LocalStorageProvider(self.root / "store")
        self.run_id = str(uuid4())

    def node(self, identity, filename):
        node = LabNode(self.storage, self.root / filename, identity, self.run_id,
                       emit=lambda *args, **kwargs: None)
        self.addCleanup(node.close)
        return node

    def test_two_directions_ack_status_and_duplicate_detection(self):
        a, b = self.node("node-a", "a.db"), self.node("node-b", "b.db")
        a.seed(3)
        b.seed(3)
        for _ in range(3):
            a.tick()
            b.tick()
        self.assertEqual(a.summary()["heartbeat_status"], {"acknowledged": 3})
        self.assertEqual(b.summary()["heartbeat_status"], {"acknowledged": 3})
        self.assertEqual(a.summary()["processed_heartbeats"], 3)
        self.assertGreater(a.db.execute("SELECT count(*) FROM events WHERE event='duplicate_observation'").fetchone()[0], 0)
        self.assertEqual(a.db.execute("SELECT count(*) FROM inbox WHERE kind='heartbeat'").fetchone()[0], 3)

    def test_commit_then_connection_loss_replays_same_message(self):
        a, b = self.node("node-a", "a.db"), self.node("node-b", "b.db")
        a.seed(1)
        original = self.storage.put
        def ambiguous_write(*args, **kwargs):
            original(*args, **kwargs)
            raise StorageError("Response lost", code="transient", retryable=True)
        self.storage.put = ambiguous_write
        a.flush()
        self.assertEqual(a.summary()["heartbeat_status"], {"pending": 1})
        self.storage.put = original
        a.flush()
        b.tick()
        a.tick()
        self.assertEqual(a.summary()["heartbeat_status"], {"acknowledged": 1})
        self.assertEqual(b.summary()["processed_heartbeats"], 1)

    def test_resume_from_persistent_outbox_and_inbox(self):
        a, b = self.node("node-a", "a.db"), self.node("node-b", "b.db")
        a.seed(1)
        a.flush()
        # Simulate stop after the processing transaction but before acknowledgement upload.
        path = self.storage.list_files()[0]
        b.accept(path, self.storage.get(path))
        restored = self.node("node-b", "b.db")
        restored.tick()
        a.tick()
        self.assertEqual(a.summary()["heartbeat_status"], {"acknowledged": 1})
        self.assertEqual(restored.summary()["processed_heartbeats"], 1)

    def test_replica_duplicate_processing_is_measured(self):
        a, b = self.node("node-a", "a.db"), self.node("node-b", "b.db")
        replica = self.node("node-b", "replica.db")
        a.seed(2)
        a.tick()
        b.tick()
        replica.tick()
        a.tick()
        result = report([self.root / "a.db", self.root / "b.db", self.root / "replica.db"])
        self.assertEqual(result["cross_worker_duplicate_processing"], 2)
        self.assertEqual(result["ack_roundtrip_seconds"]["samples"], 2)
        self.assertEqual(a.summary()["heartbeat_status"], {"acknowledged": 2})

    def test_invalid_message_is_quarantined_and_does_not_block_valid_one(self):
        a, b = self.node("node-a", "a.db"), self.node("node-b", "b.db")
        a.seed(1)
        bad_path = f"/lab-{self.run_id}-node-b-{uuid4()}.json"
        self.storage.put(bad_path, b'{"version":999}')
        a.tick()
        b.tick()
        b.tick()
        a.tick()
        self.assertEqual(b.summary()["rejected"], 1)
        self.assertEqual(a.summary()["heartbeat_status"], {"acknowledged": 1})

    def test_changed_id_unknown_ack_and_wrong_route_rejected(self):
        b = self.node("node-b", "b.db")
        message = Envelope.heartbeat(self.run_id, "node-a", "node-b")
        b.accept(message.path, message.to_bytes())
        changed = json.loads(message.to_bytes())
        changed["timestamp"] = "2026-01-01T01:00:00Z"
        with self.assertRaises(MessageValidationError):
            b.accept(message.path, json.dumps(changed).encode())
        with self.assertRaises(MessageValidationError):
            b.accept("/other.json", message.to_bytes())
        ack = Envelope.heartbeat(self.run_id, "node-b", "node-a").acknowledgement()
        with self.assertRaises(MessageValidationError):
            b.accept(ack.path, ack.to_bytes())

    def test_strict_schema_limits_and_state_identity(self):
        message = json.loads(Envelope.heartbeat(self.run_id, "node-a", "node-b").to_bytes())
        for field, value in [("version", True), ("run_id", "../bad"), ("kind", "execute"),
                             ("timestamp", None), ("sender", []), ("correlation_id", str(uuid4()))]:
            with self.subTest(field=field), self.assertRaises(MessageValidationError):
                Envelope.from_bytes(json.dumps({**message, field: value}).encode())
        for data in [b"x" * 4097, b"\xff", b"[]", b'{"version":2,"version":2}']:
            with self.assertRaises(MessageValidationError):
                Envelope.from_bytes(data)
        self.node("node-a", "a.db")
        with self.assertRaises(ValueError):
            LabNode(self.storage, self.root / "a.db", "node-b", self.run_id)

    def test_local_storage_rejects_escape_and_conflict(self):
        with self.assertRaises(StorageError):
            self.storage.put("/../escape", b"data")
        self.storage.put("/file", b"first")
        with self.assertRaises(StorageError):
            self.storage.put("/file", b"second")
        self.assertEqual(self.storage.get("/file"), b"first")

    def test_missing_evidence_is_an_error_not_a_successful_empty_run(self):
        result = report([self.root / "missing.sqlite"])
        self.assertEqual(len(result["state_errors"]), 1)
        self.assertEqual(result["workers"], [])

    def test_listing_outage_retains_pending_work_and_reports_it(self):
        a, b = self.node("node-a", "a.db"), self.node("node-b", "b.db")
        a.seed(1)
        listing = self.storage.list_files
        self.storage.list_files = Mock(side_effect=StorageError("offline", code="transient", retryable=True))
        a.tick()
        self.assertEqual(a.summary()["heartbeat_status"], {"sent": 1})
        self.assertEqual(a.db.execute("SELECT count(*) FROM events WHERE event='storage_error'").fetchone()[0], 1)
        self.storage.list_files = listing
        b.tick()
        a.tick()
        self.assertEqual(a.summary()["heartbeat_status"], {"acknowledged": 1})


class RetryTests(unittest.TestCase):
    def test_sdk_refreshes_expired_access_token_before_request(self):
        dbx = dropbox.Dropbox(oauth2_access_token="not-a-real-token",
                              oauth2_refresh_token="not-a-real-refresh-token", app_key="test",
                              oauth2_access_token_expiration=datetime.utcnow() - timedelta(minutes=1))
        try:
            with patch.object(dbx, "refresh_access_token") as refresh:
                dbx.check_and_refresh_access_token()
                refresh.assert_called_once()
        finally:
            dbx.close()

    def test_service_credential_is_used_without_keyring(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "dropbox_token").write_text("sentinel-refresh-token")
            with patch.dict(os.environ, {"DROPBOX_REFRESH_TOKEN": "", "CREDENTIALS_DIRECTORY": directory}), \
                 patch.object(dropbox_setup.keyring, "get_password") as keyring, \
                 patch.object(dropbox_setup.dropbox, "Dropbox") as factory:
                dropbox_setup.client("public-key")
                self.assertEqual(factory.call_args.kwargs["oauth2_refresh_token"], "sentinel-refresh-token")
                self.assertEqual(factory.call_args.kwargs["max_retries_on_rate_limit"], 0)
                keyring.assert_not_called()

    def test_timeout_is_bounded_and_then_succeeds(self):
        dbx, sleep, retry = Mock(), Mock(), Mock()
        dbx.files_upload.side_effect = [requests.Timeout("SECRET"), HttpError("id", 503, "SECRET"), None]
        provider = DropboxStorageProvider(dbx, sleep=sleep, on_retry=retry)
        provider.put("/file", b"same", overwrite=True)
        self.assertEqual(dbx.files_upload.call_count, 3)
        self.assertEqual(sleep.call_count, 2)
        self.assertEqual(retry.call_count, 2)

    def test_expired_or_revoked_auth_is_reported_without_secret(self):
        dbx, sleep = Mock(), Mock()
        dbx.files_upload.side_effect = AuthError("request", "SECRET")
        with self.assertRaises(StorageError) as caught:
            DropboxStorageProvider(dbx, sleep=sleep).put("/file", b"data", overwrite=True)
        self.assertEqual(caught.exception.code, "authentication")
        self.assertNotIn("SECRET", str(caught.exception))
        sleep.assert_not_called()

    def test_retry_exhaustion_rate_limit_and_unsafe_upload(self):
        for error, overwrite, expected_calls in [
            (requests.Timeout("secret"), True, 3),
            (requests.Timeout("secret"), False, 1),
            (RateLimitError("id", backoff=60), True, 1),
        ]:
            dbx = Mock()
            dbx.files_upload.side_effect = error
            with self.assertRaises(StorageError):
                DropboxStorageProvider(dbx, sleep=Mock()).put("/file", b"data", overwrite=overwrite)
            self.assertEqual(dbx.files_upload.call_count, expected_calls)

    def test_rate_limit_cooldown_survives_next_poll(self):
        dbx = Mock()
        dbx.files_upload.side_effect = RateLimitError("id", backoff=60)
        with patch("dropbox_storage.time.monotonic", return_value=10):
            provider = DropboxStorageProvider(dbx, sleep=Mock())
            for _ in range(2):
                with self.assertRaises(StorageError):
                    provider.put("/file", b"data", overwrite=True)
            self.assertEqual(dbx.files_upload.call_count, 1)


if __name__ == "__main__":
    unittest.main()
