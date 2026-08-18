//! Load and verify the model bundle. Hash verification happens FIRST; any mismatch is a hard error.

use crate::error::{EngineError, Result};
use serde::Deserialize;
use sha2::{Digest, Sha256};
use std::collections::BTreeMap;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone, Deserialize)]
pub struct Manifest {
    pub bundle_version: String,
    pub created_at: String,
    pub git_commit: String,
    pub model_versions: BTreeMap<String, String>,
    pub files: BTreeMap<String, String>,
    #[serde(default)]
    pub goldens: serde_json::Value,
}

#[derive(Debug, Clone, Deserialize)]
pub struct HmmParams {
    pub pair: String,
    pub version: String,
    pub features: Vec<String>,
    pub n_states: usize,
    pub means: Vec<Vec<f64>>,
    pub precisions: Vec<Vec<Vec<f64>>>,
    pub log_dets: Vec<f64>,
    pub transmat: Vec<Vec<f64>>,
    pub startprob: Vec<f64>,
    pub scaler_mean: Vec<f64>,
    pub scaler_scale: Vec<f64>,
    pub state_names: Vec<String>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct Calibration {
    pub a: f64,
    pub b: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct ForecasterSidecar {
    pub version: String,
    pub features: Vec<String>,
    pub onnx_input: String,
    pub onnx_output_probabilities: String,
    pub calibration: Calibration,
    pub threshold: f64,
}

#[derive(Debug, Clone, Deserialize)]
pub struct SirenSidecar {
    pub version: String,
    pub features: Vec<String>,
    pub onnx_input: String,
    pub onnx_output: String,
    pub scaler_mean: Vec<f64>,
    pub scaler_scale: Vec<f64>,
    pub train_scores_sorted: Vec<f64>,
}

#[derive(Debug, Clone, Deserialize)]
pub struct FeatureSpec {
    pub version: String,
    pub pairs: Vec<String>,
    pub usd_base_pairs: Vec<String>,
    pub warmup_rows: usize,
    pub golden_window_rows: usize,
}

/// Everything the engine needs, loaded from one bundle directory and hash-verified.
#[derive(Debug, Clone)]
pub struct Bundle {
    pub dir: PathBuf,
    pub manifest: Manifest,
    pub spec: FeatureSpec,
    pub hmm: BTreeMap<String, HmmParams>,
    pub forecaster: ForecasterSidecar,
    pub siren: SirenSidecar,
}

fn read(path: &Path) -> Result<Vec<u8>> {
    fs::read(path).map_err(|source| EngineError::Io {
        path: path.display().to_string(),
        source,
    })
}

fn read_json<T: for<'de> Deserialize<'de>>(dir: &Path, file: &str) -> Result<T> {
    let bytes = read(&dir.join(file))?;
    serde_json::from_slice(&bytes).map_err(|source| EngineError::Json {
        file: file.to_string(),
        source,
    })
}

pub fn sha256_hex(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

impl Bundle {
    /// Verify every hash in the manifest, then parse the json/yaml sidecars.
    pub fn load(dir: impl AsRef<Path>) -> Result<Self> {
        let dir = dir.as_ref().to_path_buf();
        let manifest: Manifest = read_json(&dir, "manifest.json")?;
        Self::verify_hashes(&dir, &manifest)?;
        let spec_bytes = read(&dir.join("feature_spec.yaml"))?;
        let spec: FeatureSpec =
            serde_yaml::from_slice(&spec_bytes).map_err(|source| EngineError::Yaml {
                file: "feature_spec.yaml".into(),
                source,
            })?;
        let mut hmm = BTreeMap::new();
        for pair in &spec.pairs {
            let params: HmmParams = read_json(&dir, &format!("hmm_{pair}.json"))?;
            hmm.insert(pair.clone(), params);
        }
        let forecaster: ForecasterSidecar = read_json(&dir, "forecaster.json")?;
        let siren: SirenSidecar = read_json(&dir, "siren.json")?;
        Ok(Self {
            dir,
            manifest,
            spec,
            hmm,
            forecaster,
            siren,
        })
    }

    /// Recompute SHA-256 for every file listed in the manifest; the first mismatch is fatal.
    pub fn verify_hashes(dir: &Path, manifest: &Manifest) -> Result<()> {
        for (file, expected) in &manifest.files {
            let path = dir.join(file);
            if !path.exists() {
                return Err(EngineError::MissingFile { file: file.clone() });
            }
            let actual = sha256_hex(&read(&path)?);
            if &actual != expected {
                return Err(EngineError::HashMismatch {
                    file: file.clone(),
                    expected: expected.clone(),
                    actual,
                });
            }
        }
        Ok(())
    }

    pub fn path(&self, file: &str) -> PathBuf {
        self.dir.join(file)
    }
}
