# Python files: recommended reading order

**File roles:** The review table includes an **Example usage or integration
component?** column for every Python file. `lab_app.py` is an example lab
application. The reusable transport components are `storage.py`,
`dropbox_storage.py`, and the authentication/client helpers in `dropbox_setup.py`.
Mythic integration has not been implemented, so final runtime dependencies are
not yet confirmed.

## What this system is

This project is a lab prototype for exchanging messages between two independent
Python applications through shared file storage. Instead of connecting directly
to each other, the applications upload JSON message files to a Dropbox App Folder
and periodically check that folder for incoming messages. A local-folder storage
option lets us run the same messaging logic offline.

The main demonstration exchanges harmless heartbeats ("I am here") and
acknowledgements ("I received your heartbeat") in both directions. It explores
reliable delivery, recovery after interruption, and what happens when two gateway
workers process the same messages. It does not execute commands or operational
C2 tasks.

## Features available

- **Dropbox authentication:** initial browser authorization and saved refresh
  credentials support subsequent unattended runs. The Dropbox SDK refreshes
  short-lived access tokens automatically.
- **Interchangeable storage:** a shared interface supports Dropbox and local
  filesystem providers, keeping cloud SDK calls separate from messaging logic.
- **Validated JSON messages:** versioned formats include unique message IDs and
  UTC timestamps. The heartbeat format also includes sender, recipient, message
  kind, run ID, and acknowledgement correlation.
- **Two-way messaging:** independently running applications A and B can send
  heartbeats and acknowledge messages received from their peer.
- **Persistent message tracking:** SQLite records pending, sent, and acknowledged
  heartbeats, received message IDs, and processing events so restarts can resume
  work using the same state file.
- **Duplicate detection:** each worker avoids processing the same message twice
  within its retained database. Reports also measure processing duplicated across
  independent gateway workers; there is no distributed exactly-once guarantee.
- **Failure handling:** bounded retries, timeouts, rate-limit cooldown, sanitized
  errors, and invalid-message quarantine support controlled failure experiments.
- **Experiment automation and measurements:** a runner starts separate processes
  for baseline, kill/restart, and replica scenarios. Reports summarize round-trip
  latency, acknowledgements, failures, and duplicate processing.
- **Ubuntu gateway preparation:** deployment and credential-configuration scripts
  prepare two separate gateway VMs, with instructions for failure/recovery tests
  and evidence collection.
- **Tests and documentation:** automated tests cover normal exchange and common
  failure scenarios. Guides explain setup, verification, architecture, Mythic
  feasibility research, and the changes needed for a future OneDrive provider.

The earlier version-1 text-message CLI is also available for manually sending,
reading, listing, and deleting simple text messages. It is separate from the
version-2 heartbeat demonstration.

## What has been verified

Automated tests and local experiments have demonstrated two-way exchange,
process restart recovery, and duplicate processing across replicas. Live Dropbox
exchange still needs verification from a session with an available refresh token.
Ubuntu VM deployment and VM failure/recovery measurements also remain lab checks.
Mythic work is documentation research only; a OneDrive adapter is not implemented.
See [RESULTS.md](RESULTS.md) for the recorded evidence and remaining checks.

## Recommended reading order

Read the main heartbeat application first, then its storage implementation,
experiments, and tests. The earlier text-message demonstration comes afterward
because it is separate from the heartbeat application.

| Order | File | Example usage or integration component? | What it does | What to look at while reviewing |
| --- | --- | --- | --- | --- |
| 1 | [app_a.py](../app_a.py) | **Example entry point.** Starts node A for the lab; not required by a future integration. | Starts the lab application with the default identity `node-a`. | Follow its call to `lab_app.main()`. This small entry point does not contain the messaging logic. |
| 2 | [app_b.py](../app_b.py) | **Example entry point.** Starts node B for the lab; not required by a future integration. | Starts a separate instance of the same application with the identity `node-b`. | Compare it with app A: both use the same implementation but run as independent processes. |
| 3 | [lab_app.py](../lab_app.py) | **Lab application / example usage.** Composes the transport for heartbeat experiments. Its CLI, finite polling loop, and lab-node setup are not an implemented Mythic runtime. | Reads terminal options, selects storage, opens the node's SQLite state, and runs its polling loop. | Follow configuration → client/provider creation → node creation → `seed()` → repeated `tick()` calls. Check exit codes and fatal error reporting. |
| 4 | [lab_protocol.py](../lab_protocol.py) | **Lab-only protocol.** Heartbeat/ack envelopes demonstrate exchange; they are not Mythic messages and are not required as-is after integration. | Defines the version-2 heartbeat and acknowledgement envelopes, their JSON format, routing, and validation. | Review `Envelope`, `heartbeat()`, `acknowledgement()`, `path`, and `from_bytes()`. Notice that acknowledgements have deterministic IDs and no arbitrary task payload is accepted. |
| 5 | [storage.py](../storage.py) | **Reusable transport core.** Intended storage boundary to retain if the integration uses this provider abstraction; not Mythic-specific. | Defines the provider-independent storage contract: `put`, `get`, `list_files`, and `delete`, plus the shared `StorageError`. | This is the boundary that lets messaging code work with Dropbox or a local folder. Check the overwrite behaviour and retryable error information. |
| 6 | [lab_node.py](../lab_node.py) | **Lab implementation / design reference.** Demonstrates durable delivery tracking with SQLite. State/recovery ideas may be reused, but this heartbeat node is not an essential Mythic component as-is. | Implements durable heartbeat exchange, acknowledgements, message statuses, duplicate detection, and invalid-message quarantine. | Follow `seed()` → `flush()` → `tick()` → `accept()`. Review the SQLite outbox/inbox tables and the transaction that records processing and queues its acknowledgement together. |
| 7 | [dropbox_setup.py](../dropbox_setup.py) | **Mixed: reusable authentication + setup/diagnostics.** Client/credential helpers are candidates for reuse; browser setup, verification, and manual upload commands are tooling rather than the integrated runtime. | Handles initial browser authorization, credential retrieval, authenticated client creation, connection verification, and local-file upload. | Start with `app_key()` and `client()`, which are reused by the applications. Then review `authenticate()` for initial consent and `verify()` for diagnostics. Check `main()` for the commands and any additional upload call currently attached to verification. |
| 8 | [dropbox_storage.py](../dropbox_storage.py) | **Reusable Dropbox transport core.** Candidate Dropbox backend for the integration; still needs integration-specific validation and wiring. | Implements the storage contract using the Dropbox SDK, including pagination, download cleanup, bounded retries, and rate-limit cooldown. | Compare its four storage methods with `storage.py`. Then review `_operation()` to see which failures are retried and how SDK errors become `StorageError`. |
| 9 | [local_storage.py](../local_storage.py) | **Offline test support.** Useful for development and tests; not required in a Dropbox-backed deployment. | Implements the same storage contract using a local directory for offline experiments. | Compare it with the Dropbox provider. Review path containment and how temporary files prevent partially written messages from becoming visible. |
| 10 | [run_lab.py](../run_lab.py) | **Lab experiment runner.** Launches and interrupts demonstration processes; not required by the integrated runtime. | Starts independent lab processes for baseline exchange, kill/restart recovery, or two-receiver experiments, and saves their evidence. | Review process arguments, separate state files, the restart timeline, and how process exit codes affect the final result. |
| 11 | [lab_report.py](../lab_report.py) | **Lab reporting tool.** Analyzes experiment evidence; not required by the integrated runtime. | Reads SQLite evidence and calculates acknowledgement counts, round-trip latency, storage attempt failure rates, and duplicate processing across workers. | Review metric definitions. Repeated polling observations differ from processing on multiple replicas; unacknowledged messages at a deadline are not automatically proven lost. |
| 12 | [tests/test_lab.py](../tests/test_lab.py) | **Development tests.** Retain/adapt for regression testing; not deployed as runtime components. | Tests heartbeat exchange in both directions, recovery, duplicates, invalid inputs, credential handling, and retry limits. | Compare each failure scenario with `LabNode` and the adapter. Tests use local storage or mocks rather than a live Dropbox account. |
| 13 | [tests/test_dropbox_setup.py](../tests/test_dropbox_setup.py) | **Development tests.** Validate setup/diagnostics; not deployed as runtime components. | Tests OAuth configuration and the upload/list/download/delete verification flow using mocked Dropbox responses. | Review cleanup after failures, revision-safe deletion, missing configuration, and refresh-token storage without printing the token. |
| 14 | [messages.py](../messages.py) | **Mostly example messaging + shared helpers.** The v1 message format/transport is a demonstration, not a Mythic protocol. Current lab code imports its ID validation and validation exception; those helpers could be separated if examples are removed. | Defines the earlier version-1 text-message format and its provider-independent send/receive/list/delete operations. Also contains shared ID validation used by the lab protocol. | Compare `TestMessage` with the version-2 `Envelope`. These are separate demonstrations; the heartbeat application does not use `MessageTransport`. |
| 15 | [message_cli.py](../message_cli.py) | **Example usage / manual CLI.** Demonstrates composing Dropbox with v1 messaging; not required by the integrated runtime. | Exposes the version-1 text-message demonstration through terminal commands. | Follow how it connects the authenticated Dropbox client, storage adapter, and `MessageTransport`. Compare this small composition point with `lab_app.py`. |
| 16 | [tests/test_transport.py](../tests/test_transport.py) | **Development tests.** Adapter tests remain useful; v1 message tests cover the example. Neither runs as part of the deployed transport. | Tests the storage adapter and version-1 messages, including pagination, download cleanup, validation, and error translation. | Review the in-memory provider: it demonstrates that messaging does not require Dropbox-specific calls. |
| 17 | [infra/configure_gateway.py](../infra/configure_gateway.py) | **Lab deployment tooling.** Configures the current Ubuntu heartbeat service; future integration needs its own deployment configuration, so this script is not essential as-is. | Runs inside an Ubuntu gateway VM to configure the app key, run UUID, and refresh credential for the systemd service. | Review hidden credential input, optional browser authorization, root-only file permissions, and how it avoids placing tokens in shell arguments or logs. |

## Example applications versus reusable transport

`lab_app.py` is the runnable heartbeat lab application: it shows how to configure
and connect the provider, credentials, and `LabNode`, then run the experiment.
`app_a.py` and `app_b.py` are convenience entry points into that application.
They are necessary to run the current demonstration through those entry points,
but are not essential parts of a future Mythic integration.

The reusable transport candidates are `storage.py`, `dropbox_storage.py`, and
the authentication/client helpers in `dropbox_setup.py`. The heartbeat envelopes,
SQLite-backed `LabNode`, experiment runner, and reports support the lab. Their
reliability patterns can inform later work without requiring those files to be
used unchanged.

**No Mythic integration is implemented yet.** The table describes current roles
and candidates for reuse, not a confirmed final deployment. Integration-specific
protocol handling, lifecycle/configuration, and compatibility checks remain
separate work; the current heartbeat application does not provide them. See
[RESEARCH.md](RESEARCH.md#mythic-profile-and-agent-boundaries).

The main lab runtime relationship is:

```text
app_a.py / app_b.py
        ↓
lab_app.py — selects configuration and storage
        ↓
lab_node.py — exchanges validated lab_protocol.py envelopes
        ↓
storage.py — common contract
        ↓
dropbox_storage.py OR local_storage.py
```

For the Ubuntu deployment and the exact commands to verify each stage, continue
with [VERIFICATION.md](VERIFICATION.md). For design decisions and the research
assessment, read [RESEARCH.md](RESEARCH.md).
