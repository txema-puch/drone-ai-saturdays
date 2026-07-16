# syntax=docker/dockerfile:1.10

# These are linux/amd64 image-manifest digests, not mutable multi-arch tags.
ARG NODE_IMAGE="node:22.17.1-bookworm-slim@sha256:ffb27ca0f26a231a08930c872631cea70cbb318463d1e712922b5c7cfdc3fcca"
ARG PYTHON_IMAGE="python:3.11.13-slim-bookworm@sha256:cec9aa7aa96eea4fa036e9b82be1e6b325f2e3707f462d885868df51ec0a4b47"
ARG UV_IMAGE="ghcr.io/astral-sh/uv:0.11.13@sha256:947db38c67f9790712fd2f34081dae2c8df982a2c6f31ae0f430e1ff7f99ce49"

FROM --platform=linux/amd64 ${NODE_IMAGE} AS frontend-build
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM --platform=linux/amd64 ${UV_IMAGE} AS uv-bin

FROM --platform=linux/amd64 ${PYTHON_IMAGE} AS python-deps
ENV UV_CACHE_DIR=/tmp/uv-cache \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_REQUIRE_HASHES=1 \
    UV_TORCH_BACKEND=cpu
COPY --from=uv-bin /uv /uvx /usr/local/bin/
COPY delivery/container/requirements-linux-x86_64.lock /tmp/requirements.lock
RUN --mount=type=cache,target=/tmp/uv-cache \
    uv pip install --system --no-deps --require-hashes -r /tmp/requirements.lock

FROM --platform=linux/amd64 python-deps AS product-wheel
WORKDIR /build/backend
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/research/pyproject.toml ./research/pyproject.toml
COPY backend/src ./src
RUN --mount=type=cache,target=/tmp/uv-cache \
    uv build --wheel --out-dir /tmp/dist \
    && uv pip install --system --no-deps /tmp/dist/sadar-*.whl

# The production target builds only from the redownload-verified schema-v3 lock.
# Keep this stage source-minimal so application edits do not invalidate the immutable
# evidence-artifact download layer.
FROM --platform=linux/amd64 product-wheel AS release-fetch
COPY backend/src/sadar/releases/approach_bundle.lock.json /tmp/approach_bundle.lock.json
RUN sadar-fetch-release \
         --lock /tmp/approach_bundle.lock.json \
         --destination /opt/sadar/release

FROM --platform=linux/amd64 ${PYTHON_IMAGE} AS runtime
ARG SOURCE_COMMIT="unknown"
LABEL org.opencontainers.image.source="https://github.com/txema-puch/drone-ai-saturdays" \
      org.opencontainers.image.revision="${SOURCE_COMMIT}"

ENV HOME=/home/sadar \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SADAR_APPROACH_RELEASE_DIR=/opt/sadar/release \
    SADAR_FRONTEND_DIR=/opt/sadar/frontend \
    TMPDIR=/tmp/sadar \
    PORT=7860

RUN groupadd --gid 1000 sadar \
    && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/sadar sadar \
    && install -d -o 1000 -g 1000 /opt/sadar/frontend /opt/sadar/release /tmp/sadar

WORKDIR /opt/sadar
COPY --from=product-wheel /usr/local /usr/local
COPY --from=frontend-build --chown=1000:1000 /build/frontend/dist ./frontend
COPY --from=release-fetch --chown=1000:1000 /opt/sadar/release /opt/sadar/release
COPY --chown=1000:1000 scripts/container-entrypoint.sh /usr/local/bin/sadar-entrypoint

USER 1000:1000
EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; port=int(os.environ.get('PORT', '7860')); urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=2).read()"]
ENTRYPOINT ["/usr/local/bin/sadar-entrypoint"]
