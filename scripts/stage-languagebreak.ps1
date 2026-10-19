param(
    [ValidateSet('payload','hotfix')][string]$Phase = 'payload',
    [ValidateSet(1,2)][int]$PayloadCopy = 1,
    [switch]$VerifyOnly
)
# Run only after the user explicitly approves the data-clearing LanguageBreak flow.
$ErrorActionPreference = 'Stop'
$paperosRoot = Split-Path -Parent $PSScriptRoot
$paperosRelease = Get-Content -LiteralPath (Join-Path $paperosRoot 'downloads\languagebreak\release.json') -Raw | ConvertFrom-Json
$paperosSource = Join-Path $paperosRoot 'downloads\languagebreak\payload'
if ($paperosRelease.tag -ne '1.0.2.1') { throw 'Review this release before staging' }
# The reviewed tarball stores member names with a leading './'.
$paperosManifestFiles = @($paperosRelease.files | ForEach-Object {
    $paperosPath = [string]$_.path
    if ($paperosPath.StartsWith('./')) { $paperosPath = $paperosPath.Substring(2) }
    [pscustomobject]@{ path=$paperosPath; sha256=$_.sha256; bytes=$_.bytes }
})
$paperosFiles = if ($Phase -eq 'payload') {
    @($paperosManifestFiles | Where-Object { $_.path.StartsWith('LanguageBreak/') })
} else {
    @($paperosManifestFiles | Where-Object { $_.path -eq 'Update_hotfix_languagebreak-zh-Hans-CN.bin' })
}
$paperosExpectedCount = if ($Phase -eq 'payload') { 6 } else { 1 }
if ($paperosFiles.Count -ne $paperosExpectedCount) { throw 'Expected reviewed files are missing' }
if (-not $VerifyOnly) {
    $paperosStatePath = Join-Path $paperosRoot 'build\languagebreak-state.json'
    $paperosState = Get-Content -LiteralPath $paperosStatePath -Raw | ConvertFrom-Json
    if ($paperosState.data_clear_authorized -ne $true) { throw 'Data-clearing flow has not been authorized' }
    if ($paperosState.release -ne $paperosRelease.tag) { throw 'Workflow release changed' }
    if ($Phase -eq 'payload' -and $PayloadCopy -eq 2 -and $paperosState.payload_copies_completed -lt 1) { throw 'First payload copy must be completed before the second' }
    if ($Phase -eq 'hotfix' -and $paperosState.payload_copies_completed -lt 2) { throw 'Complete both payload copies before staging hotfix' }
    if ((Get-Volume -DriveLetter G).FileSystemLabel -ne 'Kindle') { throw 'G: is not Kindle' }
    $paperosPartition = Get-Partition -DriveLetter G
    $paperosDisk = Get-CimInstance -ClassName Win32_DiskDrive -Filter ('Index = ' + $paperosPartition.DiskNumber)
    if ($paperosDisk.Model -notmatch 'Kindle' -or $paperosDisk.PNPDeviceID -notmatch '^USBSTOR') { throw 'Connected drive is not a Kindle USB disk' }
    $paperosHasher = [Security.Cryptography.SHA256]::Create()
    $paperosIdentity = [BitConverter]::ToString($paperosHasher.ComputeHash([Text.Encoding]::UTF8.GetBytes($paperosDisk.PNPDeviceID))).Replace('-','').ToLowerInvariant()
    $paperosHasher.Dispose()
    if (-not $paperosState.device_usb_identity_sha256 -and $Phase -eq 'payload' -and $PayloadCopy -eq 1) {
        $paperosVersion = (Get-Content -LiteralPath 'G:\system\version.txt' -Raw).Trim()
        if ($paperosVersion -ne 'Kindle 5.16.2.1.1 (409749 002)') { throw 'Expected firmware changed before initial staging' }
        $paperosState | Add-Member -NotePropertyName device_usb_identity_sha256 -NotePropertyValue $paperosIdentity
    }
    if ($paperosIdentity -ne $paperosState.device_usb_identity_sha256) { throw 'Connected USB device does not match this Kindle' }
}
$paperosCopyPlan = @()
foreach ($paperosFile in $paperosFiles) {
    $paperosRelative = if ($Phase -eq 'payload') { $paperosFile.path.Substring('LanguageBreak/'.Length) } else { $paperosFile.path }
    $paperosInput = Join-Path $paperosSource $paperosFile.path
    $paperosTarget = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine('G:\', $paperosRelative))
    if (-not $paperosTarget.StartsWith('G:\') -or $paperosRelative.Contains('..')) { throw 'Unexpected copy target' }
    if ((Get-FileHash -LiteralPath $paperosInput -Algorithm SHA256).Hash.ToLowerInvariant() -ne $paperosFile.sha256) { throw 'Reviewed source changed' }
    if ((Get-Item -LiteralPath $paperosInput).Length -ne $paperosFile.bytes) { throw 'Reviewed source size changed' }
    $paperosCopyPlan += [pscustomobject]@{ input=$paperosInput; target=$paperosTarget; sha256=$paperosFile.sha256 }
}
if (-not $VerifyOnly) {
    foreach ($paperosCopy in $paperosCopyPlan) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $paperosCopy.target) -Force | Out-Null
        # LiteralPath is essential: the dictionary name is shell text, never a command.
        Copy-Item -LiteralPath $paperosCopy.input -Destination $paperosCopy.target
        if ((Get-FileHash -LiteralPath $paperosCopy.target -Algorithm SHA256).Hash.ToLowerInvariant() -ne $paperosCopy.sha256) { throw 'Device copy did not match reviewed source' }
    }
    if ($Phase -eq 'payload') {
        $paperosState.payload_copies_completed = [Math]::Max([int]$paperosState.payload_copies_completed, $PayloadCopy)
        $paperosState.next_step = if ($PayloadCopy -eq 1) { 'resell_then_automatic_second_copy' } else { 'eject_then_select_simplified_chinese' }
    } else {
        $paperosState.hotfix_staged = $true
        $paperosState.next_step = 'install_languagebreak_hotfix'
    }
    $paperosState.updated_utc = (Get-Date).ToUniversalTime().ToString('o')
    $paperosState | ConvertTo-Json | Set-Content -LiteralPath $paperosStatePath -Encoding utf8
}
[ordered]@{ phase=$Phase; verified_files=$paperosFiles.Count; release=$paperosRelease.tag; device_written=(-not $VerifyOnly) } | ConvertTo-Json -Compress
