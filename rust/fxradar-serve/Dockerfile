# ---- builder ---------------------------------------------------------------------------------
# current stable, the toolchain CI tests (.github/workflows/rust.yml); a pinned 1.83 predates it
FROM rust:1-bookworm AS builder
WORKDIR /build
COPY rust/fxradar-serve/Cargo.toml rust/fxradar-serve/Cargo.lock* ./
COPY rust/fxradar-serve/src ./src
COPY rust/fxradar-serve/static ./static
COPY rust/fxradar-serve/benches ./benches
COPY rust/fxradar-serve/tests ./tests
# stage outputs in /out so the runtime COPYs never depend on a glob matching (an empty glob fails)
RUN cargo build --release --bin fxradar-serve --bin selftest --bin keys \
 && mkdir -p /out/bin /out/lib \
 && cp target/release/fxradar-serve target/release/selftest target/release/keys /out/bin/ \
 && find target/release -maxdepth 1 -name '*.so*' -exec cp {} /out/lib/ \;

# ---- runtime ---------------------------------------------------------------------------------
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# the versioned avatar system prompt (phase 35); the binary also carries a compiled-in fallback
COPY prompts /app/prompts
COPY --from=builder /out/bin/ /usr/local/bin/
# onnxruntime shared libraries, if ort linked dynamically (the folder is empty when it is static);
# COPY has no shell, so the previous `2>/dev/null || true` suffix was parsed as source paths
COPY --from=builder /out/lib/ /usr/local/lib/
ENV LD_LIBRARY_PATH=/usr/local/lib
# the bundle and the artifacts are mounted read-only (see docker-compose.yml); the key store
# (phase 24) needs a writable volume — mount one at /var/lib/fxradar (it is a secret file)
RUN mkdir -p /var/lib/fxradar
ENV FXRADAR_KEYS_DB=/var/lib/fxradar/keys.db
EXPOSE 8080
ENTRYPOINT ["fxradar-serve", "--bundle", "/bundle", "--data-dir", "/data", "--bind", "0.0.0.0:8080"]
