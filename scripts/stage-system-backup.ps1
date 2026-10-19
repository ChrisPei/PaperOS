$ErrorActionPreference = 'Stop'
$paperosRoot = Split-Path -Parent $PSScriptRoot
$paperosWorkflow = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\languagebreak-state.json') -Raw | ConvertFrom-Json
$paperosBackup = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\full-backup-state.json') -Raw | ConvertFrom-Json
if ($paperosWorkflow.root_verified -ne $true -or -not $paperosBackup.p4_sha256) { throw 'Verified root and USB partition backup are required' }
if ((Get-Volume -DriveLetter G).FileSystemLabel -ne 'Kindle') { throw 'G: is not Kindle' }
$paperosPart = Get-Partition -DriveLetter G
$paperosUsb = Get-CimInstance -ClassName Win32_DiskDrive -Filter ('Index = ' + $paperosPart.DiskNumber)
$paperosHasher = [Security.Cryptography.SHA256]::Create()
$paperosIdentity = [BitConverter]::ToString($paperosHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($paperosUsb.PNPDeviceID))).Replace('-','').ToLowerInvariant()
$paperosHasher.Dispose()
if ($paperosIdentity -ne $paperosWorkflow.device_usb_identity_sha256) { throw 'Connected Kindle changed' }
if ((Get-Volume -DriveLetter G).SizeRemaining -lt 1GB) { throw 'Not enough user storage for system backup staging' }
if (Test-Path -LiteralPath 'G:\paperos\recovery-backup\RUNNING.lock') { throw 'Inspect the running backup before replacing its package' }
$paperosCheck = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\snapshot-validation.json') -Raw | ConvertFrom-Json
if ($paperosCheck.passed -ne $true) { throw 'Matching-kernel snapshot validation must pass first' }
$paperosCurrentHash = (Get-FileHash -LiteralPath (Join-Path $paperosRoot 'dist\paperos-snapshot') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($paperosCurrentHash -ne $paperosCheck.snapshot_binary_sha256) { throw 'Snapshot binary changed since validation' }
$paperosToolCheck = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\backup-toolbox-validation.json') -Raw | ConvertFrom-Json
$paperosToolHash = (Get-FileHash -LiteralPath (Join-Path $paperosRoot 'dist\paperos-backup-tools') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($paperosToolCheck.passed -ne $true -or $paperosToolCheck.sha256 -ne $paperosToolHash -or $paperosToolCheck.kernel -ne '3.10.53-lab126') { throw 'Matching-kernel static toolbox validation must pass first' }
$paperosScriptHash = (Get-FileHash -LiteralPath (Join-Path $paperosRoot 'device-probe\bin\backup-system.sh') -Algorithm SHA256).Hash.ToLowerInvariant()
if ($paperosToolCheck.backup_system_sha256 -ne $paperosScriptHash) { throw 'Backup preflight script changed since validation' }
$paperosPackage = 'G:\paperos\recovery'
if (-not [IO.Path]::GetFullPath($paperosPackage).StartsWith('G:\paperos\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected staging path' }
New-Item -ItemType Directory -Path $paperosPackage -Force | Out-Null
$paperosCopyFiles = @(
    @{source=(Join-Path $paperosRoot 'dist\paperos-snapshot'); name='paperos-snapshot'},
    @{source=(Join-Path $paperosRoot 'dist\paperos-backup-tools'); name='paperos-backup-tools'},
    @{source=(Join-Path $paperosRoot 'device-probe\bin\backup-system.sh'); name='backup-system.sh'},
    @{source=(Join-Path $paperosRoot 'device-probe\bin\launch-system-backup.sh'); name='launch-system-backup.sh'}
)
foreach ($paperosFile in $paperosCopyFiles) {
    $paperosTarget = Join-Path $paperosPackage $paperosFile.name
    Copy-Item -LiteralPath $paperosFile.source -Destination $paperosTarget
    if ((Get-FileHash -LiteralPath $paperosFile.source -Algorithm SHA256).Hash -ne (Get-FileHash -LiteralPath $paperosTarget -Algorithm SHA256).Hash) { throw 'Backup package copy failed verification' }
}
$paperosWrapperPath = 'G:\RUNME.sh'
$paperosOriginalWrapper = Join-Path $paperosBackup.directory 'RUNME-before-system-backup.sh'
if (-not (Test-Path -LiteralPath $paperosOriginalWrapper)) { Copy-Item -LiteralPath $paperosWrapperPath -Destination $paperosOriginalWrapper }
$paperosWrapper = "#!/bin/sh`nexec /bin/sh /mnt/us/paperos/recovery/launch-system-backup.sh`n"
[IO.File]::WriteAllText($paperosWrapperPath, $paperosWrapper, [Text.UTF8Encoding]::new($false))
if ([IO.File]::ReadAllText($paperosWrapperPath) -ne $paperosWrapper) { throw 'RUNME wrapper did not match reviewed backup command' }
$paperosWorkflow.next_step = 'run_system_backup_then_wait_for_done_before_usb'
$paperosWorkflow.updated_utc = (Get-Date).ToUniversalTime().ToString('o')
$paperosWorkflow | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $paperosRoot 'build\languagebreak-state.json') -Encoding utf8
[ordered]@{ staged=$true; verified_package_files=4; launcher='v3 with static ARM tools, synchronous logs and separate session'; command=';log runme'; writes_block_devices=$false; temporarily_freezes_p2_p3=$true } | ConvertTo-Json -Compress
