# Restore only files staged by our failed store entry; never clear Kindle content.
$ErrorActionPreference = 'Stop'
$paperosRoot = Split-Path -Parent $PSScriptRoot
$paperosVolume = Get-Volume -DriveLetter G
if ($paperosVolume.FileSystemLabel -ne 'Kindle') { throw 'G: is not Kindle' }
$paperosStaging = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\device-staging.json') -Raw | ConvertFrom-Json
$paperosSource = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\probe-entry-source.json') -Raw | ConvertFrom-Json
$paperosBackup = (Resolve-Path -LiteralPath $paperosStaging.backup).Path
if (-not $paperosBackup.StartsWith((Join-Path $paperosRoot 'backups') + '\')) { throw 'Unexpected backup path' }
foreach ($paperosEntry in $paperosSource.files) {
    $paperosTarget = [System.IO.Path]::GetFullPath((Join-Path 'G:\' $paperosEntry.path))
    if (-not $paperosTarget.StartsWith('G:\') -or $paperosEntry.path.Contains('..')) { throw 'Unexpected device path' }
    if (-not (Test-Path -LiteralPath $paperosTarget)) { continue }
    if ((Get-FileHash -LiteralPath $paperosTarget -Algorithm SHA256).Hash.ToLowerInvariant() -ne $paperosEntry.sha256) {
        throw "A staged file changed on-device; preserve it before rollback: $($paperosEntry.path)"
    }
    $paperosOriginal = Join-Path $paperosBackup $paperosEntry.path
    if (Test-Path -LiteralPath $paperosOriginal) {
        Copy-Item -LiteralPath $paperosOriginal -Destination $paperosTarget
    } else {
        Remove-Item -LiteralPath $paperosTarget
    }
}
$paperosGuard = 'G:\paperos-update-guard'
if (Test-Path -LiteralPath $paperosGuard) {
    $paperosResolvedGuard = (Resolve-Path -LiteralPath $paperosGuard).Path
    if ($paperosResolvedGuard -ne 'G:\paperos-update-guard' -or $paperosStaging.temporary_guard -ne $paperosResolvedGuard) { throw 'Wrong guard path' }
    $paperosGuardFiles = @(Get-ChildItem -LiteralPath $paperosResolvedGuard -Force)
    if ($paperosGuardFiles.Count -ne 1 -or $paperosGuardFiles[0].Name -ne 'filler-0.pad' -or $paperosGuardFiles[0].PSIsContainer) { throw 'Unexpected guard contents' }
    Remove-Item -LiteralPath $paperosGuardFiles[0].FullName
    Remove-Item -LiteralPath $paperosResolvedGuard
}
[ordered]@{ restored_utc=[DateTime]::UtcNow.ToString('o'); root_firmware_changed=$false; remaining_bytes=(Get-Volume -DriveLetter G).SizeRemaining } | ConvertTo-Json -Compress
