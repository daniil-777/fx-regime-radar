# Evaluation snapshot 2026-08-23

Immutable. Every eval run reads this directory and never `data/`, so a result means the
same thing next week. Rebuild only when you intend to re-baseline — see
`docs/eval_process.md`, which requires a fresh baseline whenever a pinned field changes.

- built: `2026-08-23T08:31:17Z`
- git SHA: `3c88ba5a3e4824e1634dd1401fa073e499e6299c`
- data through: `2026-08-20`
- registry version: `3.0.0`
- markets in pack: 3 majors + 23 across all boards
- trim window: last 800 days for parquet frames

## Files and hashes

| file | sha256 |
|---|---|
| `config/visual_registry.yaml` | `123c54b0bf923e437b5789459f3356f34feab6d32da18e6fe4abf0bc1ff1e3f4` |
| `data/avatar_context.json` | `d087dd2c5802fe00e21a5f1124caf976e30b3b0d5951b466287e7d87c74ec92b` |
| `data/conformal_coverage.json` | `7b0809e0de7ec0c45057ac08bfd1bc698db5b064354b2ca5dd4ecae6863882c4` |
| `data/decision_table.json` | `0b3b2822ebc4c6651102ba2d371f6c8a05c27230a91e55d9b67419a325b9c6ab` |
| `data/events.csv` | `bf7efba3a725d9a2db7c7f064bf09e1d5b41a442f3234d2ea4194a99ffc4e382` |
| `data/features.parquet` | `9108584a8e651ff00e2c418b1f751488cae8dcbeb95c8f6ee654741cfb89d907` |
| `data/ledger.parquet` | `3e617c3bd2b5d16af71223fa98d503bf1b7ea7ea2a8d5a0fed889401fa2c2464` |
| `data/live_record.json` | `57c2b60afde9760898801c4992adf28a00a80c0ba70739e27696439718cb56cc` |
| `data/regimes.parquet` | `7e8c9090313c8ab6a31ea0f1b040f98a41cf2e97d76ecc04fd2bbe60c4760107` |
| `data/status.json` | `2efca55eb93c762e5fd78187630a2ea9e37244a3cdb548a45b27915904b82c37` |
| `data/storm_replays.json` | `8ca211abb1642c15956af6ba8170d9830441efb47bd7fbe63d74050adf22a2d9` |
| `data/treasury_risk.json` | `892a7b051354b3b1dbd7e205178efc6672fcb8ee974c8391abebe057ede47ffc` |
| `data/visual_boards.json` | `921ce2ff6a7a4af16851931b8dac1bb2f0c1394c5183828533cd6caf09eafb9d` |
| `data/visual_index.json` | `3bfc5c5b120af64eec2394ae1a505c6aeaca25220645347aa342e05e2cdf9843` |
| `docs/avatar_knowledge.md` | `9ae9ec62a76eb0f6bf72a25cd0c8d81a3609e2b6fdb24384af09bf57ba506f21` |
