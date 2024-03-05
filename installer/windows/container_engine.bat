@echo off

set "CONTAINER_ENGINES=podman docker"

for %%P in (%CONTAINER_ENGINES%) do (
    where %%P >nul 2>&1 && (
        set "CONTAINER_EXE=%%P"
        %%P images >nul 2>&1 && (
            echo Container engine %%P is running
            set "engine_found=true"
            set "engine=%%P"
            exit /b 0
        )
    ) 
)

if not defined engine_found (
    echo Podman or Docker container engine is not running. Please ensure either Podman or Docker is installed and running
    exit /b 1
)