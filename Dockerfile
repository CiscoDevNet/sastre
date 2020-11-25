ARG http_proxy
ARG https_proxy
ARG no_proxy

FROM python:3.9-alpine

ENV SASTRE_ROOT_DIR="/shared-data"

WORKDIR /sastre-init
COPY /dcloud-lab.sh ./rc/
COPY /container-init.sh /etc/profile.d/sastre_init.sh

RUN apk update && apk upgrade && apk add --no-cache git && \
    pip install --no-cache-dir --upgrade pip setuptools && \
    pip install --no-cache-dir cisco-sdwan

VOLUME /shared-data

WORKDIR /shared-data

CMD ["/bin/ash", "-l"]

