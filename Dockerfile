ARG http_proxy
ARG https_proxy
ARG no_proxy

FROM python:3.8-alpine

WORKDIR /sastre
COPY /dcloud-lab.sh ./rc/

RUN mkdir logs && \
    mkdir data && \
    apk add --no-cache git && \
    pip install --no-cache-dir git+https://wwwin-github.cisco.com/AIDE/aide-python-agent.git && \
    pip install --no-cache-dir git+https://wwwin-github.cisco.com/AIDE/Sastre-Pro.git

VOLUME /sastre/rc /sastre/logs /sastre/data

CMD ["/bin/ash"]

