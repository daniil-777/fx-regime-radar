//! Per-key token bucket. Each key gets `capacity` tokens that refill continuously at
//! `capacity / 60` per second (i.e. `capacity` requests per minute, with bursts up to `capacity`).

use std::collections::HashMap;
use std::sync::Mutex;
use std::time::Instant;

struct Bucket {
    tokens: f64,
    last: Instant,
}

pub struct RateLimiter {
    capacity: f64,
    refill_per_sec: f64,
    buckets: Mutex<HashMap<String, Bucket>>,
}

impl RateLimiter {
    /// `per_minute` requests per minute per key (burst = the same number).
    pub fn new(per_minute: u32) -> RateLimiter {
        let cap = per_minute.max(1) as f64;
        RateLimiter {
            capacity: cap,
            refill_per_sec: cap / 60.0,
            buckets: Mutex::new(HashMap::new()),
        }
    }

    pub fn per_minute(&self) -> u32 {
        self.capacity as u32
    }

    /// `Ok(remaining)` if the request is admitted, `Err(retry_after_secs)` otherwise.
    pub fn check(&self, key: &str) -> Result<u32, u64> {
        self.check_at(key, Instant::now())
    }

    pub fn check_at(&self, key: &str, now: Instant) -> Result<u32, u64> {
        let mut map = match self.buckets.lock() {
            Ok(m) => m,
            Err(p) => p.into_inner(),
        };
        let b = map.entry(key.to_string()).or_insert(Bucket {
            tokens: self.capacity,
            last: now,
        });
        let elapsed = now.saturating_duration_since(b.last).as_secs_f64();
        b.tokens = (b.tokens + elapsed * self.refill_per_sec).min(self.capacity);
        b.last = now;
        if b.tokens >= 1.0 {
            b.tokens -= 1.0;
            Ok(b.tokens.floor() as u32)
        } else {
            let need = 1.0 - b.tokens;
            Err((need / self.refill_per_sec).ceil().max(1.0) as u64)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::time::Duration;

    #[test]
    fn bucket_blocks_after_capacity_and_refills() {
        let rl = RateLimiter::new(5);
        let t0 = Instant::now();
        for _ in 0..5 {
            assert!(rl.check_at("k", t0).is_ok());
        }
        let retry = rl.check_at("k", t0).unwrap_err();
        assert!(retry >= 1);
        // 12 s later one token has refilled (5/min = one per 12 s)
        assert!(rl.check_at("k", t0 + Duration::from_secs(12)).is_ok());
        // other keys are independent
        assert!(rl.check_at("other", t0).is_ok());
    }
}
