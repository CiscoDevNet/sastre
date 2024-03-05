#!/bin/bash
CONTAINER_ENGINE_PATHS=("/usr/bin/podman" "/usr/local/bin/podman" "/opt/homebrew/bin/podman" "/opt/podman/bin/podman" "/usr/bin/docker" "/usr/local/bin/docker" "/opt/homebrew/bin/docker" "/opt/docker/bin/docker")

for path in "${CONTAINER_ENGINE_PATHS[@]}"; do
    if [ -x "$path" ]; then
        if "$path" images &>/dev/null; then
            echo "Container engine $path is running"
            CONTAINER_EXE="$path"
            break
        fi
    fi
done