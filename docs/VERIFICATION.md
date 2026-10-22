# Lab setup and verification

Run PowerShell commands from the project directory. Use Python 3.10 or newer.
All traffic in this prototype is a fixed heartbeat or acknowledgement, never a task.

## Installation and regression checks

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Expected: all tests pass. The new `tests/test_lab.py` exercises both directions,
duplicate detection, restart persistence, an upload that commits before the
connection fails, invalid JSON, identity mismatch, timeouts, authentication errors,
and retry exhaustion. Tests use local storage or mocks and require no credentials.
`requirements.lock.txt` is the earlier Windows snapshot; use requirements.txt on
Ubuntu and save `python -m pip freeze` with experiment evidence to record versions.

## 3. Two independent applications

Quick local experiment (starts A and B as separate operating-system processes):

```powershell
.\.venv\Scripts\python.exe run_lab.py --scenario baseline
```

Expected: exit code 0, five acknowledged heartbeats per application, ten RTT
samples, zero unacknowledged fraction, zero cross-worker duplicate processing.
The printed evidence directory contains SQLite state, structured logs, and
`report.json`. Duplicate observations are normal: the polling loop sees retained
files again, but does not repeat the processing transaction.

For real Dropbox, authorize using the same app key and Dropbox account on both
endpoints. Separate accounts have separate App Folders and will not see each other.

```powershell
.\.venv\Scripts\python.exe dropbox_setup.py auth
.\.venv\Scripts\python.exe run_lab.py --provider dropbox --duration 120 --scenario baseline
```

Expected: the same five acknowledged heartbeats in both directions, with measured
Dropbox RTTs. Every run uses a fresh UUID. Files are retained in the App Folder
with a `lab-<run-id>-...json` prefix; remove only that run's files after reviewing
evidence. No existing user file is deleted by this lab.

To run the applications yourself, generate one UUID:

```powershell
[guid]::NewGuid().ToString()
```

Replace `RUN_UUID` with that value in both terminals, then start these at roughly
the same time:

```powershell
# Terminal A
.\.venv\Scripts\python.exe app_a.py --run-id RUN_UUID --state lab-data/a.sqlite --duration 120
# Terminal B
.\.venv\Scripts\python.exe app_b.py --run-id RUN_UUID --state lab-data/b.sqlite --duration 120
```

Expected: `queued`, `sent`, `processed`, and `acknowledged` events; the final
summary has `heartbeat_status: {"acknowledged": 3}` on each side. A file belongs
to exactly one node/run identity; use new state paths for a new run. Never share
one SQLite state file between separate processes or VMs.

## 4. Reliability, validation, credentials, and observation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_lab.py -v
.\.venv\Scripts\python.exe run_lab.py --scenario restart
```

Expected: all reliability tests pass. The restart runner kills B after 1.5 seconds,
waits 2 seconds, restarts it using the same database, and still ends with five
acknowledged heartbeats on each side. The report timeline records kill/relaunch
times; SQLite events record processing and acknowledgement times. Longer RTTs
during this outage are expected. The acknowledgement outbox is committed in the
same transaction as processing, so a crash between processing and upload can
recover. Files are retained so a replacement worker can replay them.

Dropbox operations retry eligible failures at most three times per operation.
Backoff has jitter; the maximum scheduled sleep is 8 seconds. A server-requested
wait longer than 8 seconds is surfaced and remembered as an in-process cooldown;
later polling cycles make no provider request until it expires. Calls have a 15-second SDK socket timeout;
this is not an absolute wall-clock deadline for the entire process or token refresh.
SDK-internal error/rate-limit retries are disabled to avoid nested retry loops.
Only idempotent overwrites and reads are automatically retried. A create-only
upload may have committed when its response is lost and is deliberately not
blindly retried. The heartbeat outbox safely uses stable paths and identical bytes.

Transient failures leave messages pending. Authentication and permanent API
errors stop the process with a clear sanitized fatal record and exit 1; do not
retry revoked credentials forever. Expired short-lived access tokens are refreshed
by the SDK using the saved refresh token. Revoked/invalid refresh tokens require
`auth` again. Exit 2 means heartbeats remain unacknowledged at the run deadline;
it is not proof that they were permanently lost. Restart with the same state to
continue. Exit 130 indicates an interactive interruption.

Invalid envelopes are recorded once per path in the worker's `rejected` table
and skipped thereafter. They never trigger a receipt. Corrected data should use
a new message ID/path. Tests also prove valid messages continue after rejection.
Envelope validation rejects unsupported versions, extra/duplicate fields, invalid
IDs/timestamps/routes, changed contents under an existing ID, unknown receipts,
and JSON above 4096 bytes. The SDK still buffers downloads before validation;
the prototype is intended for a controlled, small lab folder, not hostile bulk input.

Credentials are read from the OS keyring, an injected `DROPBOX_REFRESH_TOKEN`, or
a systemd credential. `.env`, SQLite files, evidence, and `*.secret` are ignored
by Git. Put only the public app key in .env. Never commit tokens. Events contain
IDs, timestamps, status, and error categories; provider exception bodies and message
contents are not logged. Failed authentication and timeout tests use sentinel
secrets and assert that safe errors do not reveal them.

For a manual connection interruption on an Ubuntu lab VM, briefly block HTTPS
egress using its console while host app A continues sending:

```bash
sudo ufw insert 1 deny out 443/tcp
# Wait about 20 seconds; expect retry/storage_error events, no false acknowledgement.
sudo ufw delete deny out 443/tcp
sudo journalctl -u dropbox-lab --no-pager -o cat
```

Expected: processing resumes, pending messages are acknowledged, and events retain
the outage evidence. Remove the temporary rule even if the test is interrupted.

## 5. Two isolated Ubuntu gateway VMs

Prerequisites: Canonical Multipass 1.14 or newer with a supported hypervisor, capacity for two
2-CPU/2-GB/8-GB VMs, and approved outbound Dropbox HTTPS access. No hypervisor was
available in the development environment; these steps require your lab machine.

```powershell
powershell -File infra/deploy.ps1
multipass list
```

Expected: `dropbox-gw-1` and `dropbox-gw-2` running Ubuntu 24.04. The script copies
an allowlist of source files, installs dependencies, and does not copy .env or
credentials. It refuses to replace an existing VM. Each VM has its own disk and
SQLite database. Inbound traffic is blocked except SSH for Multipass management;
no application listener is opened. Outbound traffic remains allowed for package
installation, DNS, time synchronization, and Dropbox. This is host firewall
isolation, not a separate physical network or a hardened production deployment.
Cloud-init usage follows [Canonical's guide](https://canonical.com/multipass/docs/latest/how-to-guides/manage-instances/launch-customized-instances-with-multipass-and-cloud-init/).

Generate a fresh UUID for the experiment, then configure each gateway interactively:

```powershell
multipass shell dropbox-gw-1
```

Inside the VM:

```bash
sudo /opt/dropbox-lab/.venv/bin/python /opt/dropbox-lab/configure_gateway.py
sudo systemctl start dropbox-lab
sudo systemctl is-active dropbox-lab
sudo ufw status
sudo stat -c '%a %U' /etc/dropbox-lab/token
exit
```

Repeat on `dropbox-gw-2`. Use the same app key/account/run UUID on both. Leave the
hidden token prompt empty to authorize in your host browser and paste the code
back into the VM. The helper saves a root-owned mode-600 token; systemd uses
[`LoadCredential`](https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html#LoadCredential=ID:PATH) to expose it to the unprivileged service. Tokens do not travel in
command arguments or shell history. Expected: `active`, incoming deny policy,
and `600 root`. Services are deliberately not enabled at boot; start manually
after a VM restart. They have a bounded 24-hour lab runtime.

Start app A on the host with that same UUID and a new state file:

```powershell
.\.venv\Scripts\python.exe app_a.py --run-id RUN_UUID --state lab-data/gateway-a.sqlite --heartbeats 20 --heartbeat-interval 3 --duration 180
```

While A runs, use another host terminal:

```powershell
# Wait until both gateway journals contain processed events, then simulate loss.
multipass stop --force dropbox-gw-1
# Keep it down about 20 seconds while A continues. Gateway 2 should acknowledge.
multipass start dropbox-gw-1
multipass exec dropbox-gw-1 -- sudo systemctl start dropbox-lab
```

Record the UTC times of stop, start, and the first processed event after recovery.
Expected: A continues receiving acknowledgements from gateway 2, gateway 1 resumes
using its persistent database, and each gateway processes each ID at most once
locally. Both gateways may process the same heartbeat: the aggregate report must
show these cross-worker duplicates, not hide them. The benign effect is just a
SQLite receipt record. Do not infer safety for external side effects from this.

After A finishes:

```powershell
powershell -File infra/collect.ps1
.\.venv\Scripts\python.exe lab_report.py lab-data/gateway-a.sqlite artifacts/gateways/dropbox-gw-1.sqlite artifacts/gateways/dropbox-gw-2.sqlite --output artifacts/gateways/report.json
```

Expected: twenty acknowledged A heartbeats, no local repeated processing, and
measured cross-worker duplicates. Collection uses SQLite backup, including WAL
state, rather than copying a live database file unsafely. Save journals, VM/cloud-init
status, stop/restart times, and the report. Compute recovery time as first new
processing time minus service restart time; measure a period with traffic arriving.
Stop the services/VMs when done. Reusing the same run/state is a restart test;
for a new run, archive evidence and choose a fresh state file/run identity.

## 6. Mythic architecture research

Read [RESEARCH.md](RESEARCH.md). Check each cited interface against a pinned SDK
revision before any future integration. Expected deliverable: a separation of
transport, profile lifecycle, protocol translation, and agent behaviour, plus an
explicit compatibility gap assessment. No Mythic server, agent, profile, or tasking
is installed or executed by this repository.

## 7. Measurements and provider comparison

```powershell
.\.venv\Scripts\python.exe run_lab.py --scenario replicas
.\.venv\Scripts\python.exe run_lab.py --provider dropbox --duration 120 --scenario restart
```

Use the report path printed by each run. Compare `ack_roundtrip_seconds` p50/p95,
`unacknowledged_fraction`, event counts, and `cross_worker_duplicate_processing`.
Dropbox reports also include `storage_attempt_failure_rate`: failed adapter
attempts divided by total adapter attempts, including retried attempts. Listing
one complete folder is one adapter attempt even if it spans multiple API pages.
Local runs report null for this Dropbox-specific measure. This is not the same
as a message loss rate or the provider's fleet-wide error rate. Small samples
are demonstrations; repeat with recorded polling intervals and run lengths for
performance conclusions. RTT uses one sender clock and includes polling; it is
not a measured one-way delivery latency.

Read the OneDrive comparison in [RESEARCH.md](RESEARCH.md). A OneDrive adapter is
future work; the existing protocol does not need changes to replace the provider.
See [RESULTS.md](RESULTS.md) for the actual local evidence and unverified lab items.
