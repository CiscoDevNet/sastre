@echo off
setlocal enabledelayedexpansion

echo ===============Sastre-Pro installation process started=============
set "SASTRE_VERSION=latest"
set "PRODUCT=sastre-pro"
set "SLEEP_INTERVAL=5"
set "sastreVolume=sastre-volume"
set "currentDir=%CD%"
set "volumePath=%currentDir%\%sastreVolume%"

set list_existing_sastre_images=

for /f "delims=" %%A in ('docker images --filter "reference=%PRODUCT%:%SASTRE_VERSION%" --format "{{.Repository}}"') do (
    set "list_existing_sastre_images=%%A"
)

set "containers_stopped_count=0"
for /f %%A in ('docker ps -q --filter "ancestor=%PRODUCT%:%SASTRE_VERSION%"') do (
    set /a "containers_stopped_count+=1"
    docker stop %%A
)
timeout /t %SLEEP_INTERVAL% /nobreak

if %containers_stopped_count% neq 0 (
    echo %containers_stopped_count% containers stopped.
)

set "containers_removed_count=0"
:: Function to check if sastre-pro containers are removed
for /f %%A in ('docker ps -aq --filter "ancestor=%PRODUCT%:%SASTRE_VERSION%"') do (
    set /a "containers_removed_count+=1"
    docker rm %%A
)
timeout /t %SLEEP_INTERVAL% /nobreak

if %containers_removed_count% neq 0 (   
    echo %containers_removed_count% containers removed.
)

set "images_removed_count=0"
:: Remove sastre-pro containers and images
for /f %%A in ('docker images %PRODUCT%:%SASTRE_VERSION% ^| findstr "%PRODUCT%"') do (
    set /a "images_removed_count+=1"
    echo Deleting sastre-pro image: %%A
    docker rmi -f %%A
)

if %images_removed_count% neq 0 (   
    echo %images_removed_count% images removed.
    echo Successfully deleted sastre-pro docker image %PRODUCT%:%SASTRE_VERSION%
)

docker load -i %PRODUCT%.tar

:: Check if the sastre-pro image was loaded successfully
if %ERRORLEVEL% equ 0 (
    echo Latest sastre-pro docker image loaded successfully
) else (
    echo Failed to load latest sastre-pro docker image with exit code: %ERRORLEVEL%
)

if not exist "%volumePath%" (
    mkdir "%volumePath%"
    icacls "%volumePath%" /grant:r "Everyone:(OI)(CI)W" /t
    echo Sastre-Pro volume path created: %volumePath%
) else (
    echo Sastre-Pro volume path already exists: %volumePath%
)

echo ===============Sastre-Pro installation process finished==============
exit /b 0