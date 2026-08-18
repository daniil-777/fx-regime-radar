//! One error enum for the whole engine — no `unwrap`/`expect` in library code.

use thiserror::Error;

#[derive(Debug, Error)]
pub enum EngineError {
    #[error("io error at {path}: {source}")]
    Io {
        path: String,
        #[source]
        source: std::io::Error,
    },
    #[error("json error in {file}: {source}")]
    Json {
        file: String,
        #[source]
        source: serde_json::Error,
    },
    #[error("yaml error in {file}: {source}")]
    Yaml {
        file: String,
        #[source]
        source: serde_yaml::Error,
    },
    #[error("manifest lists {file} but it is missing from the bundle")]
    MissingFile { file: String },
    #[error("SHA-256 mismatch for {file}: manifest {expected}, actual {actual}")]
    HashMismatch {
        file: String,
        expected: String,
        actual: String,
    },
    #[error("parquet error: {0}")]
    Parquet(#[from] parquet::errors::ParquetError),
    #[error("golden {row}: bad column {column}: {reason}")]
    Golden {
        row: usize,
        column: String,
        reason: String,
    },
    #[error("onnx runtime error: {0}")]
    Ort(#[from] ort::Error),
    #[error("shape error: {0}")]
    Shape(String),
    #[error("unknown pair {0}")]
    UnknownPair(String),
    #[error("not enough history for {pair}: {rows} rows, need at least {need}")]
    InsufficientHistory {
        pair: String,
        rows: usize,
        need: usize,
    },
    #[error("window for {pair} has mismatched lengths (dates {dates}, close {close}, high {high}, low {low})")]
    RaggedWindow {
        pair: String,
        dates: usize,
        close: usize,
        high: usize,
        low: usize,
    },
    #[error("self-test failed: {0}")]
    SelfTest(String),
}

pub type Result<T> = std::result::Result<T, EngineError>;
