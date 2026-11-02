# Integration boundaries and current implementation

The current implementation provides generic Dropbox byte storage and credentials,
plus a separate heartbeat lab. It does not register a Mythic profile, communicate
with a Mythic backend, or implement a Mythic agent transport.

## Reusable root modules

| Module | Responsibility |
| --- | --- |
| `storage.py` | Byte-storage protocol and provider-independent storage errors |
| `dropbox_storage.py` | Dropbox byte-storage adapter and bounded provider retries |
| `dropbox_client.py` | Public app key, minimum scopes, credential retrieval, SDK client |

These modules do not import the development package, contain a polling loop, or
depend on heartbeat JSON or SQLite. They are reusable components, not a claim of
production readiness or Mythic interoperability.

## Unimplemented integration decisions

The selected endpoint/agent and a pinned Mythic version must determine any future
compatibility assessment. Important boundaries to document are:

- Profile registration/configuration versus the communications program.
- Agent scheduling versus transport-specific file discovery.
- Expected message identity and format versus the lab heartbeat schema.
- Credentials, lifecycle, and observability for each separately running service.
- Recovery and duplicate handling, particularly if more than one gateway exists.

The lab keeps its original heartbeat-only behaviour. It is not extended to execute
commands or forward agent traffic into Mythic. Its tests verify byte exchange and
the lab's delivery model, not end-to-end Mythic compatibility.

## Configuration and tooling

Both example applications and the setup CLI read the root `.env`. Reusable client
creation reads the environment and supports the OS keyring or systemd credentials;
callers control configuration loading. Existing credential-store service names
and app-key identifiers are unchanged, so moving the source does not require a
new authorization by itself.

Run setup with `python -m dev.tools.dropbox_setup` and lab applications with
`python -m dev.lab.app_a` / `python -m dev.lab.app_b` from the project root.
The lab VM deployment allowlist preserves the new package directories.
