@echo off
setlocal EnableDelayedExpansion
REM ============================================================================
REM  release.bat -- publish dist\ConstructionPaper.exe to GitHub Releases
REM
REM    tools\release.bat 1.0.0
REM    tools\release.bat 1.0.0 "Build 4 -- scatter sheet rewrite"
REM
REM  Needs the GitHub CLI (winget install GitHub.cli) and one-time:
REM    gh auth login
REM
REM  The download page reads version, date, size and the SHA-256 straight out
REM  of the release, so nothing on the website has to be edited afterwards.
REM  The hash is parsed out of the notes -- keep the "SHA-256: <hash>" line.
REM ============================================================================

set "REPO=antigomer/cxpaper-releases"
set "EXE=%~dp0..\..\dist\ConstructionPaper.exe"

if "%~1"=="" (
  echo Usage: tools\release.bat ^<version^> ["release title"]
  echo   e.g. tools\release.bat 1.0.0 "Build 4"
  exit /b 1
)
set "VER=%~1"
set "TITLE=%~2"
if "%TITLE%"=="" set "TITLE=Construction Paper %VER%"

if not exist "%EXE%" (
  echo ERROR: not found: %EXE%
  echo Edit EXE= at the top of this file if the build lives somewhere else.
  exit /b 1
)

where gh >nul 2>&1
if errorlevel 1 (
  echo ERROR: the GitHub CLI is not on PATH.
  echo   winget install GitHub.cli
  echo   gh auth login
  exit /b 1
)

echo.
echo   file    %EXE%
for %%F in ("%EXE%") do echo   size    %%~zF bytes
echo   repo    %REPO%
echo   tag     v%VER%
echo.

REM --- SHA-256 --------------------------------------------------------------
set "HASH="
for /f "usebackq delims=" %%H in (`powershell -NoProfile -Command ^
  "(Get-FileHash -LiteralPath '%EXE%' -Algorithm SHA256).Hash.ToLower()"`) do set "HASH=%%H"

if "!HASH!"=="" (
  echo ERROR: could not compute SHA-256.
  exit /b 1
)
echo   sha256  !HASH!
echo.

REM --- notes ----------------------------------------------------------------
set "NOTES=%TEMP%\cp_release_notes_%VER%.md"
>  "!NOTES!" echo Construction Paper %VER%
>> "!NOTES!" echo.
>> "!NOTES!" echo SHA-256: !HASH!
>> "!NOTES!" echo.
>> "!NOTES!" echo Verify before running:
>> "!NOTES!" echo.
>> "!NOTES!" echo     Get-FileHash .\ConstructionPaper.exe -Algorithm SHA256
>> "!NOTES!" echo.
>> "!NOTES!" echo A licence key is required. cxpaper.com/license/

echo Publishing...
gh release create "v%VER%" "%EXE%" --repo "%REPO%" --title "%TITLE%" --notes-file "!NOTES!"
if errorlevel 1 (
  echo.
  echo Release FAILED. If the tag already exists, either bump the version or:
  echo   gh release delete v%VER% --repo %REPO% --yes
  del "!NOTES!" >nul 2>&1
  exit /b 1
)

del "!NOTES!" >nul 2>&1
echo.
echo Done. cxpaper.com/download/ will show v%VER% on its next load.
echo.
endlocal
