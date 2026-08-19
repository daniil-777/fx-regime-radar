//! `keys`: tiny admin CLI for API keys (phase 24). Prints a new key's plaintext exactly once;
//! the database holds sha256 hashes only.
//!
//!   keys issue --label "acme treasury" --tier pro
//!   keys list
//!   keys revoke <hash-prefix>
//!   keys set-tier <hash-prefix> partner
//!   keys webhooks            (all registered webhooks, secrets hidden)

use clap::{Parser, Subcommand};
use fxradar_serve::store::{Store, Tier};
use std::path::PathBuf;

#[derive(Parser, Debug)]
#[command(
    name = "keys",
    about = "FX Regime Radar — API key admin (sha256 hashes only)"
)]
struct Args {
    /// SQLite file (env FXRADAR_KEYS_DB). NOT committed; treat as a secret file.
    #[arg(long, env = "FXRADAR_KEYS_DB", default_value = "data/keys.db")]
    db: PathBuf,
    #[command(subcommand)]
    cmd: Cmd,
}

#[derive(Subcommand, Debug)]
enum Cmd {
    /// Create a key and print its plaintext ONCE
    Issue {
        #[arg(long, default_value = "")]
        label: String,
        /// free | pro | partner
        #[arg(long, default_value = "free")]
        tier: String,
    },
    /// List keys (hash prefix, tier, label, created, revoked, last used)
    List,
    /// Revoke a key by unique hash prefix
    Revoke { prefix: String },
    /// Change a key's tier (free | pro | partner)
    SetTier { prefix: String, tier: String },
    /// List registered webhooks (secrets hidden)
    Webhooks,
}

fn main() {
    let args = Args::parse();
    let store = match Store::open(&args.db) {
        Ok(s) => s,
        Err(e) => {
            eprintln!("cannot open {}: {e}", args.db.display());
            std::process::exit(1);
        }
    };
    let res = match args.cmd {
        Cmd::Issue { label, tier } => {
            let tier_parsed = Tier::parse(&tier);
            if tier_parsed.as_str() != tier.trim().to_ascii_lowercase() {
                eprintln!("unknown tier {tier:?}; use free | pro | partner");
                std::process::exit(2);
            }
            store.issue_key(&label, tier_parsed).map(|(plain, rec)| {
                println!("API key (shown ONCE, store it now):\n\n  {plain}\n");
                println!(
                    "hash prefix: {}   tier: {}   label: {:?}   created: {}",
                    &rec.key_hash[..12],
                    rec.tier,
                    rec.label,
                    rec.created_at
                );
            })
        }
        Cmd::List => store.list_keys().map(|keys| {
            println!(
                "{:<14} {:<8} {:<9} {:<20} {:<20} label",
                "hash-prefix", "tier", "revoked", "created", "last_used"
            );
            for k in keys {
                println!(
                    "{:<14} {:<8} {:<9} {:<20} {:<20} {}",
                    &k.key_hash[..12],
                    k.tier,
                    if k.revoked { "yes" } else { "no" },
                    k.created_at,
                    k.last_used.unwrap_or_else(|| "-".into()),
                    k.label
                );
            }
        }),
        Cmd::Revoke { prefix } => store
            .revoke(&prefix)
            .map(|h| println!("revoked {}", &h[..12])),
        Cmd::SetTier { prefix, tier } => {
            let t = Tier::parse(&tier);
            if t.as_str() != tier.trim().to_ascii_lowercase() {
                eprintln!("unknown tier {tier:?}; use free | pro | partner");
                std::process::exit(2);
            }
            store
                .set_tier(&prefix, t)
                .map(|h| println!("{} -> {}", &h[..12], t))
        }
        Cmd::Webhooks => store.list_webhooks(None).map(|hooks| {
            println!(
                "{:<5} {:<14} {:<9} {:<12} url",
                "id", "key-prefix", "kind", "pairs"
            );
            for h in hooks {
                let pairs = if h.pairs.is_empty() {
                    "all".to_string()
                } else {
                    h.pairs.join("+")
                };
                println!(
                    "{:<5} {:<14} {:<9} {:<12} {}",
                    h.id,
                    &h.key_hash[..12],
                    h.kind,
                    pairs,
                    redact(&h.url)
                );
            }
        }),
    };
    if let Err(e) = res {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}

/// Hide path segments (Slack/Telegram URLs embed secrets).
fn redact(url: &str) -> String {
    match url
        .find("://")
        .and_then(|i| url[i + 3..].find('/').map(|j| i + 3 + j))
    {
        Some(p) => format!("{}/…", &url[..p]),
        None => url.to_string(),
    }
}
