//! FX Regime Radar — the production side of the wall.
//!
//! This crate scores raw price windows into regime / change-risk / anomaly outputs using ONLY the
//! versioned model bundle exported by Python (json + onnx + parquet). It imports nothing from
//! Python at runtime, does no network I/O and writes no files. At start-up the [`selftest`]
//! replays every golden vector and the caller must refuse to serve on any mismatch.

pub mod bundle;
pub mod error;
pub mod features;
pub mod hmm;
pub mod infer;
pub mod selftest;

pub use bundle::Bundle;
pub use error::EngineError;
pub use features::{FeatureRow, PairWindow};
pub use infer::{Engine, ScoredRow};
