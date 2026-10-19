param([ValidateSet(22, 2222)][int]$Port = 2222)
$ErrorActionPreference = 'Stop'
$paperosUsbipd = 'C:\Program Files\usbipd-win\usbipd.exe'
$paperosReady = $false
function Invoke-PaperOSNative {
    param([string]$Executable, [string[]]$Arguments)
    # Windows PowerShell 5 treats native stderr warnings as ErrorRecords.
    # Inspect the native exit code while keeping expected USB transitions quiet.
    $ErrorActionPreference = 'Continue'
    $paperosOutput = & $Executable @Arguments 2>$null
    [PSCustomObject]@{ ExitCode = $LASTEXITCODE; Output = $paperosOutput }
}
for ($paperosAttempt = 0; $paperosAttempt -lt 25; $paperosAttempt++) {
    $paperosDevices = (Invoke-PaperOSNative $paperosUsbipd @('list')).Output
    $paperosDevice = $paperosDevices | Where-Object { $_ -match '^4-14\s+0525:a4a2\s' }
    if ($paperosDevice -and $paperosDevice -notmatch 'Attached') {
        $null = Invoke-PaperOSNative $paperosUsbipd @('attach', '--wsl', 'Ubuntu-24.04', '--busid', '4-14')
    }
    $paperosLink = Invoke-PaperOSNative wsl @('-d', 'Ubuntu-24.04', '-u', 'root', '--', 'test', '-e', '/sys/class/net/enx025041504501')
    if ($paperosLink.ExitCode -eq 0) {
        $paperosLink = Invoke-PaperOSNative wsl @('-d', 'Ubuntu-24.04', '-u', 'root', '--', 'ip', 'address', 'replace', '169.254.28.1/30', 'dev', 'enx025041504501')
        if ($paperosLink.ExitCode -ne 0) { Start-Sleep -Milliseconds 500; continue }
        $paperosLink = Invoke-PaperOSNative wsl @('-d', 'Ubuntu-24.04', '-u', 'root', '--', 'ip', 'link', 'set', 'enx025041504501', 'up')
        if ($paperosLink.ExitCode -ne 0) { Start-Sleep -Milliseconds 500; continue }
        if ($Port -eq 2222) {
            $paperosProof = Invoke-PaperOSNative wsl @('-d', 'Ubuntu-24.04', '--', 'python3', '/mnt/d/kindle/scripts/device-ssh.py', '--script', '/mnt/d/kindle/device-probe/bin/usb-ssh-proof.sh')
        } else {
            $paperosProof = Invoke-PaperOSNative wsl @('-d', 'Ubuntu-24.04', '--', 'python3', '/mnt/d/kindle/scripts/device-ssh.py', '--port', '22', '--command', 'test -f /etc/paperos-release && readlink /proc/1/exe')
        }
        if ($paperosProof.ExitCode -eq 0) { $paperosProof.Output; $paperosReady = $true; break }
    }
    Start-Sleep -Seconds 2
}
if (-not $paperosReady) { throw 'The expected Kindle USB service did not become ready' }
