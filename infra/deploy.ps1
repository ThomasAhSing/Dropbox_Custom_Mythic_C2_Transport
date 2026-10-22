param()
$ErrorActionPreference = 'Stop'
if (-not (Get-Command multipass -ErrorAction SilentlyContinue)) {
    throw 'Install Canonical Multipass and enable its supported hypervisor, then rerun.'
}
$projectRoot = Split-Path $PSScriptRoot -Parent
$sourceFiles = @('app_a.py','app_b.py','lab_app.py','lab_node.py','lab_protocol.py',
    'lab_report.py','storage.py','local_storage.py','messages.py','dropbox_storage.py',
    'dropbox_setup.py','requirements.txt')
# Explicit allowlist: credentials, .env, local state, and test files are never transferred.
foreach ($vm in @('dropbox-gw-1','dropbox-gw-2')) {
    & multipass launch 24.04 --name $vm --cpus 2 --memory 2G --disk 8G --cloud-init "$PSScriptRoot/cloud-init.yaml"
    if ($LASTEXITCODE -ne 0) { throw "VM launch failed: $vm (existing VMs are not replaced)" }
    & multipass exec $vm -- cloud-init status --wait
    if ($LASTEXITCODE -ne 0) { throw "cloud-init failed: $vm" }
    foreach ($file in $sourceFiles) {
        & multipass transfer "$projectRoot/$file" "${vm}:/tmp/$file"
        if ($LASTEXITCODE -ne 0) { throw "Transfer failed: $file" }
        & multipass exec $vm -- sudo install -m 0644 "/tmp/$file" "/opt/dropbox-lab/$file"
        if ($LASTEXITCODE -ne 0) { throw "Install failed: $file" }
    }
    & multipass transfer "$PSScriptRoot/configure_gateway.py" "${vm}:/tmp/configure_gateway.py"
    if ($LASTEXITCODE -ne 0) { throw 'Credential helper transfer failed' }
    & multipass exec $vm -- sudo install -m 0644 /tmp/configure_gateway.py /opt/dropbox-lab/configure_gateway.py
    if ($LASTEXITCODE -ne 0) { throw 'Credential helper install failed' }
    & multipass exec $vm -- sudo python3 -m venv /opt/dropbox-lab/.venv
    if ($LASTEXITCODE -ne 0) { throw "venv failed: $vm" }
    & multipass exec $vm -- sudo /opt/dropbox-lab/.venv/bin/python -m pip install -r /opt/dropbox-lab/requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "Dependency install failed: $vm" }
    Write-Host "Prepared $vm. Credentials and service start are manual; see docs/VERIFICATION.md."
}
