# ---- builder ---------------------------------------------------------------------------------
FROM rust:1.83-bookworm AS builder
WORKDIR /build
COPY rust/fxradar-serve/Cargo.toml rust/fxradar-serve/Cargo.lock* ./
COPY rust/fxradar-serve/src ./src
COPY rust/fxradar-serve/static ./static
COPY rust/fxradar-serve/benches ./benches
COPY rust/fxradar-serve/tests ./tests
RUN cargo build --release --bin fxradar-serve --bin selftest --bin keys

# ---- runtime ---------------------------------------------------------------------------------
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# the versioned avatar system prompt (phase 35); the binary also carries a compiled-in fallback
COPY prompts /app/prompts
COPY --from=builder /build/target/release/fxradar-serve /build/target/release/selftest /build/target/release/keys /usr/local/bin/
# onnxruntime dylibs are copied next to the binaries by ort's copy-dylibs feature at build time
COPY --from=builder /build/target/release/*.so* /usr/local/lib/ 2>/dev/null || true
ENV LD_LIBRARY_PATH=/usr/local/lib
# the bundle and the artifacts are mounted read-only (see docker-compose.yml); the key store
# (phase 24) needs a writable volume — mount one at /var/lib/fxradar (it is a secret file)
RUN mkdir -p /var/lib/fxradar
ENV FXRADAR_KEYS_DB=/var/lib/fxradar/keys.db
EXPOSE 8080
ENTRYPOINT ["fxradar-serve", "--bundle", "/bundle", "--data-dir", "/data", "--bind", "0.0.0.0:8080"]
