@echo off
rem Autonomous Quant Trader - menu de arranque (doble clic). Solo PAPER.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Autonomous Quant Trader

set "UV="
where uv >nul 2>nul && set "UV=uv"
if not defined UV if exist "%APPDATA%\Python\Python314\Scripts\uv.exe" set "UV=%APPDATA%\Python\Python314\Scripts\uv.exe"
if not defined UV if exist "%USERPROFILE%\.local\bin\uv.exe" set "UV=%USERPROFILE%\.local\bin\uv.exe"
if not defined UV if exist "%USERPROFILE%\.cargo\bin\uv.exe" set "UV=%USERPROFILE%\.cargo\bin\uv.exe"
if not defined UV (
  echo No encuentro uv. Instalalo con:  pip install uv   ^(o mira el README^) y vuelve a abrir AQT.cmd
  pause
  exit /b 1
)

"%UV%" run python -m services.launcher
if errorlevel 1 pause
