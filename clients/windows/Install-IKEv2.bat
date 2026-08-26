@echo off
title IKEv2 setup
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-IKEv2.ps1"
if errorlevel 1 pause
