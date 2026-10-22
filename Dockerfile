FROM python:3.13.16-slim-trixie AS build-image

# Install system dependencies needed for downloading and extracting
RUN apt-get update -y && \
    apt-get install -y --no-install-recommends wget unzip xz-utils && \
    rm -rf /var/lib/apt/lists/* && \
    apt-get purge --auto-remove && \
    apt-get clean

# Install Bento4 in the specified location
RUN mkdir -p /home/mediacms.io/bento4 && \
    wget -q --tries=5 --waitretry=10 --timeout=30 https://www.bok.net/Bento4/binaries/Bento4-SDK-1-6-0-637.x86_64-unknown-linux.zip && \
    unzip Bento4-SDK-1-6-0-637.x86_64-unknown-linux.zip -d /home/mediacms.io/bento4 && \
    mv /home/mediacms.io/bento4/Bento4-SDK-1-6-0-637.x86_64-unknown-linux/* /home/mediacms.io/bento4/ && \
    rm -rf /home/mediacms.io/bento4/Bento4-SDK-1-6-0-637.x86_64-unknown-linux && \
    rm -rf /home/mediacms.io/bento4/docs && \
    rm Bento4-SDK-1-6-0-637.x86_64-unknown-linux.zip

# Jellyfin ffmpeg portable build, for NVIDIA NVENC/CUVID support
# Releases + sha256 digests: https://github.com/jellyfin/jellyfin-ffmpeg/releases
ARG JELLYFIN_FFMPEG_VERSION=8.1.3-1
ARG JELLYFIN_FFMPEG_SHA256=b86dc023c64a5a9a410e6e3a938a970460214fae78f31c1553c9f88f1c289b6a
RUN mkdir -p /opt/jellyfin-ffmpeg && \
    wget -q --tries=5 --waitretry=10 --timeout=30 -O jellyfin-ffmpeg.tar.xz \
        https://github.com/jellyfin/jellyfin-ffmpeg/releases/download/v${JELLYFIN_FFMPEG_VERSION}/jellyfin-ffmpeg_${JELLYFIN_FFMPEG_VERSION}_portable_linux64-gpl.tar.xz && \
    echo "${JELLYFIN_FFMPEG_SHA256}  jellyfin-ffmpeg.tar.xz" | sha256sum -c - && \
    tar -xf jellyfin-ffmpeg.tar.xz -C /opt/jellyfin-ffmpeg && \
    rm jellyfin-ffmpeg.tar.xz

############ BASE RUNTIME IMAGE ############
FROM python:3.13.16-slim-trixie AS base

SHELL ["/bin/bash", "-c"]

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV CELERY_APP='cms'
ENV VIRTUAL_ENV=/home/mediacms.io
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# Install system dependencies first
RUN apt-get update -y && \
    apt-get -y upgrade && \
    apt-get install --no-install-recommends -y \
        supervisor \
        nginx \
        imagemagick \
        procps \
        build-essential \
        pkg-config \
        zlib1g-dev \
        zlib1g \
        libxml2-dev \
        libxmlsec1-dev \
        libxmlsec1t64-openssl \
        libpq-dev \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set up virtualenv first
RUN mkdir -p /home/mediacms.io/mediacms/{logs} && \
    cd /home/mediacms.io && \
    python3 -m venv $VIRTUAL_ENV

# Copy requirements files
COPY requirements.txt requirements-dev.txt ./

# Install Python dependencies using pip (within virtualenv)
ARG DEVELOPMENT_MODE=False
RUN pip install --no-cache-dir uv && \
    uv pip install --no-binary lxml --no-binary xmlsec -r requirements.txt && \
    if [ "$DEVELOPMENT_MODE" = "True" ]; then \
        echo "Installing development dependencies..." && \
        uv pip install -r requirements-dev.txt; \
    fi && \
    apt-get purge -y --auto-remove \
        build-essential \
        pkg-config \
        libxml2-dev \
        libxmlsec1-dev \
        libpq-dev

# Copy Jellyfin ffmpeg and Bento4 from build image
COPY --from=build-image /opt/jellyfin-ffmpeg/ffmpeg /opt/jellyfin-ffmpeg/ffprobe /usr/local/bin/
COPY --from=build-image /home/mediacms.io/bento4 /home/mediacms.io/bento4

# Copy application files
COPY . /home/mediacms.io/mediacms
WORKDIR /home/mediacms.io/mediacms

# required for sprite thumbnail generation for large video files
COPY deploy/docker/policy.xml /etc/ImageMagick-7/policy.xml

# Set process control environment variables
ENV ENABLE_UWSGI='yes' \
    ENABLE_NGINX='yes' \
    ENABLE_CELERY_BEAT='yes' \
    ENABLE_CELERY_SHORT='yes' \
    ENABLE_CELERY_LONG='yes' \
    ENABLE_MIGRATIONS='yes'

EXPOSE 9000 80

RUN chmod +x ./deploy/docker/entrypoint.sh

ENTRYPOINT ["./deploy/docker/entrypoint.sh"]
CMD ["./deploy/docker/start.sh"]

############ FULL IMAGE ############
FROM base AS full
COPY requirements-full.txt ./
RUN mkdir -p /root/.cache/ && \
    chmod go+rwx /root/ && \
    chmod go+rwx /root/.cache/
RUN uv pip install -r requirements-full.txt