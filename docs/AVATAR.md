# The AI presenter — setup, policy, and what keeps it honest

Three layers behind a feature flag (`FXRADAR_AVATAR=on`, **off by default**):

| layer | what | where |
|---|---|---|
| MIND | `data/avatar_context.json` — today's regimes, risks, bands, sirens, consensus, events, treasury lights, ledger stats, drift flag, the pre-gated greeting, the refusal texts, the FAQ, and `allowed_numbers` (the closed set of numbers the presenter may speak). Rebuilt by the daily pipeline (`fxradar.avatar_context`). | Python |
| MOUTH | `POST /avatar/brain` — answers from the pack + `docs/avatar_knowledge.md` only. Gates, in order: topic guard (direction/advice → branded refusal) → direction-word lint → numeric grounding (every number must be in `allowed_numbers` or echoed from the question); one corrective regeneration, then the `not_in_pack` refusal. With `ANTHROPIC_API_KEY`: Haiku, ≤220 tokens, versioned system prompt `prompts/avatar_system_v1.txt`. Without: the keyless FAQ matcher (same gates). | Rust |
| FACE | `/avatar` widget (tokens only): vendor video over WebRTC when configured, else the DRAWN PRESENTER — a geometric bust in the token palette (blinking eyes, speaking mouth, teal headset, regime-coloured ring) + browser TTS — fully real-time with zero external services. The drawn face is deliberately non-photoreal (no likeness questions; the disclosure is still spoken first) and occupies exactly the slot the vendor video replaces. | static HTML |

## Environment

```
FXRADAR_AVATAR=on                    # master flag (off = every /avatar/* route is 503)
FXRADAR_AVATAR_VENDOR=local          # local | anam | heygen
FXRADAR_AVATAR_BRAIN_TOKEN=<secret>  # what the VENDOR presents to /avatar/brain
ANTHROPIC_API_KEY=<optional>         # LLM answers; without it the FAQ fallback answers
ANAM_API_KEY / HEYGEN_API_KEY        # only for their vendor modes (503 if unset)
FXRADAR_AVATAR_MAX_SESSIONS_MONTH=300
FXRADAR_AVATAR_MAX_MINUTES_MONTH=600
FXRADAR_AVATAR_DEV=1                 # DEV ONLY: session-token without an API key (local vendor)
FXRADAR_AVATAR_URL=https://host/avatar   # lets the Streamlit Briefing page embed the widget
```

## Turning on the real thing — three keys, each optional

| you add | you get | where |
|---|---|---|
| `ANTHROPIC_API_KEY` (console.anthropic.com) | open conversation on any topic — the model already knows the app via the context + knowledge packs; app numbers stay pack-grounded | env or `.streamlit/secrets.toml` |
| `ELEVENLABS_API_KEY` (elevenlabs.io — free tier) | the studio voice (Flash v2.5, ~75 ms) — the server only voices answers our gates produced (hash-checked) | env or secrets.toml |
| `ANAM_API_KEY` (anam.ai — free dev tier) | the photoreal face over WebRTC, speaking with the vendor's own voice — text still comes from OUR gated brain | env or secrets.toml |

`make avatar` picks all three up automatically and runs in OPEN mode: any topic is fair game; the
numeric-grounding gate switches to annotate-only (`open:ungrounded` badge instead of a block) —
but the direction and advice bans stay hard, always. Keyless, everything still runs: drawn face,
browser voice, gated FAQ.

## Vendors and likeness

Primary: Anam.ai (BYO-LLM — the vendor's face calls our `/avatar/brain`, so every sentence passes
our gates before their TTS; ElevenLabs Flash voice via their audio passthrough). Fallback: HeyGen
LiveAvatar (streaming token flow). **Likeness policy: a licensed stock avatar or the founder's own
consented scan only** — record the licence/consent reference here before enabling a vendor face:

- likeness licence/consent reference: _none yet — local disc face only_.

No GPU on the VM: faces render in the vendor cloud; our server only serves text and tokens.

## Privacy and review

Every Q/A is stored in `avatar_transcripts` (sqlite, server-side) with the gate decision and
latency; the widget says so visibly. Standing ops task: a human reads the week's transcripts every
Monday alongside the weekly report and files anything odd as an issue. Transcripts are used for
nothing else — no training, no marketing.

## Latency budget (question → first audio)

browser ASR ≈ 0 (on-device) · brain: keyless FAQ ≈ 1–5 ms measured / Haiku ≤220 tok ≈ 1.2–2.5 s ·
TTS: browser ≈ instant, ElevenLabs Flash ≈ 75 ms TTFB · vendor face + WebRTC ≈ 300–500 ms.
Target ≤ 3.5 s worst case on the LLM path; ≈ instant on the keyless path. **Measured** (release
binary, local, keyless FAQ path, 2026-08-20): question → gated answer 0–6 ms server-side; the
whole round trip is dominated by browser TTS startup.

## The async sibling

`scripts/render_briefing.py` (independent flag `FXRADAR_BRIEFING_MP4=on`) drafts the ~90-second
Monday briefing script from `template_narrate` output and, when `HEYGEN_API_KEY` is set, submits it
to the HeyGen video API; the MP4 is **human-reviewed before publish**, always. Without a key it
writes the reviewed-script text next to the weekly report and stops — honestly.

## What the presenter will never do

State or imply price direction · give personal advice · speak a number outside the packs ·
improvise methodology · appear on the Proof page (the ledger stays human-free) · autoplay sound ·
urge the user to keep talking.
