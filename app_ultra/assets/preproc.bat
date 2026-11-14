@echo off
rem windres needs a C preprocessor; this machine only has MinGW binutils
rem (no gcc/cc1). app.rc has no #include / #define, so pass the file through.
rem NOTE: cmd's "type" rejects forward-slash paths, hence the normalization.
setlocal enabledelayedexpansion
set "IN="
for %%A in (%*) do (
  set "ARG=%%A"
  if not "!ARG:~0,1!"=="-" set "IN=%%A"
)
if defined IN (
  set "IN=!IN:/=\!"
  type "!IN!"
)
