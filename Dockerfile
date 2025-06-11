FROM python:3.12-alpine

ARG http_proxy
ARG https_proxy
ARG no_proxy

ENV SASTRE_ROOT_DIR="/shared-data"

WORKDIR /sastre-init
COPY /examples/sastre-env.sh ./rc/

# Add non-root user and group
RUN addgroup -S sastre && adduser -S sastre -G sastre

RUN apk update && apk upgrade && apk add --no-cache git bash && \
    pip install --no-cache-dir --upgrade pip setuptools wheel && \
    pip install --no-cache-dir cisco-sdwan && \
    echo "export PS1='\h:\w\$ '" >> /home/sastre/.bashrc && \
    echo "[ \${SASTRE_ROOT_DIR} ] && [ ! -d \${SASTRE_ROOT_DIR}/rc ] && cp -R /sastre-init/rc \${SASTRE_ROOT_DIR}" >> /home/sastre/.bashrc && \
    echo "sdwan -h" >> /home/sastre/.bashrc

# Set proper permissions for directories
RUN mkdir -p ${SASTRE_ROOT_DIR} && \
    chown -R sastre:sastre /sastre-init ${SASTRE_ROOT_DIR} /home/sastre

VOLUME /shared-data

WORKDIR /shared-data

# Switch to non-root user
USER sastre

CMD ["/bin/bash"]
