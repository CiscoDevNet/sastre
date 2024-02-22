@echo off

set "app_name=%1"
set "version=%2"

set "TARGET_FOLDER=%cd%\target"

if not exist "%TARGET_FOLDER%" (
    mkdir "%TARGET_FOLDER%"
)

rem Copy files to the target folder
copy /Y "sastre-pro.nsi" "%TARGET_FOLDER%"
copy /Y "LICENSE.txt" "%TARGET_FOLDER%"
copy /Y "sastre-pro.ico" "%TARGET_FOLDER%"
copy /Y "sastre-pro.bat" "%TARGET_FOLDER%"
copy /Y "install.bat" "%TARGET_FOLDER%"
copy /Y "uninstall.bat" "%TARGET_FOLDER%"

for %%f in ("%TARGET_FOLDER%\*.bat") do (
    (
        for /f "usebackq delims=" %%l in ("%%~f") do (
            set "line=%%l"
            setlocal enabledelayedexpansion
            set "line=!line:%%APP_NAME%%=%app_name%!"
            set "line=!line:%%VERSION%%=%version%!"
            echo(!line!
            endlocal
        )
    ) > "%%~f.tmp" && move /Y "%%~f.tmp" "%%~f"
)

for %%f in ("%TARGET_FOLDER%\*.nsi") do (
    (
        for /f "usebackq delims=" %%l in ("%%~f") do (
            set "line=%%l"
            setlocal enabledelayedexpansion
            set "line=!line:%%APP_NAME%%=%app_name%!"
            set "line=!line:%%VERSION%%=%version%!"
            echo(!line!
            endlocal
        )
    ) > "%%~f.tmp" && move /Y "%%~f.tmp" "%%~f"
)

echo Successfully copied files and placeholders are replaced!
