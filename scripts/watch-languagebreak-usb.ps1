param(
    [ValidateRange(30,1800)][int]$TimeoutSeconds = 900,
    [switch]$ValidateOnly
)
# One-shot second copy after the approved Resell Device step; never resets or flashes.
$ErrorActionPreference = 'Stop'
$paperosRoot = Split-Path -Parent $PSScriptRoot
$paperosStageScript = Join-Path $PSScriptRoot 'stage-languagebreak.ps1'
$paperosStatePath = Join-Path $paperosRoot 'build\languagebreak-state.json'
$paperosState = Get-Content -LiteralPath $paperosStatePath -Raw | ConvertFrom-Json
if ($paperosState.data_clear_authorized -ne $true) { throw 'Data-clearing flow has not been authorized' }
& $paperosStageScript -Phase payload -PayloadCopy 2 -VerifyOnly
if ($ValidateOnly) {
    'Watcher preflight passed; not armed and no device files written.'
    return
}
if ($paperosState.device_usb_identity_sha256 -notmatch '^[0-9a-f]{64}$') { throw 'Expected USB identity is missing' }
if ($paperosState.payload_copies_completed -ne 1 -or $paperosState.hotfix_staged) { throw 'Arm this watcher only after the first payload copy' }
$paperosDeadline = (Get-Date).AddSeconds($TimeoutSeconds)
$paperosDisconnected = $false
$paperosCopied = $false
'Armed: waiting for USB disconnect, then the same Kindle to reconnect.'
while ((Get-Date) -lt $paperosDeadline) {
    $paperosVolume = Get-Volume -DriveLetter G -ErrorAction SilentlyContinue
    if (-not $paperosVolume) {
        if (-not $paperosDisconnected) { 'USB disconnected; waiting for Kindle reconnect.' }
        $paperosDisconnected = $true
    } elseif ($paperosDisconnected -and $paperosVolume.FileSystemLabel -eq 'Kindle') {
        # Get-Volume may report a drive before its partition association is ready.
        try {
            $paperosPartition = Get-Partition -DriveLetter G
            $paperosDisk = Get-CimInstance -ClassName Win32_DiskDrive -Filter ('Index = ' + $paperosPartition.DiskNumber)
        } catch {
            Start-Sleep -Milliseconds 500
            continue
        }
        $paperosHasher = [Security.Cryptography.SHA256]::Create()
        $paperosIdentity = [BitConverter]::ToString($paperosHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($paperosDisk.PNPDeviceID))).Replace('-','').ToLowerInvariant()
        $paperosHasher.Dispose()
        if ($paperosIdentity -ne $paperosState.device_usb_identity_sha256) { throw 'Reconnect is a different USB device; nothing copied' }
        & $paperosStageScript -Phase payload -PayloadCopy 2
        $paperosCopied = $true
        'Second payload copy complete and verified. Safely eject before holding power.'
        break
    }
    Start-Sleep -Milliseconds 500
}
if (-not $paperosCopied) { throw 'Timed out without copying; reconnect timing needs another attempt' }
