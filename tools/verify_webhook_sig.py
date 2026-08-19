"""Verify an FX Regime Radar alert signature — the 10-line HMAC client.

Usage: verify_webhook_sig.py <secret> <X-FXRadar-Timestamp> <X-FXRadar-Signature> < body.json
Exit 0 = genuine, 1 = tampered / wrong secret.
Signature = "sha256=" + hex(HMAC-SHA256(secret, f"{timestamp}.{raw body}")).
"""

import hashlib
import hmac
import sys

secret, ts, sig = sys.argv[1], sys.argv[2], sys.argv[3]
body = sys.stdin.buffer.read()
mac = hmac.new(secret.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
ok = hmac.compare_digest("sha256=" + mac, sig)
print("OK genuine" if ok else "FAIL signature mismatch")
sys.exit(0 if ok else 1)
