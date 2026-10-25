<#
.SYNOPSIS
    Bridges a USB-connected Android phone to the fleet manager running in a VM.

.DESCRIPTION
    For networks where Wi-Fi client isolation blocks phone-to-server traffic.
    The phone stays on USB; this script switches its adbd to TCP mode and forwards
    127.0.0.1:<Port> on this Windows host to the phone over the cable. A VirtualBox
    NAT guest reaches the host loopback as 10.0.2.2, so register the phone in the
    dashboard as host 10.0.2.2, port <Port>, connection type adb_tcp.

    The script keeps watching and re-applies both steps after the phone reboots or
    is re-plugged. ADB RSA authorization is unchanged: the manager's own key must
    still be accepted on the phone once. Press Ctrl+C to stop; the forward is removed.

.EXAMPLE
    .\scripts\usb-bridge.ps1
    .\scripts\usb-bridge.ps1 -Serial R83W70BG5GT -Port 5555
#>
param(
    [string]$Serial = "",
    [ValidateRange(1024, 65535)][int]$Port = 5555,
    [string]$Adb = ""
)

$ErrorActionPreference = "Stop"

function Find-Adb {
    if ($Adb) { return $Adb }
    $command = Get-Command adb -ErrorAction SilentlyContinue
    if ($command) { return $command.Source }
    foreach ($candidate in @(
            "$env:USERPROFILE\tools\platform-tools\adb.exe",
            "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe")) {
        if (Test-Path $candidate) { return $candidate }
    }
    throw "adb not found. Install Android platform-tools or pass -Adb <path to adb.exe>."
}

function Get-UsbSerials {
    # USB transports are listed by hardware serial; TCP ones look like host:port.
    & $script:AdbPath devices | Select-Object -Skip 1 |
        Where-Object { $_ -match "^(\S+)\s+device\b" -and $Matches[1] -notmatch ":" } |
        ForEach-Object { ($_ -split "\s+")[0] }
}

function Test-Forward([string]$Device) {
    $forwards = & $script:AdbPath forward --list
    return [bool]($forwards | Where-Object { $_ -eq "$Device tcp:$Port tcp:$Port" })
}

$script:AdbPath = Find-Adb
Write-Host "Using $script:AdbPath"
Write-Host "Register the phone in the dashboard as 10.0.2.2:$Port (adb_tcp). Ctrl+C to stop."
$bridged = ""
try {
    while ($true) {
        $serials = @(Get-UsbSerials)
        $device = if ($Serial) { $serials | Where-Object { $_ -eq $Serial } } else { $serials | Select-Object -First 1 }
        if (-not $device) {
            if ($bridged) { Write-Host "$(Get-Date -Format T)  Phone disconnected; waiting for USB..." }
            $bridged = ""
        }
        else {
            $tcpPort = (& $script:AdbPath -s $device shell getprop service.adb.tcp.port).Trim()
            if ($tcpPort -ne "$Port") {
                Write-Host "$(Get-Date -Format T)  Switching $device adbd to TCP port $Port"
                & $script:AdbPath -s $device tcpip $Port | Out-Null
                Start-Sleep -Seconds 3
                continue
            }
            if (-not (Test-Forward $device)) {
                & $script:AdbPath -s $device forward "tcp:$Port" "tcp:$Port" | Out-Null
                Write-Host "$(Get-Date -Format T)  Bridged $device -> 127.0.0.1:$Port (VM: 10.0.2.2:$Port)"
            }
            $bridged = $device
        }
        Start-Sleep -Seconds 5
    }
}
finally {
    if ($bridged) {
        & $script:AdbPath forward --remove "tcp:$Port" 2>$null | Out-Null
        Write-Host "Forward removed."
    }
}
