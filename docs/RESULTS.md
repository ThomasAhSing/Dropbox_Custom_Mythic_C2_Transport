# Observed results and completion evidence

Recorded October 18, 2026, America/Vancouver. Times in event files are UTC.

## Local process experiments

The runner launched real independent Python processes on Windows/Python 3.13,
using atomic local filesystem storage. These results do not measure Dropbox or
Ubuntu VM performance. Runs were concurrent with each other, so latency values
are demonstrations rather than controlled benchmarks.

| Scenario | Run UUID | Acknowledged | Cross-worker duplicate processing | RTT p95 |
| --- | --- | --- | --- | --- |
| Baseline | e1958c7e-bce9-4e5e-96aa-244c99978663 | 5 A + 5 B | 0 | 0.442 s |
| Kill/restart B | d646ac8c-d924-4e60-90ff-2615c7326176 | 5 A + 5 B | 0 | 3.356 s |
| Two receiver replicas | 409f0d2d-9def-479b-9449-f8d0a4ed2fd5 | 5 A | 5 | 0.257 s |

Both experiments ended with exit codes 0 for final workers and an unacknowledged
fraction of 0. The restarted worker used its original SQLite database. Each report
has per-message RTT samples and a launch/kill timeline. The restart script's two
second outage plus relaunch/polling increased observed latency, as expected.

The replica scenario runs one sender and two node-b receivers with separate
databases. Both receivers process each incoming heartbeat once, producing five
cross-worker processing duplicates for five unique heartbeats. Deterministic
acknowledgements avoid duplicate logical receipts at A. The script and tests
intentionally expose this limitation rather than claim distributed exactly-once
processing. See the latest `artifacts/<run-id>/report.json` for measured latency.

Evidence lives in ignored `artifacts/<run-id>/` folders: report JSON, process logs,
and SQLite databases. Save these alongside any submitted report; they are not
tracked source files. Reproduce using the commands in VERIFICATION.md.

## Automated checks

All 30 automated tests passed. The suite covers the prior setup/storage tests plus durable bidirectional
exchange, response-loss replay, restart state, replica processing counts, invalid
message handling, credential failure sanitization, service credential loading,
expired-access-token refresh dispatch, rate-limit cooldown, and retry bounds.

## Items requiring live lab validation

| Item | Observed status | Required evidence |
| --- | --- | --- |
| Dropbox A↔B exchange | Attempted; no refresh token was available to this execution session | Authorize in the user's terminal, rerun Dropbox baseline/restart, retain reports |
| Revoked refresh credential | Mocked failure tested | Optional real controlled revocation/re-authorization exercise |
| Gateway VM deployment | Scripts prepared; Multipass/hypervisor unavailable here | Two running Ubuntu VMs, service/firewall/credential checks |
| VM failure/recovery | Local process kill/restart measured; VM exercise pending | Stop/start timeline, both VM databases and journals, host sender report |
| Mythic compatibility | Primary documentation and SDK source reviewed | Feasibility report delivered; no live interoperability claim |
| OneDrive comparison | Documentation comparison delivered | Adapter implementation and matched live benchmarks are future work |

The completion criteria for live Dropbox and gateway infrastructure are not
claimed satisfied until those reports exist. No fabricated cloud timings,
deployed VM claims, or Mythic interoperability results are included.
