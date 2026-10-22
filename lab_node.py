"""Durable heartbeat endpoint; all cloud operations use StorageProvider."""

import hashlib
import json
from pathlib import Path
import sqlite3
import time

from lab_protocol import Envelope, utc_now
from messages import MessageValidationError, validate_id
from storage import StorageError, StorageProvider


class LabNode:
    def __init__(self, storage: StorageProvider, state, node, run_id, *, emit=print):
        validate_id(run_id)
        if node not in ("node-a", "node-b"):
            raise ValueError("Unknown node")
        self.storage, self.node, self.run_id, self.emit = storage, node, run_id, emit
        self.peer = "node-b" if node == "node-a" else "node-a"
        Path(state).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(state)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=FULL;
            CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS outbox (
                id TEXT PRIMARY KEY, body BLOB NOT NULL, kind TEXT NOT NULL,
                status TEXT NOT NULL, created REAL NOT NULL, sent REAL, acked REAL);
            CREATE TABLE IF NOT EXISTS inbox (
                id TEXT PRIMARY KEY, digest TEXT NOT NULL, kind TEXT NOT NULL,
                processed REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS rejected (path TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS events (
                seq INTEGER PRIMARY KEY, timestamp TEXT, event TEXT, message_id TEXT, code TEXT);
        """)
        identity = f"{node}:{run_id}"
        row = self.db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
        if row and row[0] != identity:
            self.db.close()
            raise ValueError("State belongs to a different node or run; choose a new state file.")
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO metadata VALUES ('identity', ?)", (identity,))

    def close(self):
        self.db.close()

    def event(self, event, message_id=None, code=None):
        """Record structured metadata; never include message contents or SDK exceptions."""
        timestamp = utc_now()
        self.db.execute("INSERT INTO events(timestamp,event,message_id,code) VALUES (?,?,?,?)",
                        (timestamp, event, message_id, code))
        self.emit(json.dumps(dict(timestamp=timestamp, node=self.node, event=event,
                                  message_id=message_id, code=code)), flush=True)

    def seed(self, count, interval=0):
        """Create initial heartbeats once; restarts resume existing outbox entries."""
        with self.db:
            if self.db.execute("SELECT 1 FROM metadata WHERE key='seeded'").fetchone():
                return
            for _ in range(count):
                message = Envelope.heartbeat(self.run_id, self.node, self.peer)
                self._queue(message)
                self.db.execute("UPDATE outbox SET created=? WHERE id=?",
                                (time.time() + _ * interval, message.message_id))
                self.event("queued", message.message_id)
            self.db.execute("INSERT INTO metadata VALUES ('seeded', ?)", (str(count),))

    def record(self, event, code=None):
        """Persist a storage observation outside a message processing transaction."""
        with self.db:
            self.event(event, code=code)

    def _queue(self, message):
        self.db.execute("INSERT OR IGNORE INTO outbox VALUES (?,?,?,'pending',?,NULL,NULL)",
                        (message.message_id, message.to_bytes(), message.kind, time.time()))

    def flush(self):
        """Upload stable bytes; a crash after upload is safe to replay at the same path."""
        for row in self.db.execute("SELECT * FROM outbox WHERE status='pending' AND created<=?", (time.time(),)).fetchall():
            message = Envelope.from_bytes(row["body"])
            try:
                self.storage.put(message.path, row["body"], overwrite=True)
            except StorageError as exc:
                with self.db:
                    self.event("storage_error", message.message_id, exc.code)
                if not exc.retryable:
                    raise
                continue
            with self.db:
                self.db.execute("UPDATE outbox SET status='sent', sent=? WHERE id=?",
                                (time.time(), message.message_id))
                self.event("sent", message.message_id)

    def accept(self, path, body):
        """Atomically record the benign processing effect and enqueue its receipt."""
        message = Envelope.from_bytes(body)
        if message.path != path or message.run_id != self.run_id or message.recipient != self.node or message.sender != self.peer:
            raise MessageValidationError("Envelope route or filename mismatch.")
        digest = hashlib.sha256(body).hexdigest()
        with self.db:
            previous = self.db.execute("SELECT digest FROM inbox WHERE id=?", (message.message_id,)).fetchone()
            if previous:
                if previous[0] != digest:
                    raise MessageValidationError("Message ID reused with changed contents.")
                self.event("duplicate_observation", message.message_id)
                return
            if message.kind == "ack":
                original = self.db.execute("SELECT body,status FROM outbox WHERE id=? AND kind='heartbeat'",
                                           (message.correlation_id,)).fetchone()
                if not original or Envelope.from_bytes(original["body"]).acknowledgement() != message:
                    raise MessageValidationError("Unmatched acknowledgement.")
                self.db.execute("UPDATE outbox SET status='acknowledged', acked=? WHERE id=?",
                                (time.time(), message.correlation_id))
                self.event("acknowledged", message.correlation_id)
            else:
                # The entire demonstration effect is this durable inbox row and a receipt.
                self._queue(message.acknowledgement())
                self.event("processed", message.message_id)
            self.db.execute("INSERT INTO inbox VALUES (?,?,?,?)",
                            (message.message_id, digest, message.kind, time.time()))

    def tick(self):
        """Try queued sends and incoming messages; retain files for recovery/audit."""
        self.flush()
        prefix = f"/lab-{self.run_id}-{self.node}-"
        try:
            paths = self.storage.list_files()
        except StorageError as exc:
            with self.db:
                self.event("storage_error", code=exc.code)
            if not exc.retryable:
                raise
            return
        for path in sorted(paths):
            if not path.startswith(prefix) or not path.endswith(".json"):
                continue
            if self.db.execute("SELECT 1 FROM rejected WHERE path=?", (path,)).fetchone():
                continue
            try:
                self.accept(path, self.storage.get(path))
            except MessageValidationError:
                with self.db:
                    self.db.execute("INSERT OR IGNORE INTO rejected VALUES (?)", (path,))
                    self.event("invalid_message", code="validation")
            except StorageError as exc:
                with self.db:
                    self.event("storage_error", code=exc.code)
                if not exc.retryable:
                    raise
        self.flush()

    def summary(self):
        statuses = dict(self.db.execute("SELECT status,count(*) FROM outbox WHERE kind='heartbeat' GROUP BY status"))
        return dict(node=self.node, run_id=self.run_id, heartbeat_status=statuses,
                    processed_heartbeats=self.db.execute("SELECT count(*) FROM inbox WHERE kind='heartbeat'").fetchone()[0],
                    rejected=self.db.execute("SELECT count(*) FROM rejected").fetchone()[0])
