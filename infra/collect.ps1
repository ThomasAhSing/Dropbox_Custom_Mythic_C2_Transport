param([string]$Output = 'artifacts/gateways')
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Path $Output -Force | Out-Null
foreach ($vm in @('dropbox-gw-1','dropbox-gw-2')) {
    # SQLite backup includes committed WAL data without copying an inconsistent live file.
    & multipass exec $vm -- sudo /opt/dropbox-lab/.venv/bin/python -c "import sqlite3; s=sqlite3.connect('/var/lib/dropbox-lab/worker.sqlite'); d=sqlite3.connect('/tmp/lab-evidence.sqlite'); s.backup(d); d.close(); s.close()"
    if ($LASTEXITCODE -ne 0) { throw "Backup failed: $vm" }
    & multipass exec $vm -- sudo chmod 0644 /tmp/lab-evidence.sqlite
    if ($LASTEXITCODE -ne 0) { throw "Evidence permissions failed: $vm" }
    & multipass transfer "${vm}:/tmp/lab-evidence.sqlite" "$Output/$vm.sqlite"
    if ($LASTEXITCODE -ne 0) { throw "Evidence transfer failed: $vm" }
    & multipass exec $vm -- sudo journalctl -u dropbox-lab --no-pager -o cat |
        Set-Content -LiteralPath "$Output/$vm.jsonl" -Encoding utf8
    if ($LASTEXITCODE -ne 0) { throw "Journal collection failed: $vm" }
}
Write-Host "Evidence saved in $Output. Run lab_report.py on both SQLite files and the app A state."
