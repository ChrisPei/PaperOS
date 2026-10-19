$ErrorActionPreference = 'Stop'
$paperosRoot = Split-Path -Parent $PSScriptRoot
$paperosBackup = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\full-backup-state.json') -Raw | ConvertFrom-Json
$paperosWorkflow = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\languagebreak-state.json') -Raw | ConvertFrom-Json
if ($paperosBackup.complete -ne $true -or $paperosWorkflow.root_verified -ne $true) { throw 'Verified complete backup and root are required' }
if ((Get-Volume -DriveLetter G).FileSystemLabel -ne 'Kindle') { throw 'G: is not Kindle' }
$paperosPart = Get-Partition -DriveLetter G
$paperosUsb = Get-CimInstance -ClassName Win32_DiskDrive -Filter ('Index = ' + $paperosPart.DiskNumber)
$paperosHasher = [Security.Cryptography.SHA256]::Create()
$paperosIdentity = [BitConverter]::ToString($paperosHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($paperosUsb.PNPDeviceID))).Replace('-','').ToLowerInvariant()
$paperosHasher.Dispose()
if ($paperosIdentity -ne $paperosBackup.device_usb_identity_sha256) { throw 'Connected Kindle changed' }
$paperosCheck = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\native-preview-validation.json') -Raw | ConvertFrom-Json
$paperosNativeHash = (Get-FileHash -LiteralPath (Join-Path $paperosRoot 'dist\paperos-kt3') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($paperosCheck.passed -ne $true -or $paperosCheck.native_sha256 -ne $paperosNativeHash -or $paperosCheck.kernel -ne '3.10.53-lab126') { throw 'Current native program must pass matching-kernel event and timeout validation' }
$paperosToolCheck = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\backup-toolbox-validation.json') -Raw | ConvertFrom-Json
$paperosToolHash = (Get-FileHash -LiteralPath (Join-Path $paperosRoot 'dist\paperos-backup-tools') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($paperosToolCheck.passed -ne $true -or $paperosToolCheck.sha256 -ne $paperosToolHash) { throw 'Static execution tools changed since validation' }
$paperosPackage = 'G:\paperos\hardware-preview'
if (-not [IO.Path]::GetFullPath($paperosPackage).StartsWith('G:\paperos\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected staging path' }
if (Test-Path -LiteralPath (Join-Path $paperosPackage 'RUNNING.lock')) { throw 'Existing preview is still running or needs inspection' }
New-Item -ItemType Directory -Path $paperosPackage -Force | Out-Null
$paperosOwnerPath = Join-Path $paperosPackage 'OWNER'
$paperosOwner = 'paperos-hardware-preview-v1'
if ((Test-Path -LiteralPath $paperosOwnerPath) -and [IO.File]::ReadAllText($paperosOwnerPath).Trim() -ne $paperosOwner) { throw 'Hardware preview directory belongs to another package' }
[IO.File]::WriteAllText($paperosOwnerPath, $paperosOwner + "`n", [Text.UTF8Encoding]::new($false))
$paperosFiles = @(
    @{source=(Join-Path $paperosRoot 'dist\paperos-kt3'); name='paperos'},
    @{source=(Join-Path $paperosRoot 'dist\paperos-backup-tools'); name='paperos-backup-tools'},
    @{source=(Join-Path $paperosRoot 'assets\NotoSansCJKsc-Regular.otf'); name='font.otf'},
    @{source=(Join-Path $paperosRoot 'build\preview-agents.tsv'); name='agents.tsv'},
    @{source=(Join-Path $paperosRoot 'device-probe\bin\launch-hardware-preview.sh'); name='launch-hardware-preview.sh'},
    @{source=(Join-Path $paperosRoot 'device-probe\bin\run-hardware-preview.sh'); name='run-hardware-preview.sh'}
)
foreach ($paperosFile in $paperosFiles) {
    $paperosTarget = Join-Path $paperosPackage $paperosFile.name
    Copy-Item -LiteralPath $paperosFile.source -Destination $paperosTarget
    if ((Get-FileHash -LiteralPath $paperosFile.source -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $paperosTarget -Algorithm SHA256).Hash) { throw 'Preview copy failed verification' }
}
$paperosSavedWrapper = Join-Path $paperosBackup.directory 'RUNME-before-hardware-preview.sh'
if (-not (Test-Path -LiteralPath $paperosSavedWrapper)) { Copy-Item -LiteralPath 'G:\RUNME.sh' -Destination $paperosSavedWrapper }
$paperosWrapper = "#!/bin/sh`nexec /bin/sh /mnt/us/paperos/hardware-preview/launch-hardware-preview.sh`n"
[IO.File]::WriteAllText('G:\RUNME.sh', $paperosWrapper, [Text.UTF8Encoding]::new($false))
if ([IO.File]::ReadAllText('G:\RUNME.sh') -ne $paperosWrapper) { throw 'Preview launcher copy did not match reviewed command' }
$paperosWorkflow.next_step = 'run_two_minute_native_display_input_preview_then_reconnect_usb'
$paperosWorkflow.updated_utc = (Get-Date).ToUniversalTime().ToString('o')
$paperosWorkflow | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $paperosRoot 'build\languagebreak-state.json') -Encoding utf8
[ordered]@{ staged=$true; verified_package_files=6; timeout_seconds=120; native_sha256=$paperosNativeHash; command=';log runme'; feed='USB snapshot'; writes_block_devices=$false; changes_bootmode=$false } | ConvertTo-Json -Compress
