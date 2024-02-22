#!/bin/bash
docker run -it --rm --hostname sastre  --mount type=bind,source="$(pwd)"/sastre-volume,target=/shared-data sastre-pro:latest