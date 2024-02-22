@echo off
setlocal enabledelayedexpansion
echo ===============Sastre-Pro application uninstallating process started=============
set "SASTRE_VERSION=latest"
set "PRODUCT=sastre-pro"
set "SLEEP_INTERVAL=5"
set "CURRENT_DIR=%CD%"


set "containers_stopped_count=0"
:: Function to check if containers are stopped
for /f %%A in ('docker ps -q --filter "ancestor=%PRODUCT%:%SASTRE_VERSION%"') do (
    set /a "containers_stopped_count+=1"
    docker stop %%A
)
timeout /t %SLEEP_INTERVAL% /nobreak

if %containers_stopped_count% neq 0 (
    echo %containers_stopped_count% containers stopped.
)

set "containers_removed_count=0"
:: Function to check if containers are removed
for /f %%A in ('docker ps -aq --filter "ancestor=%PRODUCT%:%SASTRE_VERSION%"') do (
    set /a "containers_removed_count+=1"
    docker rm %%A
)
timeout /t %SLEEP_INTERVAL% /nobreak

if %containers_removed_count% neq 0 (   
    echo %containers_removed_count% containers removed.
)

set "images_removed_count=0"
:: Remove sastre containers and images
for /f %%A in ('docker images %PRODUCT%:%SASTRE_VERSION% ^| findstr "%PRODUCT%"') do (
    set /a "images_removed_count+=1"
    echo Deleting sastre image: %%A
    docker rmi -f %%A
)

if %images_removed_count% neq 0 (
    echo %images_removed_count% images removed.
    echo Successfully deleted sastre-pro docker image %PRODUCT%:%SASTRE_VERSION%
)

echo =============Sastre-Pro application uninstall process finished=============
echo NOTE: Please delete %CURRENT_DIR%\sastre-volume folder manually (if you choose so)

exit /b 0
