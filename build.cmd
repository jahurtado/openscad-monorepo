@echo off
REM build.cmd — Windows shortcut to build a project's STLs.
REM   build <project> [pieces...]          e.g.  build example
REM   build example base_print lid_print   one STL per named piece
REM   build example --all                  one STL per *_print module
REM   build example --inspect              build + regenerate the main.batch sections
REM   build example --list                 list the project's *_print modules
REM   build --all-projects                 one STL per piece, in every project (CI)
REM Thin wrapper over tools\build.py that uses the repo venv when it exists.
setlocal
set "here=%~dp0"
set "py=%here%.venv\Scripts\python.exe"
if exist "%py%" (
  "%py%" "%here%tools\build.py" %*
) else (
  REM no .venv: uv syncs and runs (needs uv installed; see README.md, Prerequisites)
  uv run --project "%here%" "%here%tools\build.py" %*
)
