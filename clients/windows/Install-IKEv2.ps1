#Requires -Version 5.1
# IKEv2 one-click setup (Windows 10/11)
# __DOMAIN__ is replaced at install / panel download.
$ErrorActionPreference = 'Stop'
$Server = '__DOMAIN__'
$Name   = 'IKEv2'

function Test-Admin {
    $p = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    return $p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

if (-not (Test-Admin)) {
    $arg = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -ArgumentList $arg
    exit
}

Write-Host ''
Write-Host ' IKEv2 setup' -ForegroundColor Cyan
Write-Host " Server: $Server"
Write-Host ''

New-Item -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\PolicyAgent' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\PolicyAgent' -Name 'AssumeUDPEncapsulationContextOnSendRule' -Type DWord -Value 2
New-Item -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\RasMan\Parameters' -Force | Out-Null
Set-ItemProperty -Path 'HKLM:\SYSTEM\CurrentControlSet\Services\RasMan\Parameters' -Name 'DisableIKECertificateRevocationCheck' -Type DWord -Value 1

try { Set-Service RasMan -StartupType Automatic -ErrorAction SilentlyContinue } catch {}
try { Set-Service IKEEXT -StartupType Automatic -ErrorAction SilentlyContinue } catch {}
try { Start-Service IKEEXT -ErrorAction SilentlyContinue } catch {}
try { Start-Service RasMan -ErrorAction SilentlyContinue } catch {}

Get-VpnConnection -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $Name } | ForEach-Object {
    try { Remove-VpnConnection -Name $Name -Force -ErrorAction Stop } catch {}
}
Get-VpnConnection -AllUserConnection -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $Name } | ForEach-Object {
    try { Remove-VpnConnection -Name $Name -AllUserConnection -Force -ErrorAction Stop } catch {}
}

Add-VpnConnection -Name $Name -ServerAddress $Server -TunnelType IKEv2 `
    -AuthenticationMethod Eap -EncryptionLevel Required -RememberCredential -Force

Write-Host " Profile '$Name' created." -ForegroundColor Green
Write-Host ''
Write-Host ' Connect: Settings > Network > VPN > IKEv2 > Connect'
Write-Host ' Use the VPN username/password from the panel.'
Write-Host ''
try { Start-Process 'rasphone.exe' -ArgumentList "-d `"$Name`"" } catch {}
Read-Host 'Press Enter to close'
