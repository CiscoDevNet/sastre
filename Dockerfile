ARG http_proxy
ARG https_proxy
ARG no_proxy

FROM python:3.8-alpine

WORKDIR /sastre
COPY /dcloud-lab.sh ./rc/

RUN mkdir logs && \
    mkdir data && \
    pip install --no-cache-dir cisco-sdwan

VOLUME /sastre/rc /sastre/logs /sastre/data

CMD ["/bin/ash"]

