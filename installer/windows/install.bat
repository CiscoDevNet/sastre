@echo off
setlocal enabledelayedexpansion

call container_engine.bat
if %errorlevel% neq 0 (
    exit /b 1
)
set CONTAINER_EXE=%engine%

echo ===============Sastre-Pro installation process started=============
set "SASTRE_VERSION=latest"
set "SASTRE_IMAGE=localhost/sastre-pro"
set "SASTRE_TAR=sastre-pro.tar"
set "SLEEP_INTERVAL=5"
set "SASTRE_VOLUME=sastre-volume"
set "CURRENT_DIR=%CD%"
set "SASTRE_VOLUME_PATH=%CURRENT_DIR%\%SASTRE_VOLUME%"


set "containers_stopped_count=0"
for /f %%A in ('%CONTAINER_EXE% ps -q --filter "ancestor=%SASTRE_IMAGE%:%SASTRE_VERSION%"') do (
    set /a "containers_stopped_count+=1"
    %CONTAINER_EXE% stop %%A
)
timeout /t %SLEEP_INTERVAL% /nobreak

if %containers_stopped_count% neq 0 (
    echo %containers_stopped_count% containers stopped.
)

set "containers_removed_count=0"
:: Function to check if containers are removed
for /f %%A in ('%CONTAINER_EXE% ps -aq --filter "ancestor=%SASTRE_IMAGE%:%SASTRE_VERSION%"') do (
    set /a "containers_removed_count+=1"
    %CONTAINER_EXE% rm %%A
)
timeout /t %SLEEP_INTERVAL% /nobreak

if %containers_removed_count% neq 0 (   
    echo %containers_removed_count% containers removed.
)

set "images_removed_count=0"
:: Remove sastre containers and images
for /f %%A in ('%CONTAINER_EXE% images %SASTRE_IMAGE%:%SASTRE_VERSION% ^| findstr "%SASTRE_IMAGE%"') do (
    set /a "images_removed_count+=1"
    echo Deleting sastre image: %%A
    %CONTAINER_EXE% rmi -f %%A
)

if %images_removed_count% neq 0 (   
    echo %images_removed_count% images removed.
    echo Successfully deleted sastre-pro image %SASTRE_IMAGE%:%SASTRE_VERSION%
)

%CONTAINER_EXE% load -i %SASTRE_TAR%

:: Check if the sastre-pro image was loaded successfully
if %ERRORLEVEL% equ 0 (
    echo Latest sastre-pro image loaded successfully
) else (
    echo Failed to load latest sastre-pro image with exit code: %ERRORLEVEL%
)

if not exist "%SASTRE_VOLUME_PATH%" (
    mkdir "%SASTRE_VOLUME_PATH%"
    icacls "%SASTRE_VOLUME_PATH%" /grant:r "Everyone:(OI)(CI)W" /t
    echo Sastre volume path created: %SASTRE_VOLUME_PATH%
) else (
    echo Sastre volume path already exists: %SASTRE_VOLUME_PATH%
)

echo ===============Sastre-Pro installation process finished==============
echo The Sastre-Pro image has been successfully loaded into the %CONTAINER_EXE% container engine.
exit /b 0