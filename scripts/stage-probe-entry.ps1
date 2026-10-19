param([Parameter(Mandatory=$true)][string]$BackupDirectory)
$ErrorActionPreference = 'Stop'
$paperosRoot = Split-Path -Parent $PSScriptRoot
$paperosVolume = Get-Volume -DriveLetter G
if ($paperosVolume.FileSystemLabel -ne 'Kindle') { throw 'G: is not Kindle' }
$paperosBackup = (Resolve-Path -LiteralPath $BackupDirectory).Path
if (-not $paperosBackup.StartsWith((Join-Path $paperosRoot 'backups') + '\')) { throw 'Expected a private workspace backup' }
$paperosBackupReport = Get-Content -LiteralPath (Join-Path $paperosBackup 'manifest.json') -Raw | ConvertFrom-Json
if (-not $paperosBackupReport.complete -or $paperosBackupReport.scope -ne 'exported-user-storage-only') { throw 'User-storage backup is not complete' }
$paperosSource = Join-Path $paperosRoot 'build\probe-entry'
$paperosRecord = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\probe-entry-source.json') -Raw | ConvertFrom-Json
foreach ($paperosEntry in $paperosRecord.files) {
    $paperosInput = Join-Path $paperosSource $paperosEntry.path
    $paperosTarget = [System.IO.Path]::GetFullPath((Join-Path 'G:\' $paperosEntry.path))
    if (-not $paperosTarget.StartsWith('G:\') -or $paperosEntry.path.Contains('..')) { throw 'Unexpected target path' }
    if ((Get-FileHash -LiteralPath $paperosInput -Algorithm SHA256).Hash.ToLowerInvariant() -ne $paperosEntry.sha256) { throw 'Prepared file changed' }
    if (Test-Path -LiteralPath $paperosTarget) {
        $paperosOldHash = (Get-FileHash -LiteralPath $paperosTarget -Algorithm SHA256).Hash
        $paperosPreserved = Join-Path $paperosBackup $paperosEntry.path
        if (-not (Test-Path -LiteralPath $paperosPreserved) -or (Get-FileHash -LiteralPath $paperosPreserved -Algorithm SHA256).Hash -ne $paperosOldHash) { throw 'Preserve changed original before replacing it' }
    }
    New-Item -ItemType Directory -Path (Split-Path -Parent $paperosTarget) -Force | Out-Null
    Copy-Item -LiteralPath $paperosInput -Destination $paperosTarget
    if ((Get-FileHash -LiteralPath $paperosTarget -Algorithm SHA256).Hash.ToLowerInvariant() -ne $paperosEntry.sha256) { throw 'Device copy verification failed' }
}
$paperosHotfix = 'G:\Update_jailbreak_hotfix_1.16.N_install.bin'
if (Test-Path -LiteralPath $paperosHotfix) {
    if ((Get-FileHash -LiteralPath $paperosHotfix -Algorithm SHA256).Hash -ne '06F79D691B50F3C15142D0159DA0BAFDD0FCD12660A6355C116FC5B3CCA0D11C') { throw 'Unexpected hotfix contents; preserve them first' }
    Remove-Item -LiteralPath $paperosHotfix
}
# Reserve space with a task-owned temporary file while Wi-Fi is used for the entry.
# FAT32 is not sparse: SetLength reserves real allocation; verify free space below.
$paperosGuard = 'G:\paperos-update-guard'
if (Test-Path -LiteralPath $paperosGuard) { throw 'Preserve an existing update-guard directory before continuing' }
New-Item -ItemType Directory -Path $paperosGuard | Out-Null
$paperosReserve = [int64]((Get-Volume -DriveLetter G).SizeRemaining - 80MB)
if ($paperosReserve -gt 0) {
    $paperosFill = [System.IO.File]::Open((Join-Path $paperosGuard 'filler-0.pad'), [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write, [System.IO.FileShare]::None)
    try { $paperosFill.SetLength($paperosReserve); $paperosFill.Flush($true) } finally { $paperosFill.Dispose() }
}
$paperosRemaining = (Get-Volume -DriveLetter G).SizeRemaining
if ($paperosRemaining -lt 50MB -or $paperosRemaining -gt 90MB) { throw 'Unexpected remaining space; inspect before using Wi-Fi' }
$paperosMutation = [ordered]@{ staged_utc=[DateTime]::UtcNow.ToString('o'); backup=$paperosBackup; entry='PaperOS hardware probe'; upstream_release=$paperosRecord.upstream.tag; command='/bin/sh /mnt/us/extensions/PaperOSProbe/bin/probe.sh'; verified_files=$paperosRecord.files.Count; remaining_bytes=$paperosRemaining; temporary_guard=$paperosGuard }
[System.IO.File]::WriteAllText((Join-Path $paperosRoot 'build\device-staging.json'), ($paperosMutation | ConvertTo-Json -Depth 5), [System.Text.UTF8Encoding]::new($false))
$paperosMutation | ConvertTo-Json -Depth 5
