$ErrorActionPreference = 'Stop'
$paperosRoot = Split-Path -Parent $PSScriptRoot
$paperosWorkflow = Get-Content -LiteralPath (Join-Path $paperosRoot 'build\languagebreak-state.json') -Raw | ConvertFrom-Json
if ($paperosWorkflow.root_verified -ne $true) { throw 'Verify the real-device root probe first' }
if ((Get-Volume -DriveLetter G).FileSystemLabel -ne 'Kindle') { throw 'G: is not Kindle' }
$paperosPartition = Get-Partition -DriveLetter G
$paperosDisk = Get-Disk -Number $paperosPartition.DiskNumber
$paperosUsbDisk = Get-CimInstance -ClassName Win32_DiskDrive -Filter ('Index = ' + $paperosPartition.DiskNumber)
$paperosHasher = [Security.Cryptography.SHA256]::Create()
$paperosIdentity = [BitConverter]::ToString($paperosHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($paperosUsbDisk.PNPDeviceID))).Replace('-','').ToLowerInvariant()
$paperosHasher.Dispose()
if ($paperosIdentity -ne $paperosWorkflow.device_usb_identity_sha256) { throw 'USB identity does not match this Kindle' }
$paperosExpectedSize = [long]6385664 * 512
if ($paperosDisk.Size -ne $paperosExpectedSize -or $paperosDisk.LogicalSectorSize -ne 512) { throw 'USB geometry does not match the root probe' }
$paperosBackupRoot = Join-Path $paperosRoot ('backups\full-device-' + (Get-Date).ToUniversalTime().ToString('yyyyMMddTHHmmssfffZ'))
$paperosBackupRoot = [IO.Path]::GetFullPath($paperosBackupRoot)
if (-not $paperosBackupRoot.StartsWith(([IO.Path]::GetFullPath((Join-Path $paperosRoot 'backups')) + '\'), [StringComparison]::OrdinalIgnoreCase)) { throw 'Unexpected backup directory' }
if ((Get-Volume -DriveLetter D).SizeRemaining -lt 8GB) { throw 'Need at least 8 GB available on D:' }
New-Item -ItemType Directory -Path $paperosBackupRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $paperosRoot 'build\device-root-probe.txt') -Destination (Join-Path $paperosBackupRoot 'device-probe.txt')
$paperosState = [ordered]@{
    directory=$paperosBackupRoot
    status='backing_up_usb_user_partition'
    complete=$false
    device_usb_identity_sha256=$paperosIdentity
    emmc_bytes=([long]7634944 * 512)
    p4_offset=([long]1249280 * 512)
    p4_bytes=$paperosExpectedSize
    p4_written_bytes=0
    p4_sha256=$null
    system_regions_received=$false
    boot_partitions_received=$false
    updated_utc=(Get-Date).ToUniversalTime().ToString('o')
}
$paperosStatePath = Join-Path $paperosRoot 'build\full-backup-state.json'
$paperosState | ConvertTo-Json | Set-Content -LiteralPath $paperosStatePath -Encoding utf8
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class PaperOSVolumeControl {
    [DllImport("kernel32.dll", SetLastError=true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool DeviceIoControl(SafeFileHandle handle, uint code,
        IntPtr input, uint inputBytes, IntPtr output, uint outputBytes,
        out uint returnedBytes, IntPtr overlapped);
}
'@
$paperosVolumeHandle = $null
$paperosRawHandle = $null
$paperosOutput = $null
$paperosHash = $null
$paperosLocked = $false
try {
    $paperosVolumeHandle = [IO.File]::Open('\\.\G:', [IO.FileMode]::Open, [IO.FileAccess]::ReadWrite, [IO.FileShare]::ReadWrite)
    [uint32]$paperosReturnedBytes = 0
    $paperosLocked = [PaperOSVolumeControl]::DeviceIoControl($paperosVolumeHandle.SafeFileHandle, 0x00090018, [IntPtr]::Zero, 0, [IntPtr]::Zero, 0, [ref]$paperosReturnedBytes, [IntPtr]::Zero)
    if (-not $paperosLocked) { throw ('Cannot lock Kindle user volume for a consistent backup. Win32 error ' + [Runtime.InteropServices.Marshal]::GetLastWin32Error()) }
    # The physical device is opened read-only. The lock flushes filesystem caches.
    $paperosRawPath = '\\.\PhysicalDrive' + [string]$paperosPartition.DiskNumber
    $paperosRawHandle = [IO.File]::Open($paperosRawPath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::ReadWrite)
    $paperosImagePath = Join-Path $paperosBackupRoot 'mmcblk0p4.img'
    $paperosOutput = [IO.File]::Open($paperosImagePath, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    $paperosHash = [Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
    $paperosBuffer = New-Object byte[] 1048576
    [long]$paperosWritten = 0
    $paperosNextProgress = 0
    while ($paperosWritten -lt $paperosExpectedSize) {
        $paperosReadSize = [int][Math]::Min([long]$paperosBuffer.Length, [long]($paperosExpectedSize - $paperosWritten))
        $paperosCount = $paperosRawHandle.Read($paperosBuffer, 0, $paperosReadSize)
        if ($paperosCount -le 0) { throw 'USB device ended before its reported partition size' }
        $paperosOutput.Write($paperosBuffer, 0, $paperosCount)
        $paperosHash.AppendData($paperosBuffer, 0, $paperosCount)
        $paperosWritten += $paperosCount
        $paperosPercent = [int][Math]::Floor(100.0 * $paperosWritten / $paperosExpectedSize)
        if ($paperosPercent -ge $paperosNextProgress) {
            'USB user partition backup: ' + $paperosPercent + '%'
            $paperosState.p4_written_bytes = $paperosWritten
            $paperosState.updated_utc = (Get-Date).ToUniversalTime().ToString('o')
            $paperosState | ConvertTo-Json | Set-Content -LiteralPath $paperosStatePath -Encoding utf8
            $paperosNextProgress = $paperosPercent + 10
        }
    }
    $paperosOutput.Flush($true)
    $paperosOutput.Dispose()
    $paperosOutput = $null
    $paperosIncomingHash = [BitConverter]::ToString($paperosHash.GetHashAndReset()).Replace('-','').ToLowerInvariant()
    $paperosSavedHash = (Get-FileHash -LiteralPath $paperosImagePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($paperosIncomingHash -ne $paperosSavedHash) { throw 'Saved image did not match bytes read from USB' }
    $paperosState.p4_sha256 = $paperosSavedHash
    $paperosState.p4_written_bytes = $paperosWritten
    $paperosState.status = 'usb_partition_verified_waiting_for_system_regions'
} catch {
    $paperosState.status = 'usb_backup_failed'
    $paperosState.error = $_.Exception.Message
    throw
} finally {
    if ($paperosOutput) { $paperosOutput.Dispose() }
    if ($paperosRawHandle) { $paperosRawHandle.Dispose() }
    if ($paperosHash) { $paperosHash.Dispose() }
    if ($paperosLocked -and $paperosVolumeHandle) {
        [uint32]$paperosReturnedBytes = 0
        $paperosUnlocked = [PaperOSVolumeControl]::DeviceIoControl($paperosVolumeHandle.SafeFileHandle, 0x0009001c, [IntPtr]::Zero, 0, [IntPtr]::Zero, 0, [ref]$paperosReturnedBytes, [IntPtr]::Zero)
    }
    if ($paperosVolumeHandle) { $paperosVolumeHandle.Dispose() }
    $paperosState.updated_utc = (Get-Date).ToUniversalTime().ToString('o')
    $paperosState | ConvertTo-Json | Set-Content -LiteralPath $paperosStatePath -Encoding utf8
    $paperosState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $paperosBackupRoot 'manifest.json') -Encoding utf8
}
[ordered]@{ directory=$paperosBackupRoot; bytes=$paperosState.p4_written_bytes; usb_partition_verified=($paperosState.status -eq 'usb_partition_verified_waiting_for_system_regions'); complete_full_device_backup=$false } | ConvertTo-Json -Compress
