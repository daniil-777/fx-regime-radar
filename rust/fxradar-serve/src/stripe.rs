//! Stripe webhook handling (phase 28, TEST MODE by design): verify `Stripe-Signature`
//! (HMAC-SHA256 of `{t}.{payload}`, 5-minute tolerance) and map subscription events to a tier
//! change. No Stripe SDK; the secret comes from the environment and is never logged.
//!
//! Convention the Checkout Session must follow (documented in docs/API.md):
//!   * `client_reference_id` = the first 12+ hex chars of the API-key hash (`keys list` prints it),
//!     and `subscription_data[metadata][key_prefix]` = the same prefix (so subscription events,
//!     which have no client_reference_id, still identify the key);
//!   * the price's `lookup_key` (or `metadata[tier]`) is "pro" or "partner".

use crate::store::Tier;
use hmac::{Hmac, Mac};
use serde_json::Value;
use sha2::Sha256;

type HmacSha256 = Hmac<Sha256>;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum StripeError {
    #[error("malformed Stripe-Signature header")]
    Malformed,
    #[error("timestamp outside tolerance")]
    Expired,
    #[error("signature mismatch")]
    Mismatch,
}

/// Compute the v1 signature for a (timestamp, payload) pair — used by tests and by docs.
pub fn sign(secret: &str, timestamp: u64, payload: &[u8]) -> String {
    let mut mac =
        HmacSha256::new_from_slice(secret.as_bytes()).expect("hmac accepts any key length");
    mac.update(timestamp.to_string().as_bytes());
    mac.update(b".");
    mac.update(payload);
    hex::encode(mac.finalize().into_bytes())
}

/// Verify `Stripe-Signature: t=<unix>,v1=<hex>[,v1=<hex>...]` against `payload` at time `now`.
pub fn verify(
    secret: &str,
    header: &str,
    payload: &[u8],
    now: u64,
    tolerance_secs: u64,
) -> Result<(), StripeError> {
    let mut ts: Option<u64> = None;
    let mut sigs: Vec<String> = Vec::new();
    for part in header.split(',') {
        let mut kv = part.trim().splitn(2, '=');
        match (kv.next(), kv.next()) {
            (Some("t"), Some(v)) => ts = v.parse().ok(),
            (Some("v1"), Some(v)) => sigs.push(v.to_string()),
            _ => {}
        }
    }
    let ts = ts.ok_or(StripeError::Malformed)?;
    if sigs.is_empty() {
        return Err(StripeError::Malformed);
    }
    if now.abs_diff(ts) > tolerance_secs {
        return Err(StripeError::Expired);
    }
    let expected = sign(secret, ts, payload);
    let ok = sigs
        .iter()
        .any(|s| constant_time_eq(s.as_bytes(), expected.as_bytes()));
    if ok {
        Ok(())
    } else {
        Err(StripeError::Mismatch)
    }
}

fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

/// What a Stripe event asks us to do.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TierChange {
    pub key_prefix: String,
    pub tier: Tier,
    pub event_type: String,
}

fn str_at<'a>(v: &'a Value, path: &[&str]) -> Option<&'a str> {
    let mut cur = v;
    for p in path {
        cur = match p.parse::<usize>() {
            Ok(i) if cur.is_array() => cur.get(i)?,
            _ => cur.get(p)?,
        };
    }
    cur.as_str()
}

fn tier_from_object(obj: &Value) -> Option<Tier> {
    let candidates = [
        str_at(obj, &["metadata", "tier"]),
        str_at(obj, &["items", "data", "0", "price", "lookup_key"]),
        str_at(obj, &["line_items", "data", "0", "price", "lookup_key"]),
        str_at(obj, &["plan", "lookup_key"]),
        str_at(obj, &["items", "data", "0", "price", "metadata", "tier"]),
    ];
    for c in candidates.into_iter().flatten() {
        let t = Tier::parse(c);
        if t.is_paid() {
            return Some(t);
        }
    }
    None
}

/// Map a parsed event to a tier change, or `None` if the event is irrelevant/incomplete.
pub fn tier_change(event: &Value) -> Option<TierChange> {
    let event_type = event.get("type")?.as_str()?.to_string();
    let obj = event.get("data")?.get("object")?;
    let key_prefix = str_at(obj, &["client_reference_id"])
        .or_else(|| str_at(obj, &["metadata", "key_prefix"]))?
        .to_string();
    let tier = match event_type.as_str() {
        "checkout.session.completed" => tier_from_object(obj)?,
        "customer.subscription.updated" => {
            let status = str_at(obj, &["status"]).unwrap_or("active");
            if matches!(status, "canceled" | "unpaid" | "incomplete_expired")
                || obj.get("cancel_at_period_end") == Some(&Value::Bool(true))
                    && status == "canceled"
            {
                Tier::Free
            } else {
                tier_from_object(obj)?
            }
        }
        "customer.subscription.deleted" => Tier::Free,
        _ => return None,
    };
    Some(TierChange {
        key_prefix,
        tier,
        event_type,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const SECRET: &str = "whsec_test_synthetic_secret";

    #[test]
    fn signature_roundtrip_and_failures() {
        let payload = br#"{"id":"evt_1","type":"checkout.session.completed"}"#;
        let now = 1_700_000_000u64;
        let sig = sign(SECRET, now, payload);
        let header = format!("t={now},v1={sig}");
        assert_eq!(verify(SECRET, &header, payload, now, 300), Ok(()));
        assert_eq!(verify(SECRET, &header, payload, now + 10, 300), Ok(()));
        assert_eq!(
            verify(SECRET, &header, payload, now + 301, 300),
            Err(StripeError::Expired)
        );
        assert_eq!(
            verify("other", &header, payload, now, 300),
            Err(StripeError::Mismatch)
        );
        assert_eq!(
            verify(SECRET, &header, b"tampered", now, 300),
            Err(StripeError::Mismatch)
        );
        assert_eq!(
            verify(SECRET, "v1=abc", payload, now, 300),
            Err(StripeError::Malformed)
        );
        // multiple v1 entries (key rotation): any match is accepted
        let header2 = format!("t={now},v1=deadbeef,v1={sig}");
        assert_eq!(verify(SECRET, &header2, payload, now, 300), Ok(()));
    }

    #[test]
    fn events_map_to_tiers() {
        let checkout = serde_json::json!({
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": "abc123def456", "metadata": {"tier": "pro"}}}
        });
        assert_eq!(
            tier_change(&checkout),
            Some(TierChange {
                key_prefix: "abc123def456".into(),
                tier: Tier::Pro,
                event_type: "checkout.session.completed".into()
            })
        );
        let upd = serde_json::json!({
            "type": "customer.subscription.updated",
            "data": {"object": {"status": "active", "metadata": {"key_prefix": "abc123def456"},
                "items": {"data": [{"price": {"lookup_key": "partner"}}]}}}
        });
        assert_eq!(tier_change(&upd).unwrap().tier, Tier::Partner);
        let del = serde_json::json!({
            "type": "customer.subscription.deleted",
            "data": {"object": {"metadata": {"key_prefix": "abc123def456"}}}
        });
        assert_eq!(tier_change(&del).unwrap().tier, Tier::Free);
        let cancelled = serde_json::json!({
            "type": "customer.subscription.updated",
            "data": {"object": {"status": "canceled", "metadata": {"key_prefix": "abc123def456"},
                "items": {"data": [{"price": {"lookup_key": "pro"}}]}}}
        });
        assert_eq!(tier_change(&cancelled).unwrap().tier, Tier::Free);
        let other = serde_json::json!({"type": "invoice.paid", "data": {"object": {}}});
        assert!(tier_change(&other).is_none());
        // unknown lookup_key never upgrades
        let weird = serde_json::json!({
            "type": "checkout.session.completed",
            "data": {"object": {"client_reference_id": "abc", "metadata": {"tier": "gold"}}}
        });
        assert!(tier_change(&weird).is_none());
    }
}
