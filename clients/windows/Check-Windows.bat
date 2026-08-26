@echo off
setlocal EnableExtensions
title Windows IKEv2 health check
set "OUT=%USERPROFILE%\Desktop\windows-health.txt"
echo Writing report to:
echo %OUT%
echo.

> "%OUT%" echo ===== Windows IKEv2 health =====
>>"%OUT%" echo Date: %DATE% %TIME%
>>"%OUT%" echo User: %USERNAME%
>>"%OUT%" echo.

>>"%OUT%" echo ===== OS =====
systeminfo | findstr /B /C:"OS Name" /C:"OS Version" /C:"OS Manufacturer" /C:"System Type" /C:"Original Install Date" /C:"System Manufacturer" /C:"System Model" /C:"Windows Directory" >>"%OUT%"
>>"%OUT%" echo.

>>"%OUT%" echo ===== winver =====
ver >>"%OUT%"
>>"%OUT%" echo.

>>"%OUT%" echo ===== VPN / RAS services =====
sc.exe query RasMan >>"%OUT%" 2>&1
>>"%OUT%" echo.
sc.exe qc RasMan >>"%OUT%" 2>&1
>>"%OUT%" echo.
sc.exe query SstpSvc >>"%OUT%" 2>&1
>>"%OUT%" echo.
sc.exe query IKEEXT >>"%OUT%" 2>&1
>>"%OUT%" echo.
sc.exe query PolicyAgent >>"%OUT%" 2>&1
>>"%OUT%" echo.
sc.exe query Dnscache >>"%OUT%" 2>&1
>>"%OUT%" echo.

>>"%OUT%" echo ===== files =====
if exist C:\Windows\System32\rasmans.dll (echo rasmans.dll OK >>"%OUT%") else (echo rasmans.dll MISSING >>"%OUT%")
if exist C:\Windows\INF\netavp.inf (echo netavp.inf OK >>"%OUT%") else (echo netavp.inf MISSING >>"%OUT%")
if exist C:\Windows\INF\netrasa.inf (echo netrasa.inf OK >>"%OUT%") else (echo netrasa.inf MISSING >>"%OUT%")
dir /b "C:\ProgramData\Microsoft\Network\Connections\Pbk" >>"%OUT%" 2>&1
>>"%OUT%" echo.

>>"%OUT%" echo ===== netcfg agilevpn =====
netcfg.exe -v -s n 2>&1 | findstr /i "agilevpn sstpp pptp l2tp wanarp RasMan ras" >>"%OUT%"
>>"%OUT%" echo.

>>"%OUT%" echo ===== DISM checkhealth =====
dism /online /cleanup-image /checkhealth >>"%OUT%" 2>&1
>>"%OUT%" echo.

>>"%OUT%" echo ===== Event RasMan (last) =====
wevtutil qe System /c:60 /rd:true /f:text 2>nul | findstr /i "RasMan rasmans agilevpn 7024 7000 7034" >>"%OUT%"
>>"%OUT%" echo.

>>"%OUT%" echo ===== DONE =====
echo.
echo Report saved:
echo %OUT%
notepad "%OUT%"
pause
