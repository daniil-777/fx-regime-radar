//! Runtime flags and the kill switch (phase 45).
//!
//! Every flag here can be changed without a redeploy and takes effect on the next turn, including
//! mid-session. That property is the whole point: the moment a mitigation requires a deploy, its
//! recovery time is however long a deploy takes plus however long it takes to find someone who can
//! run one, and at 2 a.m. those are not small numbers.
//!
//! ## Why a file rather than an endpoint
//!
//! Flags live in `config/flags.json` and are re-read when the file's mtime changes — the same
//! pattern every other artifact in this service uses. A file works when the service is wedged, it
//! survives a restart, it is visible in a `cat`, and it is one `git revert` away from whatever it
//! was yesterday. An admin endpoint would be more convenient and would stop working in exactly the
//! situation you need it.
//!
//! An operator endpoint is layered on top for the cases where shell access is the slow path, but
//! the file is the source of truth and the endpoint only writes to it.
//!
//! ## Defaults are the safe value, not the current value
//!
//! A missing or corrupt flags file must not turn features on. Every default below is the
//! conservative reading: the assistant works, the expensive and experimental paths do not.

use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use std::sync::{Arc, Mutex};
use std::time::SystemTime;

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct Flags {
    /// The kill switch. False returns the system to phase-41 behaviour — packs, paraphrase cache
    /// and the FAQ, with no rooms — instantly and mid-session.
    pub agent_enabled: bool,
    /// The archive room (counts, date lookups, durations, episode comparisons).
    pub lane_archive: bool,
    /// The sealed-ledger room. Not yet built as a separate lane; the flag exists so the ladder in
    /// the runbook has a rung for it the day it is.
    pub lane_logbook: bool,
    /// The methodology room.
    pub lane_cookbook: bool,
    /// Nightly precomputed answers.
    pub packs_enabled: bool,
    /// Serving a pack for a near-miss phrasing above the similarity threshold.
    pub paraphrase_cache_enabled: bool,
    /// Reference resolution against per-session state ("and USDCHF?").
    pub conversation_state_enabled: bool,
    /// The slow-lane wait line on the customer surface.
    pub wait_line_enabled: bool,
    /// Declined in phase 41 on measurements; the flag exists so adopting them is a config change
    /// and a measurement rather than a rebuild.
    pub embeddings_enabled: bool,
    /// Run the agentic path alongside the served answer, recording but never serving it.
    pub shadow_mode: bool,
    /// Fraction of turns to shadow. Not 1.0: shadowing every turn doubles model spend to learn
    /// what a sample tells you just as well.
    pub shadow_sample_rate: f64,
}

impl Default for Flags {
    fn default() -> Self {
        Flags {
            agent_enabled: true,
            lane_archive: true,
            lane_logbook: false,
            lane_cookbook: true,
            packs_enabled: true,
            paraphrase_cache_enabled: true,
            conversation_state_enabled: true,
            wait_line_enabled: true,
            // Off until measured, per phase 41's recorded decision.
            embeddings_enabled: false,
            shadow_mode: false,
            shadow_sample_rate: 0.2,
        }
    }
}

impl Flags {
    /// The configuration this turn ran under, for the trace. An old trace read next year has to be
    /// interpretable under the flags that produced it, not under today's.
    pub fn stamp(&self) -> String {
        let mut on: Vec<&str> = Vec::new();
        let mut off: Vec<&str> = Vec::new();
        for (name, value) in [
            ("agent", self.agent_enabled),
            ("archive", self.lane_archive),
            ("logbook", self.lane_logbook),
            ("cookbook", self.lane_cookbook),
            ("packs", self.packs_enabled),
            ("paraphrase", self.paraphrase_cache_enabled),
            ("state", self.conversation_state_enabled),
            ("waitline", self.wait_line_enabled),
            ("embeddings", self.embeddings_enabled),
            ("shadow", self.shadow_mode),
        ] {
            if value {
                on.push(name)
            } else {
                off.push(name)
            }
        }
        format!("on: {} | off: {}", on.join(","), off.join(","))
    }

    /// A short stable hash of the configuration, so an ablation row can name the config it ran
    /// under and two rows can be compared without reading eleven booleans.
    pub fn config_hash(&self) -> String {
        use sha2::{Digest, Sha256};
        let mut h = Sha256::new();
        h.update(serde_json::to_string(self).unwrap_or_default().as_bytes());
        format!("{:x}", h.finalize())[..8].to_string()
    }

    pub fn export_gauges(&self) {
        for (name, value) in [
            ("agent_enabled", self.agent_enabled),
            ("lane_archive", self.lane_archive),
            ("lane_logbook", self.lane_logbook),
            ("lane_cookbook", self.lane_cookbook),
            ("packs_enabled", self.packs_enabled),
            ("paraphrase_cache_enabled", self.paraphrase_cache_enabled),
            (
                "conversation_state_enabled",
                self.conversation_state_enabled,
            ),
            ("wait_line_enabled", self.wait_line_enabled),
            ("embeddings_enabled", self.embeddings_enabled),
            ("shadow_mode", self.shadow_mode),
        ] {
            metrics::gauge!("feature_flag", "flag" => name).set(if value { 1.0 } else { 0.0 });
        }
        metrics::gauge!("shadow_sample_rate").set(self.shadow_sample_rate);
    }
}

/// What the store remembers about the file it last read: when it was modified, how long it was, and
/// what it parsed to. Both the timestamp and the length are checked, because a same-second write of
/// a different length is exactly the case an mtime-only check misses.
struct Cached {
    modified: SystemTime,
    len: u64,
    flags: Arc<Flags>,
}

/// Reads `config/flags.json` on mtime change; falls back to safe defaults.
#[derive(Clone)]
pub struct FlagStore {
    path: PathBuf,
    cache: Arc<Mutex<Option<Cached>>>,
}

impl FlagStore {
    pub fn new(path: PathBuf) -> Self {
        FlagStore {
            path,
            cache: Arc::new(Mutex::new(None)),
        }
    }

    pub fn path(&self) -> &PathBuf {
        &self.path
    }

    /// The current flags. Cheap enough to call once per turn: a stat, and a parse only when the
    /// file has actually changed.
    pub fn get(&self) -> Arc<Flags> {
        let meta = std::fs::metadata(&self.path).ok();
        let stamp = meta.as_ref().and_then(|m| m.modified().ok());
        let len = meta.as_ref().map(|m| m.len()).unwrap_or(0);
        if let Ok(guard) = self.cache.lock() {
            if let Some(c) = guard.as_ref() {
                if Some(c.modified) == stamp && c.len == len {
                    return c.flags.clone();
                }
            }
        }
        // A file that will not parse must not silently become "everything on". It becomes the
        // documented safe default and says so, once, in the log.
        let flags = match std::fs::read_to_string(&self.path) {
            Ok(body) => match serde_json::from_str::<Flags>(&body) {
                Ok(f) => f,
                Err(e) => {
                    tracing::warn!(error = %e, "flags file did not parse; using safe defaults");
                    Flags::default()
                }
            },
            Err(_) => Flags::default(),
        };
        flags.export_gauges();
        let arc = Arc::new(flags);
        if let (Ok(mut guard), Some(modified)) = (self.cache.lock(), stamp) {
            *guard = Some(Cached {
                modified,
                len,
                flags: arc.clone(),
            });
        }
        arc
    }

    /// Write one flag. Used by the operator endpoint; the file stays the source of truth.
    pub fn set(&self, name: &str, value: serde_json::Value) -> Result<Flags, String> {
        let current = (*self.get()).clone();
        let mut obj = serde_json::to_value(&current)
            .map_err(|e| e.to_string())?
            .as_object()
            .cloned()
            .ok_or("flags are not an object")?;
        if !obj.contains_key(name) {
            return Err(format!("unknown flag {name:?}"));
        }
        obj.insert(name.to_string(), value);
        let next: Flags =
            serde_json::from_value(serde_json::Value::Object(obj)).map_err(|e| e.to_string())?;
        if let Some(dir) = self.path.parent() {
            std::fs::create_dir_all(dir).map_err(|e| e.to_string())?;
        }
        std::fs::write(
            &self.path,
            serde_json::to_string_pretty(&next).map_err(|e| e.to_string())?,
        )
        .map_err(|e| e.to_string())?;
        if let Ok(mut guard) = self.cache.lock() {
            *guard = None; // force a re-read, so the write and the read cannot disagree
        }
        next.export_gauges();
        Ok(next)
    }
}

/// Should this turn be shadowed? Deterministic in the session id rather than random, so a session
/// is either shadowed throughout or not at all — half a shadowed conversation measures nothing,
/// because the agentic path would be reasoning from a state it never saw built.
pub fn shadow_this_turn(flags: &Flags, session_id: &str) -> bool {
    if !flags.shadow_mode || flags.shadow_sample_rate <= 0.0 {
        return false;
    }
    if flags.shadow_sample_rate >= 1.0 {
        return true;
    }
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    h.update(session_id.as_bytes());
    let digest = h.finalize();
    let bucket = u16::from_be_bytes([digest[0], digest[1]]) as f64 / u16::MAX as f64;
    bucket < flags.shadow_sample_rate
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_are_safe_when_the_file_is_missing() {
        let store = FlagStore::new(PathBuf::from("/nonexistent/flags.json"));
        let f = store.get();
        assert!(f.agent_enabled, "the assistant works out of the box");
        assert!(!f.embeddings_enabled, "an unmeasured dependency stays off");
        assert!(!f.shadow_mode, "shadow spend is opt-in");
        assert!(!f.lane_logbook, "an unbuilt lane stays off");
    }

    #[test]
    fn a_corrupt_file_falls_back_to_defaults_rather_than_to_everything_on() {
        let dir = std::env::temp_dir().join(format!("fxr_flags_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("flags.json");
        std::fs::write(&path, "{ this is not json").unwrap();
        let f = FlagStore::new(path).get();
        assert_eq!(*f, Flags::default());
    }

    #[test]
    fn setting_a_flag_persists_and_re_reads() {
        let dir = std::env::temp_dir().join(format!("fxr_flags_set_{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        let path = dir.join("flags.json");
        let store = FlagStore::new(path.clone());
        assert!(store.get().agent_enabled);
        let next = store
            .set("agent_enabled", serde_json::json!(false))
            .unwrap();
        assert!(!next.agent_enabled);
        // A fresh store reading the same file must see it — the file is the source of truth.
        assert!(!FlagStore::new(path).get().agent_enabled);
        assert!(store.set("no_such_flag", serde_json::json!(true)).is_err());
    }

    #[test]
    fn shadow_sampling_is_stable_per_session() {
        let flags = Flags {
            shadow_mode: true,
            shadow_sample_rate: 0.5,
            ..Flags::default()
        };
        for id in ["s-1", "s-2", "s-3", "s-4"] {
            let first = shadow_this_turn(&flags, id);
            for _ in 0..20 {
                assert_eq!(
                    shadow_this_turn(&flags, id),
                    first,
                    "a session must be shadowed throughout or not at all"
                );
            }
        }
    }

    #[test]
    fn the_sampling_rate_is_approximately_honoured() {
        let flags = Flags {
            shadow_mode: true,
            shadow_sample_rate: 0.2,
            ..Flags::default()
        };
        let n = 4000;
        let hits = (0..n)
            .filter(|i| shadow_this_turn(&flags, &format!("session-{i}")))
            .count();
        let rate = hits as f64 / n as f64;
        assert!(
            (0.17..0.23).contains(&rate),
            "20% sampling produced {rate:.3} over {n} sessions"
        );
    }

    #[test]
    fn shadow_is_off_unless_asked_for() {
        let mut flags = Flags::default();
        assert!(!shadow_this_turn(&flags, "s"));
        flags.shadow_mode = true;
        flags.shadow_sample_rate = 0.0;
        assert!(
            !shadow_this_turn(&flags, "s"),
            "a zero rate shadows nothing"
        );
    }

    #[test]
    fn the_config_hash_changes_with_the_configuration() {
        let a = Flags::default();
        let mut b = a.clone();
        b.packs_enabled = false;
        assert_ne!(a.config_hash(), b.config_hash());
        assert_eq!(a.config_hash(), Flags::default().config_hash());
        assert_eq!(a.config_hash().len(), 8);
    }

    #[test]
    fn the_stamp_names_what_was_on_and_what_was_off() {
        let f = Flags {
            packs_enabled: false,
            ..Default::default()
        };
        let s = f.stamp();
        assert!(s.contains("on: agent"), "{s}");
        assert!(s.contains("packs"), "{s}");
        let (on, off) = s.split_once(" | off: ").unwrap();
        assert!(!on.contains("packs"));
        assert!(off.contains("packs"));
    }
}
