FROM golang:1.22-bookworm AS voice-worker

WORKDIR /src/workers/voice/go
COPY workers/voice/go /src/workers/voice/go
RUN go build -o /out/yoyopod-voice-worker ./cmd/yoyopod-voice-worker

FROM python:3.12-bookworm AS build

ARG CHANNEL=dev
ARG VERSION=

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONPATH=/src

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ffmpeg \
        git \
        libasound2-dev \
        liblinphone-dev \
        pkg-config && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY . /src
COPY --from=voice-worker /out/yoyopod-voice-worker /src/workers/voice/go/build/yoyopod-voice-worker

# Keep the builder environment intentionally minimal. The release builder itself
# resolves the runtime venv inside the output slot.
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir loguru typer

RUN python -c "import sys; sys.path.insert(0, '/src'); from yoyopod_cli.build import app; app()" ensure-native

RUN if [ -n "$VERSION" ]; then \
        python /src/scripts/build_release.py --output /out --channel "$CHANNEL" --version "$VERSION" --with-venv --python-version 3.12; \
    else \
        python /src/scripts/build_release.py --output /out --channel "$CHANNEL" --with-venv --python-version 3.12; \
    fi

FROM scratch AS export
COPY --from=build /out/ /
