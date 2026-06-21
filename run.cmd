@echo off
REM Convenience wrapper (Windows). After `pip install .` you can also just run `lucidadl`.
REM Examples:
REM   run.cmd setup
REM   run.cmd album "Red Hot Chili Peppers - Californication" --to mp3 --bitrate 320k -j 8
REM   run.cmd tracks
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" -m lucidadl %*
) else (
  python -m lucidadl %*
)
