# ---- builder ---------------------------------------------------------------------------------
FROM rust:1.83-bookworm AS builder
WORKDIR /build
COPY rust/fxradar-serve/Cargo.toml rust/fxradar-serve/Cargo.lock* ./
COPY rust/fxradar-serve/src ./src
COPY rust/fxradar-serve/benches ./benches
COPY rust/fxradar-serve/tests ./tests
RUN cargo build --release --bin fxradar-serve --bin selftest

# ---- runtime ---------------------------------------------------------------------------------
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=builder /build/target/release/fxradar-serve /build/target/release/selftest /usr/local/bin/
# onnxruntime dylibs are copied next to the binaries by ort's copy-dylibs feature at build time
COPY --from=builder /build/target/release/*.so* /usr/local/lib/ 2>/dev/null || true
ENV LD_LIBRARY_PATH=/usr/local/lib
# the bundle and the artifacts are mounted read-only (see docker-compose.yml)
EXPOSE 8080
ENTRYPOINT ["fxradar-serve", "--bundle", "/bundle", "--data-dir", "/data", "--bind", "0.0.0.0:8080"]
