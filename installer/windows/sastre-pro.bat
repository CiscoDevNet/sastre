@echo off
call container_engine.bat
if %errorlevel% neq 0 (
    exit /b 1
)
set CONTAINER_EXE=%engine%
%CONTAINER_EXE% run -it --rm --hostname sastre  --mount type=bind,source="%cd%"/sastre-volume,target=/shared-data localhost/sastre-pro:latest