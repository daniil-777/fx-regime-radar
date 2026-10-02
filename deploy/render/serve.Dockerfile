# FX Regime Radar — the Rust service with its artifacts BAKED IN, for hosts that cannot bind-mount
# the git checkout (Render). Serves the AI presenter (/avatar), the scoring API and the widget.
# Same binary and the same start-up golden-vector self-test as rust/fxradar-serve/Dockerfile; the
# differences:
#   - the model bundle, data/, prompts/ and docs/avatar_knowledge.md are COPIED in (no volumes);
#     the knowledge pack is read from <data-dir>/../docs/avatar_knowledge.md, hence the layout;
#   - it binds $PORT (Render injects it; 8080 elsewhere);
#   - it builds with the current stable toolchain, the one CI tests (.github/workflows/rust.yml).
# Build from the repo root:  docker build -f deploy/render/serve.Dockerfile .
# serve.Dockerfile.dockerignore (next to this file) replaces the root .dockerignore for this build;
# the root one excludes rust/ and docs/ to keep the Streamlit image's context small.

# ---- builder ---------------------------------------------------------------------------------
FROM rust:1-bookworm AS builder
WORKDIR /build
COPY rust/fxradar-serve/Cargo.toml rust/fxradar-serve/Cargo.lock ./
COPY rust/fxradar-serve/src ./src
COPY rust/fxradar-serve/static ./static
COPY rust/fxradar-serve/benches ./benches
COPY rust/fxradar-serve/tests ./tests
RUN cargo build --release --bin fxradar-serve \
 && mkdir -p /out/bin /out/lib \
 && cp target/release/fxradar-serve /out/bin/ \
 && find target/release -maxdepth 1 -name '*.so*' -exec cp {} /out/lib/ \;

# ---- runtime ---------------------------------------------------------------------------------
FROM debian:bookworm-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates libgomp1 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --uid 1000 radar
COPY --from=builder /out/bin/ /usr/local/bin/
# onnxruntime shared libraries, if ort linked dynamically (the folder is empty when it is static)
COPY --from=builder /out/lib/ /usr/local/lib/
ENV LD_LIBRARY_PATH=/usr/local/lib

WORKDIR /app
# artifacts last, so a daily data refresh reuses the cached Rust build layer
COPY prompts ./prompts
COPY docs/avatar_knowledge.md ./docs/avatar_knowledge.md
COPY models/bundle_v1.4.0 ./models/bundle_v1.4.0
COPY data ./data

# the key / avatar-usage store is a secret sqlite file; on Render's free tier it is ephemeral
RUN mkdir -p /var/lib/fxradar && chown -R radar:radar /app /var/lib/fxradar
USER radar
ENV FXRADAR_KEYS_DB=/var/lib/fxradar/keys.db \
    PORT=8080
EXPOSE 8080
CMD ["sh", "-c", "exec fxradar-serve --bundle models/bundle_v1.4.0 --data-dir data --bind 0.0.0.0:${PORT}"]
