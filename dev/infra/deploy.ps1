param()
$ErrorActionPreference = 'Stop'
if (-not (Get-Command multipass -ErrorAction SilentlyContinue)) {
    throw 'Install Canonical Multipass and enable its supported hypervisor, then rerun.'
}
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$sourceFiles = @('storage.py','dropbox_storage.py','dropbox_client.py','requirements.txt',
    'dev/__init__.py','dev/local_storage.py','dev/lab/__init__.py',
    'dev/lab/lab_app.py','dev/lab/lab_node.py','dev/lab/lab_protocol.py',
    'dev/examples/__init__.py','dev/examples/messages.py','dev/infra/__init__.py',
    'dev/infra/configure_gateway.py')
# Explicit allowlist: credentials, .env, local state, and test files are never transferred.
foreach ($vm in @('dropbox-gw-1','dropbox-gw-2')) {
    & multipass launch 24.04 --name $vm --cpus 2 --memory 2G --disk 8G --cloud-init "$PSScriptRoot/cloud-init.yaml"
    if ($LASTEXITCODE -ne 0) { throw "VM launch failed: $vm (existing VMs are not replaced)" }
    & multipass exec $vm -- cloud-init status --wait
    if ($LASTEXITCODE -ne 0) { throw "cloud-init failed: $vm" }
    foreach ($file in $sourceFiles) {
        & multipass transfer "$projectRoot/$file" "${vm}:/tmp/dropbox-lab-source.py"
        if ($LASTEXITCODE -ne 0) { throw "Transfer failed: $file" }
        & multipass exec $vm -- sudo install -D -m 0644 "/tmp/dropbox-lab-source.py" "/opt/dropbox-lab/$file"
        if ($LASTEXITCODE -ne 0) { throw "Install failed: $file" }
    }
    & multipass exec $vm -- sudo python3 -m venv /opt/dropbox-lab/.venv
    if ($LASTEXITCODE -ne 0) { throw "venv failed: $vm" }
    & multipass exec $vm -- sudo /opt/dropbox-lab/.venv/bin/python -m pip install -r /opt/dropbox-lab/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency install failed: $vm" }
    Write-Host "Prepared $vm. Credentials and service start are manual; see docs/VERIFICATION.md."
}
