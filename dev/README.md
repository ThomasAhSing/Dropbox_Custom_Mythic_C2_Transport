# Development and lab files

Everything here supports examples, experiments, verification, or local development.
It is not a production Mythic integration. Run module commands from the project
root so imports and the root `.env` resolve consistently.

| Folder/file | Purpose |
| --- | --- |
| `lab/` | Fixed heartbeat/ack applications, experiment runner, SQLite state logic, and reports |
| `examples/` | Earlier text-message format and manual CLI |
| `tools/dropbox_setup.py` | Browser authorization, file verification, listing, and explicit manual uploads |
| `local_storage.py` | Offline filesystem provider |
| `tests/` | Mocked/provider-independent regression tests |
| `infra/` | Deployment and collection scripts for heartbeat lab VMs, not Mythic |
| `fixtures/` | Example local input files |
| `artifacts/` | Existing and new experiment evidence; ignored by Git |
| `requirements.lock.txt` | Recorded Windows development dependency versions |
| `usage.txt` | Personal usage notes |

Examples (use `.venv/bin/python` on Ubuntu):

```powershell
.\.venv\Scripts\python.exe -m dev.tools.dropbox_setup auth
.\.venv\Scripts\python.exe -m dev.tools.dropbox_setup verify
.\.venv\Scripts\python.exe -m dev.lab.run_lab --scenario baseline
.\.venv\Scripts\python.exe -m dev.lab.run_lab --scenario restart
.\.venv\Scripts\python.exe -m dev.examples.message_cli list
.\.venv\Scripts\python.exe -m unittest discover -s dev/tests -v
```

`verify` only exchanges its own synthetic test file. A manual upload is now an
explicit operation, with paths supplied by the caller:

```powershell
.\.venv\Scripts\python.exe -m dev.tools.dropbox_setup upload dev/fixtures/test.txt /test2.txt
```

Manual upload overwrites the destination file. Verification does not invoke it.

Existing evidence was moved from `artifacts/` to `dev/artifacts/` without changing
its contents. Absolute paths recorded inside historical evidence may still refer
to the original location. Existing `.venv`, `.tmp`, and Python cache directories
stay in place as ignored environment files; relocating a virtual environment can
break its interpreter paths. The root `.env` stays in place for configuration.
