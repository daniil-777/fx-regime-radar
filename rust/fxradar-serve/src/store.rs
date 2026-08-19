//! SQLite-backed store for API keys, webhooks and alert state (phase 24).
//!
//! Only the SHA-256 hex of a key is ever stored; the plaintext is printed once by the `keys`
//! CLI and never seen again. The database file itself is a secret (it holds webhook secrets and
//! Telegram bot URLs), so it lives outside git (`data/keys.db` by default, gitignored).

use rand::RngCore;
use rusqlite::{params, Connection, OptionalExtension};
use sha2::{Digest, Sha256};
use std::fmt;
use std::path::Path;
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

/// Access tier of an API key. Unknown strings parse as `Free` (deny by default).
#[derive(Debug, Clone, Copy, PartialEq, Eq, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Tier {
    Free,
    Pro,
    Partner,
}

impl Tier {
    pub fn parse(s: &str) -> Tier {
        match s.trim().to_ascii_lowercase().as_str() {
            "pro" => Tier::Pro,
            "partner" => Tier::Partner,
            _ => Tier::Free,
        }
    }
    pub fn as_str(&self) -> &'static str {
        match self {
            Tier::Free => "free",
            Tier::Pro => "pro",
            Tier::Partner => "partner",
        }
    }
    /// Pro and Partner are the paid tiers (alerts, treasury, scoring API).
    pub fn is_paid(&self) -> bool {
        matches!(self, Tier::Pro | Tier::Partner)
    }
}

impl fmt::Display for Tier {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.pad(self.as_str())
    }
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct KeyRecord {
    pub key_hash: String,
    pub tier: Tier,
    pub label: String,
    pub created_at: String,
    pub revoked: bool,
    pub last_used: Option<String>,
}

#[derive(Debug, Clone, serde::Serialize)]
pub struct Webhook {
    pub id: i64,
    pub key_hash: String,
    pub url: String,
    /// "generic" | "slack" | "telegram"
    pub kind: String,
    /// Subscribed pairs; empty = all pairs.
    pub pairs: Vec<String>,
    pub chat_id: Option<String>,
    #[serde(skip_serializing)]
    pub secret: String,
    pub created_at: String,
}

#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    #[error("sqlite error: {0}")]
    Sqlite(#[from] rusqlite::Error),
    #[error("lock poisoned")]
    Poisoned,
    #[error("no key matches prefix {0}")]
    NoMatch(String),
    #[error("prefix {0} is ambiguous ({1} keys)")]
    Ambiguous(String, usize),
}

pub type StoreResult<T> = std::result::Result<T, StoreError>;

/// sha256 hex of the plaintext key — the only form that touches disk.
pub fn hash_key(plaintext: &str) -> String {
    hex::encode(Sha256::digest(plaintext.as_bytes()))
}

/// 32 random bytes, hex, with a recognisable prefix so leaked keys are greppable.
pub fn generate_key() -> String {
    let mut buf = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut buf);
    format!("fxr_{}", hex::encode(buf))
}

/// Random hex secret for webhook signing (returned once at registration).
pub fn generate_secret() -> String {
    let mut buf = [0u8; 32];
    rand::thread_rng().fill_bytes(&mut buf);
    format!("whsec_{}", hex::encode(buf))
}

pub fn now_unix() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs())
        .unwrap_or(0)
}

/// UTC ISO-8601 timestamp (seconds) without pulling in chrono.
pub fn now_iso() -> String {
    iso_from_unix(now_unix())
}

pub fn iso_from_unix(secs: u64) -> String {
    let days = (secs / 86_400) as i64;
    let rem = secs % 86_400;
    format!(
        "{}T{:02}:{:02}:{:02}Z",
        crate::state_store::days_to_iso(days),
        rem / 3600,
        (rem % 3600) / 60,
        rem % 60
    )
}

/// Thread-safe handle over one SQLite connection (operations are microseconds; a mutex is enough).
#[derive(Clone)]
pub struct Store {
    conn: Arc<Mutex<Connection>>,
}

const SCHEMA: &str = r#"
CREATE TABLE IF NOT EXISTS api_keys (
  key_hash   TEXT PRIMARY KEY,
  tier       TEXT NOT NULL DEFAULT 'free',
  label      TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  revoked    INTEGER NOT NULL DEFAULT 0,
  last_used  TEXT
);
CREATE TABLE IF NOT EXISTS webhooks (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  key_hash   TEXT NOT NULL,
  url        TEXT NOT NULL,
  kind       TEXT NOT NULL DEFAULT 'generic',
  pairs      TEXT NOT NULL DEFAULT '',
  chat_id    TEXT,
  secret     TEXT NOT NULL,
  created_at TEXT NOT NULL,
  active     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS last_alerted (
  key_hash   TEXT NOT NULL,
  pair       TEXT NOT NULL,
  trigger    TEXT NOT NULL,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY (key_hash, pair, trigger)
);
"#;

impl Store {
    /// Open (or create) the database at `path` and ensure the schema exists.
    pub fn open(path: &Path) -> StoreResult<Store> {
        if let Some(parent) = path.parent() {
            if !parent.as_os_str().is_empty() {
                let _ = std::fs::create_dir_all(parent);
            }
        }
        let conn = Connection::open(path)?;
        Self::init(conn)
    }

    /// In-memory store (tests, CLI dry runs).
    pub fn open_in_memory() -> StoreResult<Store> {
        Self::init(Connection::open_in_memory()?)
    }

    fn init(conn: Connection) -> StoreResult<Store> {
        conn.execute_batch(
            "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL; PRAGMA foreign_keys=ON;",
        )?;
        conn.execute_batch(SCHEMA)?;
        Ok(Store {
            conn: Arc::new(Mutex::new(conn)),
        })
    }

    fn with<T>(&self, f: impl FnOnce(&Connection) -> rusqlite::Result<T>) -> StoreResult<T> {
        let conn = self.conn.lock().map_err(|_| StoreError::Poisoned)?;
        Ok(f(&conn)?)
    }

    // ---- keys -------------------------------------------------------------------------------

    /// Create a key; returns (plaintext, record). The plaintext is never stored.
    pub fn issue_key(&self, label: &str, tier: Tier) -> StoreResult<(String, KeyRecord)> {
        let plain = generate_key();
        let rec = KeyRecord {
            key_hash: hash_key(&plain),
            tier,
            label: label.to_string(),
            created_at: now_iso(),
            revoked: false,
            last_used: None,
        };
        self.with(|c| {
            c.execute(
                "INSERT INTO api_keys (key_hash, tier, label, created_at, revoked) VALUES (?1, ?2, ?3, ?4, 0)",
                params![rec.key_hash, rec.tier.as_str(), rec.label, rec.created_at],
            )
        })?;
        Ok((plain, rec))
    }

    /// Look up a key by its plaintext (hashes first). `None` if unknown.
    pub fn lookup_plaintext(&self, plaintext: &str) -> StoreResult<Option<KeyRecord>> {
        self.lookup_hash(&hash_key(plaintext))
    }

    pub fn lookup_hash(&self, key_hash: &str) -> StoreResult<Option<KeyRecord>> {
        self.with(|c| {
            c.query_row(
                "SELECT key_hash, tier, label, created_at, revoked, last_used FROM api_keys WHERE key_hash = ?1",
                params![key_hash],
                row_to_key,
            )
            .optional()
        })
    }

    pub fn touch_last_used(&self, key_hash: &str) -> StoreResult<()> {
        self.with(|c| {
            c.execute(
                "UPDATE api_keys SET last_used = ?1 WHERE key_hash = ?2",
                params![now_iso(), key_hash],
            )
        })?;
        Ok(())
    }

    pub fn list_keys(&self) -> StoreResult<Vec<KeyRecord>> {
        self.with(|c| {
            let mut st = c.prepare(
                "SELECT key_hash, tier, label, created_at, revoked, last_used FROM api_keys ORDER BY created_at",
            )?;
            let rows = st.query_map([], row_to_key)?;
            rows.collect()
        })
    }

    /// Resolve a unique hash prefix to the full hash.
    pub fn resolve_prefix(&self, prefix: &str) -> StoreResult<String> {
        let prefix = prefix.trim().to_ascii_lowercase();
        let hashes: Vec<String> = self.with(|c| {
            let mut st = c.prepare("SELECT key_hash FROM api_keys WHERE key_hash LIKE ?1")?;
            let rows = st.query_map(params![format!("{prefix}%")], |r| r.get(0))?;
            rows.collect()
        })?;
        match hashes.len() {
            0 => Err(StoreError::NoMatch(prefix)),
            1 => Ok(hashes.into_iter().next().unwrap_or_default()),
            n => Err(StoreError::Ambiguous(prefix, n)),
        }
    }

    pub fn revoke(&self, prefix: &str) -> StoreResult<String> {
        let h = self.resolve_prefix(prefix)?;
        self.with(|c| {
            c.execute(
                "UPDATE api_keys SET revoked = 1 WHERE key_hash = ?1",
                params![h],
            )
        })?;
        Ok(h)
    }

    pub fn set_tier(&self, prefix: &str, tier: Tier) -> StoreResult<String> {
        let h = self.resolve_prefix(prefix)?;
        self.with(|c| {
            c.execute(
                "UPDATE api_keys SET tier = ?1 WHERE key_hash = ?2",
                params![tier.as_str(), h],
            )
        })?;
        Ok(h)
    }

    // ---- webhooks ---------------------------------------------------------------------------

    /// Register a webhook; returns the record including the freshly generated secret.
    pub fn add_webhook(
        &self,
        key_hash: &str,
        url: &str,
        kind: &str,
        pairs: &[String],
        chat_id: Option<&str>,
    ) -> StoreResult<Webhook> {
        let secret = generate_secret();
        let created_at = now_iso();
        let pairs_csv = pairs.join(",");
        let id = self.with(|c| {
            c.execute(
                "INSERT INTO webhooks (key_hash, url, kind, pairs, chat_id, secret, created_at, active) VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, 1)",
                params![key_hash, url, kind, pairs_csv, chat_id, secret, created_at],
            )?;
            Ok(c.last_insert_rowid())
        })?;
        Ok(Webhook {
            id,
            key_hash: key_hash.to_string(),
            url: url.to_string(),
            kind: kind.to_string(),
            pairs: pairs.to_vec(),
            chat_id: chat_id.map(|s| s.to_string()),
            secret,
            created_at,
        })
    }

    pub fn list_webhooks(&self, key_hash: Option<&str>) -> StoreResult<Vec<Webhook>> {
        self.with(|c| {
            let sql = "SELECT id, key_hash, url, kind, pairs, chat_id, secret, created_at FROM webhooks WHERE active = 1 AND (?1 IS NULL OR key_hash = ?1) ORDER BY id";
            let mut st = c.prepare(sql)?;
            let rows = st.query_map(params![key_hash], row_to_webhook)?;
            rows.collect()
        })
    }

    /// Soft-delete; returns true if a webhook owned by `key_hash` was removed.
    pub fn delete_webhook(&self, key_hash: &str, id: i64) -> StoreResult<bool> {
        let n = self.with(|c| {
            c.execute(
                "UPDATE webhooks SET active = 0 WHERE id = ?1 AND key_hash = ?2 AND active = 1",
                params![id, key_hash],
            )
        })?;
        Ok(n > 0)
    }

    // ---- alert state -------------------------------------------------------------------------

    pub fn last_alerted(
        &self,
        key_hash: &str,
        pair: &str,
        trigger: &str,
    ) -> StoreResult<Option<String>> {
        self.with(|c| {
            c.query_row(
                "SELECT value FROM last_alerted WHERE key_hash = ?1 AND pair = ?2 AND trigger = ?3",
                params![key_hash, pair, trigger],
                |r| r.get::<_, String>(0),
            )
            .optional()
        })
    }

    pub fn set_last_alerted(
        &self,
        key_hash: &str,
        pair: &str,
        trigger: &str,
        value: &str,
    ) -> StoreResult<()> {
        self.with(|c| {
            c.execute(
                "INSERT INTO last_alerted (key_hash, pair, trigger, value, updated_at) VALUES (?1, ?2, ?3, ?4, ?5)
                 ON CONFLICT(key_hash, pair, trigger) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                params![key_hash, pair, trigger, value, now_iso()],
            )
        })?;
        Ok(())
    }
}

fn row_to_key(r: &rusqlite::Row<'_>) -> rusqlite::Result<KeyRecord> {
    Ok(KeyRecord {
        key_hash: r.get(0)?,
        tier: Tier::parse(&r.get::<_, String>(1)?),
        label: r.get(2)?,
        created_at: r.get(3)?,
        revoked: r.get::<_, i64>(4)? != 0,
        last_used: r.get(5)?,
    })
}

fn row_to_webhook(r: &rusqlite::Row<'_>) -> rusqlite::Result<Webhook> {
    let pairs_csv: String = r.get(4)?;
    Ok(Webhook {
        id: r.get(0)?,
        key_hash: r.get(1)?,
        url: r.get(2)?,
        kind: r.get(3)?,
        pairs: pairs_csv
            .split(',')
            .filter(|s| !s.is_empty())
            .map(|s| s.to_string())
            .collect(),
        chat_id: r.get(5)?,
        secret: r.get(6)?,
        created_at: r.get(7)?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keys_roundtrip_hash_only() {
        let s = Store::open_in_memory().unwrap();
        let (plain, rec) = s.issue_key("test", Tier::Pro).unwrap();
        assert!(plain.starts_with("fxr_"));
        assert_eq!(rec.key_hash, hash_key(&plain));
        let found = s.lookup_plaintext(&plain).unwrap().unwrap();
        assert_eq!(found.tier, Tier::Pro);
        assert!(!found.revoked);
        // the plaintext never appears in the db
        let all = s.list_keys().unwrap();
        assert_eq!(all.len(), 1);
        assert_ne!(all[0].key_hash, plain);
        s.revoke(&rec.key_hash[..8]).unwrap();
        assert!(s.lookup_plaintext(&plain).unwrap().unwrap().revoked);
        s.set_tier(&rec.key_hash[..8], Tier::Partner).unwrap();
        assert_eq!(
            s.lookup_plaintext(&plain).unwrap().unwrap().tier,
            Tier::Partner
        );
    }

    #[test]
    fn unknown_tier_is_free() {
        assert_eq!(Tier::parse("gold"), Tier::Free);
        assert_eq!(Tier::parse(" PRO "), Tier::Pro);
    }

    #[test]
    fn webhooks_and_alert_state() {
        let s = Store::open_in_memory().unwrap();
        let (_, rec) = s.issue_key("w", Tier::Pro).unwrap();
        let w = s
            .add_webhook(
                &rec.key_hash,
                "http://x/hook",
                "generic",
                &["EURUSD".into()],
                None,
            )
            .unwrap();
        assert!(w.secret.starts_with("whsec_"));
        assert_eq!(s.list_webhooks(Some(&rec.key_hash)).unwrap().len(), 1);
        assert!(s.delete_webhook(&rec.key_hash, w.id).unwrap());
        assert!(!s.delete_webhook(&rec.key_hash, w.id).unwrap());
        assert!(s.list_webhooks(None).unwrap().is_empty());
        assert!(s
            .last_alerted("k", "EURUSD", "regime_flip")
            .unwrap()
            .is_none());
        s.set_last_alerted("k", "EURUSD", "regime_flip", "calm")
            .unwrap();
        s.set_last_alerted("k", "EURUSD", "regime_flip", "chop")
            .unwrap();
        assert_eq!(
            s.last_alerted("k", "EURUSD", "regime_flip")
                .unwrap()
                .as_deref(),
            Some("chop")
        );
    }

    #[test]
    fn iso_timestamp_format() {
        assert_eq!(iso_from_unix(0), "1970-01-01T00:00:00Z");
        assert_eq!(iso_from_unix(1_700_000_000), "2023-11-14T22:13:20Z");
    }
}
