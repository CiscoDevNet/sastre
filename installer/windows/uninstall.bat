@echo off
setlocal enabledelayedexpansion

call "C:\sastre-pro\container_engine.bat"
if %errorlevel% neq 0 (
    exit /b 1
)
set CONTAINER_EXE=%engine%

echo ===============Sastre-Pro application uninstallating process started=============
set "SASTRE_VERSION=latest"
set "SASTRE_IMAGE=localhost/sastre-pro"
set "SLEEP_INTERVAL=5"
set "CURRENT_DIR=%CD%"


set "containers_stopped_count=0"
:: Function to check if containers are stopped
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

echo =============Sastre-Pro application uninstall process finished=============
echo NOTE: Please delete C:\sastre-pro\sastre-volume folder manually (if you choose so)
echo The Sastre-Pro image has been successfully unloaded from the %CONTAINER_EXE% container engine.
exit /b 0