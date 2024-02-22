@echo off
docker run -it --rm --hostname sastre  --mount type=bind,source="%cd%"/sastre-volume,target=/shared-data sastre-pro:latest