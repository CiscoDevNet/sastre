#!/bin/bash
source ./container_engine.sh
if [ -z "${CONTAINER_EXE}" ]; then
    echo "Podman or Docker container engine is not running. Please ensure either Podman or Docker is installed and running"
    exit 1
fi
$CONTAINER_EXE run -it --rm --hostname sastre  --mount type=bind,source="$(pwd)"/sastre-volume,target=/shared-data localhost/sastre-pro:latest