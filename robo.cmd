@echo off
setlocal
rem Source-tree launcher. Prefer the checkout's own virtualenv (install-robo.ps1
rem creates .venv); a plain system Python usually lacks Robo's packages.
rem The quotes are part of the value so special characters in the path stay quoted.
set "ROBO_PY=py -3"
if exist "%~dp0venv\Scripts\python.exe" set ROBO_PY="%~dp0venv\Scripts\python.exe"
if exist "%~dp0.venv\Scripts\python.exe" set ROBO_PY="%~dp0.venv\Scripts\python.exe"
%ROBO_PY% "%~dp0robo.py" %*
