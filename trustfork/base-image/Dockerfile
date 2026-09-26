FROM python:3.12-slim
ARG OPENCODE_VERSION=1.18.13
ARG PI_VERSION=0.84.1
ARG PI_SUBAGENTS_VERSION=0.15.0
ARG PI_SOURCE_COMMIT=534bcbffb7e1e7551d9ee3572dfeb278e203e493
ARG OPENCLAW_VERSION=2026.7.1-2
ARG NODE_VERSION=24.15.0
ARG TARGETARCH
ENV NVM_DIR=/root/.nvm
LABEL org.trustfork.pi.version="${PI_VERSION}" \
      org.trustfork.pi.source_commit="${PI_SOURCE_COMMIT}"
COPY openclaw-batch-wake /opt/trustfork/openclaw-batch-wake
RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git jq ripgrep unzip \
    && rm -rf /var/lib/apt/lists/* \
    && curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.2/install.sh | env -u NODE_VERSION bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install "$NODE_VERSION" \
    && nvm alias default "$NODE_VERSION" \
    && OPENCODE_ARCH="$TARGETARCH" \
    && if [ "$OPENCODE_ARCH" = "amd64" ]; then OPENCODE_ARCH=x64; fi \
    && npm install -g --ignore-scripts "opencode-ai@${OPENCODE_VERSION}" \
        "opencode-linux-${OPENCODE_ARCH}@${OPENCODE_VERSION}" \
        "@earendil-works/pi-coding-agent@${PI_VERSION}" \
        "openclaw@${OPENCLAW_VERSION}" \
    && NODE_MODULES="$(npm root -g)" \
    && cp "$NODE_MODULES/opencode-linux-${OPENCODE_ARCH}/bin/opencode" \
        "$NODE_MODULES/opencode-ai/bin/opencode.exe" \
    && chmod 755 "$NODE_MODULES/opencode-ai/bin/opencode.exe" \
    && NODE_BIN="$(dirname "$(command -v node)")" \
    && ln -sf "$NODE_BIN/node" /usr/local/bin/node \
    && ln -sf "$NODE_BIN/npm" /usr/local/bin/npm \
    && ln -sf "$NODE_BIN/npx" /usr/local/bin/npx \
    && ln -sf "$NODE_BIN/opencode" /usr/local/bin/opencode \
    && ln -sf "$NODE_BIN/pi" /usr/local/bin/pi \
    && ln -sf "$NODE_BIN/openclaw" /usr/local/bin/openclaw \
    && pi install "npm:@tintinweb/pi-subagents@${PI_SUBAGENTS_VERSION}" \
    && pip install --no-cache-dir flask \
    && test "$(opencode --version | tail -n 1 | tr -d '\r')" = "$OPENCODE_VERSION" \
    && test "$(pi --version | tail -n 1 | tr -d '\r')" = "$PI_VERSION" \
    && npm list -g "openclaw@${OPENCLAW_VERSION}" --depth=0 >/dev/null \
    && node /opt/trustfork/openclaw-batch-wake/apply.mjs "$NODE_MODULES/openclaw" \
    && openclaw --version >/dev/null
WORKDIR /workspace
