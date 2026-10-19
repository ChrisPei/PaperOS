$ErrorActionPreference = 'Stop'
$paperosRoot = Split-Path -Parent $PSScriptRoot
$paperosBackup = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\full-backup-state.json') -Raw | ConvertFrom-Json
if ($paperosBackup.complete -ne $true -or (Get-Volume -DriveLetter G).FileSystemLabel -ne 'Kindle') { throw 'Verified backup and attached Kindle are required' }
$paperosPart = Get-Partition -DriveLetter G
$paperosUsb = Get-CimInstance Win32_DiskDrive -Filter ('Index = ' + $paperosPart.DiskNumber)
$paperosHasher = [Security.Cryptography.SHA256]::Create()
$paperosIdentity = [BitConverter]::ToString($paperosHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($paperosUsb.PNPDeviceID))).Replace('-','').ToLowerInvariant()
$paperosHasher.Dispose()
if ($paperosIdentity -ne $paperosBackup.device_usb_identity_sha256) { throw 'Connected device changed' }
$paperosPayload = Join-Path $paperosRoot 'build\usb-debug'
$paperosManifest = Get-Content -LiteralPath (Join-Path $paperosPayload 'manifest.json') -Raw | ConvertFrom-Json
$paperosValidation = Get-Content -LiteralPath (Join-Path $paperosPayload 'validation.json') -Raw | ConvertFrom-Json
if ($paperosValidation.passed -ne $true -or $paperosValidation.dropbear_sha256 -ne $paperosManifest.files.dropbear -or $paperosValidation.libc_sha256 -ne $paperosManifest.files.'libc.so') { throw 'Current SSH runtime must pass the matching-kernel startup check' }
$paperosAuthValidation = Get-Content -LiteralPath (Join-Path $paperosPayload 'auth-validation.json') -Raw | ConvertFrom-Json
if ($paperosAuthValidation.passed -ne $true -or $paperosAuthValidation.authorized_keys_inside_home -ne $true -or $paperosAuthValidation.dropbear_sha256 -ne $paperosManifest.files.dropbear -or $paperosAuthValidation.libc_sha256 -ne $paperosManifest.files.'libc.so') { throw 'Current SSH runtime must pass full public-key authentication validation' }
$paperosToolProof = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\backup-toolbox-validation.json') -Raw | ConvertFrom-Json
if ($paperosToolProof.passed -ne $true -or (Get-FileHash -LiteralPath (Join-Path $paperosRoot 'dist\paperos-backup-tools')).Hash.ToLowerInvariant() -ne $paperosToolProof.sha256) { throw 'Static tools changed since their kernel validation' }
$paperosTarget = 'G:\paperos\usb-debug'
New-Item -ItemType Directory -Path $paperosTarget -Force | Out-Null
$paperosOwner = Join-Path $paperosTarget 'OWNER'
if ((Test-Path -LiteralPath $paperosOwner) -and [IO.File]::ReadAllText($paperosOwner).Trim() -ne 'paperos-usb-debug-v1') { throw 'Staging directory belongs to another package' }
[IO.File]::WriteAllText($paperosOwner, "paperos-usb-debug-v1`n", [Text.UTF8Encoding]::new($false))
$paperosFiles = @(
    @{source=(Join-Path $paperosRoot 'dist\paperos-backup-tools'); name='paperos-backup-tools'},
    @{source=(Join-Path $paperosRoot 'device-probe\bin\launch-usb-debug.sh'); name='launch-usb-debug.sh'},
    @{source=(Join-Path $paperosRoot 'device-probe\bin\run-usb-debug.sh'); name='run-usb-debug.sh'}
)
foreach ($paperosName in @('dropbear','libc.so','server_host_key','authorized_keys')) {
    if ((Get-FileHash -LiteralPath (Join-Path $paperosPayload $paperosName)).Hash.ToLowerInvariant() -ne $paperosManifest.files.$paperosName) { throw 'Debug payload changed' }
    $paperosFiles += @{source=(Join-Path $paperosPayload $paperosName); name=$paperosName}
}
foreach ($paperosFile in $paperosFiles) {
    $paperosDestination = Join-Path $paperosTarget $paperosFile.name
    Copy-Item -LiteralPath $paperosFile.source -Destination $paperosDestination
    if ((Get-FileHash -LiteralPath $paperosFile.source).Hash -ne (Get-FileHash -LiteralPath $paperosDestination).Hash) { throw 'Copy verification failed' }
}
$paperosSaved = Join-Path $paperosBackup.directory 'RUNME-before-usb-debug.sh'
if (-not (Test-Path -LiteralPath $paperosSaved)) { Copy-Item -LiteralPath 'G:\RUNME.sh' -Destination $paperosSaved }
$paperosPreviewArchive = Join-Path $paperosBackup.directory 'hardware-preview'
New-Item -ItemType Directory -Path $paperosPreviewArchive -Force | Out-Null
foreach ($paperosName in @('status.txt','report.json','preview.log','launch.log','note.txt')) {
    $paperosPreviewFile = Join-Path 'G:\paperos\hardware-preview' $paperosName
    if (Test-Path -LiteralPath $paperosPreviewFile) { Copy-Item -LiteralPath $paperosPreviewFile -Destination (Join-Path $paperosPreviewArchive $paperosName) }
}
[IO.File]::WriteAllText('G:\RUNME.sh', "#!/bin/sh`nexec /bin/sh /mnt/us/paperos/usb-debug/launch-usb-debug.sh`n", [Text.UTF8Encoding]::new($false))
[ordered]@{staged=$true; verified_files=$paperosFiles.Count; writes_block_devices=$false; changes_bootmode=$false; usb_debug_address='169.254.28.2:2222'; timeout_without_connection_seconds=900} | ConvertTo-Json -Compress
