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

/// One avatar Q/A row (phase 35).
#[derive(Debug, Clone, serde::Serialize)]
pub struct Transcript {
    pub id: i64,
    pub ts: String,
    pub session_id: String,
    pub question: String,
    pub answer: String,
    pub source: String,
    pub gate: String,
    pub latency_ms: i64,
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
CREATE TABLE IF NOT EXISTS avatar_transcripts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  ts         TEXT NOT NULL,
  session_id TEXT NOT NULL,
  question   TEXT NOT NULL,
  answer     TEXT NOT NULL,
  source     TEXT NOT NULL,
  gate       TEXT NOT NULL,
  latency_ms INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS avatar_usage (
  month      TEXT PRIMARY KEY,
  sessions   INTEGER NOT NULL DEFAULT 0,
  minutes    REAL NOT NULL DEFAULT 0,
  chars      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS avatar_sessions (
  token      TEXT PRIMARY KEY,
  session_id TEXT NOT NULL,
  created_ts INTEGER NOT NULL,
  expires_ts INTEGER NOT NULL
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
        // phase-35 delta: TTS character column on databases created before it existed (the
        // error when the column is already there is the expected no-op).
        let _ = conn.execute(
            "ALTER TABLE avatar_usage ADD COLUMN chars INTEGER NOT NULL DEFAULT 0",
            [],
        );
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

    // ---- avatar (phase 35): transcripts, monthly usage caps, short-lived session tokens ------

    /// Log one gated Q/A (weekly human review is a standing ops task; never used for anything
    /// else — see docs/PRIVACY.md).
    pub fn add_transcript(
        &self,
        session_id: &str,
        question: &str,
        answer: &str,
        source: &str,
        gate: &str,
        latency_ms: i64,
    ) -> StoreResult<i64> {
        self.with(|c| {
            c.execute(
                "INSERT INTO avatar_transcripts (ts, session_id, question, answer, source, gate, latency_ms)
                 VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7)",
                params![now_iso(), session_id, question, answer, source, gate, latency_ms],
            )?;
            Ok(c.last_insert_rowid())
        })
    }

    /// Newest transcripts first.
    pub fn recent_transcripts(&self, limit: i64) -> StoreResult<Vec<Transcript>> {
        self.with(|c| {
            let mut st = c.prepare(
                "SELECT id, ts, session_id, question, answer, source, gate, latency_ms
                 FROM avatar_transcripts ORDER BY id DESC LIMIT ?1",
            )?;
            let rows = st.query_map(params![limit], |r| {
                Ok(Transcript {
                    id: r.get(0)?,
                    ts: r.get(1)?,
                    session_id: r.get(2)?,
                    question: r.get(3)?,
                    answer: r.get(4)?,
                    source: r.get(5)?,
                    gate: r.get(6)?,
                    latency_ms: r.get(7)?,
                })
            })?;
            rows.collect()
        })
    }

    /// (sessions, minutes) consumed in a "YYYY-MM" month; (0, 0.0) if unseen.
    pub fn avatar_usage(&self, month: &str) -> StoreResult<(i64, f64)> {
        self.with(|c| {
            c.query_row(
                "SELECT sessions, minutes FROM avatar_usage WHERE month = ?1",
                params![month],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map(|v| v.unwrap_or((0, 0.0)))
        })
    }

    pub fn add_avatar_session_count(&self, month: &str) -> StoreResult<()> {
        self.with(|c| {
            c.execute(
                "INSERT INTO avatar_usage (month, sessions, minutes) VALUES (?1, 1, 0)
                 ON CONFLICT(month) DO UPDATE SET sessions = sessions + 1",
                params![month],
            )
        })?;
        Ok(())
    }

    pub fn add_avatar_minutes(&self, month: &str, minutes: f64) -> StoreResult<()> {
        self.with(|c| {
            c.execute(
                "INSERT INTO avatar_usage (month, sessions, minutes) VALUES (?1, 0, ?2)
                 ON CONFLICT(month) DO UPDATE SET minutes = minutes + excluded.minutes",
                params![month, minutes],
            )
        })?;
        Ok(())
    }

    /// TTS characters consumed in a "YYYY-MM" month; 0 if unseen.
    pub fn avatar_chars(&self, month: &str) -> StoreResult<i64> {
        self.with(|c| {
            c.query_row(
                "SELECT chars FROM avatar_usage WHERE month = ?1",
                params![month],
                |r| r.get(0),
            )
            .optional()
            .map(|v| v.unwrap_or(0))
        })
    }

    pub fn add_avatar_chars(&self, month: &str, n: i64) -> StoreResult<()> {
        self.with(|c| {
            c.execute(
                "INSERT INTO avatar_usage (month, sessions, minutes, chars) VALUES (?1, 0, 0, ?2)
                 ON CONFLICT(month) DO UPDATE SET chars = chars + excluded.chars",
                params![month, n],
            )
        })?;
        Ok(())
    }

    /// Mint a short-lived avatar session token (32 hex chars) and prune expired rows.
    pub fn create_avatar_session(&self, session_id: &str, ttl_secs: u64) -> StoreResult<String> {
        let mut buf = [0u8; 16];
        rand::thread_rng().fill_bytes(&mut buf);
        let token = hex::encode(buf);
        let now = now_unix();
        self.insert_avatar_session(&token, session_id, now, now + ttl_secs)?;
        self.with(|c| {
            c.execute(
                "DELETE FROM avatar_sessions WHERE expires_ts < ?1",
                params![now],
            )
        })?;
        Ok(token)
    }

    /// Raw insert (also used by tests to plant an expired session).
    pub fn insert_avatar_session(
        &self,
        token: &str,
        session_id: &str,
        created_ts: u64,
        expires_ts: u64,
    ) -> StoreResult<()> {
        self.with(|c| {
            c.execute(
                "INSERT INTO avatar_sessions (token, session_id, created_ts, expires_ts) VALUES (?1, ?2, ?3, ?4)",
                params![token, session_id, created_ts as i64, expires_ts as i64],
            )
        })?;
        Ok(())
    }

    /// True iff the token exists and has not expired at `now`.
    pub fn avatar_session_valid(&self, token: &str, now: u64) -> StoreResult<bool> {
        self.with(|c| {
            c.query_row(
                "SELECT expires_ts FROM avatar_sessions WHERE token = ?1",
                params![token],
                |r| r.get::<_, i64>(0),
            )
            .optional()
        })
        .map(|v| v.map(|exp| exp >= now as i64).unwrap_or(false))
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
    fn avatar_transcripts_usage_and_sessions() {
        let s = Store::open_in_memory().unwrap();
        // transcripts
        let id = s
            .add_transcript(
                "sess1",
                "what is the siren?",
                "An answer.",
                "template",
                "pass",
                3,
            )
            .unwrap();
        assert!(id > 0);
        let rows = s.recent_transcripts(10).unwrap();
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].question, "what is the siren?");
        assert_eq!(rows[0].gate, "pass");
        // usage upserts
        assert_eq!(s.avatar_usage("2026-08").unwrap(), (0, 0.0));
        s.add_avatar_session_count("2026-08").unwrap();
        s.add_avatar_session_count("2026-08").unwrap();
        s.add_avatar_minutes("2026-08", 1.5).unwrap();
        let (n, m) = s.avatar_usage("2026-08").unwrap();
        assert_eq!(n, 2);
        assert!((m - 1.5).abs() < 1e-12);
        // TTS character cap arithmetic
        assert_eq!(s.avatar_chars("2026-08").unwrap(), 0);
        s.add_avatar_chars("2026-08", 120).unwrap();
        s.add_avatar_chars("2026-09", 80).unwrap();
        assert_eq!(s.avatar_chars("2026-08").unwrap(), 120);
        s.add_avatar_chars("2026-08", 80).unwrap();
        assert_eq!(s.avatar_chars("2026-08").unwrap(), 200);
        assert_eq!(s.avatar_chars("2026-09").unwrap(), 80);
        // months are independent buckets for sessions too
        assert_eq!(s.avatar_usage("2026-09").unwrap().0, 0);
        // session tokens: mint, validate, expire, prune
        let now = now_unix();
        let tok = s.create_avatar_session("sess1", 1800).unwrap();
        assert_eq!(tok.len(), 32);
        assert!(s.avatar_session_valid(&tok, now).unwrap());
        assert!(!s.avatar_session_valid("nope", now).unwrap());
        s.insert_avatar_session("deadbeef", "old", now - 100, now - 1)
            .unwrap();
        assert!(!s.avatar_session_valid("deadbeef", now).unwrap());
        // a later mint prunes the expired row
        let _ = s.create_avatar_session("sess2", 1800).unwrap();
        assert!(!s.avatar_session_valid("deadbeef", now).unwrap());
    }

    #[test]
    fn iso_timestamp_format() {
        assert_eq!(iso_from_unix(0), "1970-01-01T00:00:00Z");
        assert_eq!(iso_from_unix(1_700_000_000), "2023-11-14T22:13:20Z");
    }
}
