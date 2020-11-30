FROM python:3.8-alpine

ARG http_proxy
ARG https_proxy
ARG no_proxy

WORKDIR /shared-data
COPY /dcloud-lab.sh /tmp/

RUN mkdir logs && \
    mkdir data && \
    apk add --no-cache git bash && \
    pip install --no-cache-dir git+https://wwwin-github.cisco.com/AIDE/aide-python-agent.git && \
    pip install --no-cache-dir git+https://wwwin-github.cisco.com/AIDE/Sastre-Pro.git

RUN echo "sastre -h" >> /root/.bashrc \
    && echo "[ ! -d rc ] && mkdir rc" >> /root/.bashrc \
    && echo "[ ! -d logs ] && mkdir logs" >> /root/.bashrc \
    && echo "[ ! -d data ] && mkdir data" >> /root/.bashrc \
    && echo "[ ! -f rc/dcloud-lab.sh ] && cp /tmp/dcloud-lab.sh ./rc/" >> /root/.bashrc 

CMD ["/bin/bash"]
