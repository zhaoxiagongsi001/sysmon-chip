@echo off
rem ld wrapper for the CRT-free build; see tools/build.ps1 and tools/ld_wrap.py
python "%~dp0ld_wrap.py" %*
