FROM python:3.9-alpine

ARG http_proxy
ARG https_proxy
ARG no_proxy

ENV SASTRE_ROOT_DIR="/shared-data"

WORKDIR /sastre-init
COPY /examples/dcloud-lab.sh ./rc/

RUN apk update && apk upgrade && apk add --no-cache git bash && \
    pip install --no-cache-dir --upgrade pip setuptools && \
    pip install --no-cache-dir cisco-sdwan && \
    echo "export PS1='\h:\w\$ '" >> /root/.bashrc && \
    echo "[ \${SASTRE_ROOT_DIR} ] && [ ! -d \${SASTRE_ROOT_DIR}/rc ] && cp -R /sastre-init/rc \${SASTRE_ROOT_DIR}" >> /root/.bashrc && \
    echo "sdwan -h" >> /root/.bashrc

VOLUME /shared-data

WORKDIR /shared-data

CMD ["/bin/bash"]
