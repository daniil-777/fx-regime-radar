# Launch film — reference images for Veo 3.1

Styleframes in `docs/film/refs/`, generated from the real design tokens by `make_refs.py`
(re-run any time: `.venv/bin/python docs/film/make_refs.py`). They exist so Veo inherits the
product's exact palette — nimbus `#0E1420`, calm `#3ECF8E`, trend `#4DA3FF`, chop `#F5B942`,
crisis `#FF5C5C`, beacon teal `#7FD1C9` — instead of inventing its own teal-and-orange.

**Every frame is deliberately text-free** (the dashboards are pixelated + blurred until no word
survives). Never feed Veo a reference with legible text: it will try to reproduce it, garble it,
and break the film's one deliberate absence — all words and numbers are composited in post from
real app captures.

## How to attach them (Flow / Gemini API)

- **"Ingredients to Video"** accepts up to **3** reference images per clip — use them as style /
  object anchors for live-action shots. Two strong references beat three competing ones.
- **"Frames to Video"** uses an image as the **literal first frame** — use it for the abstract,
  product-owned shots (orb, radar, chain, end card) so the clip *starts on brand* and animates from
  there. Add the palette hexes to the text prompt as well; belt and braces.
- Vertical cutdown: use the `_916` frames — don't let Flow crop the 16:9 ones.

## Shot map

| shot | reference(s) | mode |
|---|---|---|
| 1 — Zurich blue hour | `ref_grade_card.png` | ingredient (grade only — let Veo shoot Zurich) |
| 2 — the calm office | `ref_monitor_room.png` + `ref_grade_card.png` | ingredients |
| 3 — the barometer falls | `ref_grade_card.png` | ingredient (macro object is Veo's job; the card holds the slate/teal/amber grade) |
| 4 — storm front over the lake | `ref_grade_card.png` | ingredient |
| 5 — the radar sweep | `ref_radar_sweep.png` | **first frame** |
| 6 — the orb turns | `ref_orb_calm.png` (first frame) + `ref_orb_crisis.png` (ingredient: the destination look) | frames + ingredient |
| 7 — CRISIS lands | `ref_monitor_room_alt.png` + `ref_orb_crisis.png` (the coral wash) | ingredients |
| 8 — the alert fires | `ref_phone_alert.png` | ingredient (or first frame for a locked-off macro) |
| 9 — the treasurer acts | `ref_monitor_room.png` + `ref_orb_calm.png` (the calm the room resolves to) | ingredients |
| 10 — the sealed ledger | `ref_chain_seal.png` | **first frame** |
| 11 — end-card plate | `ref_endcard_plate.png` | **first frame** (hold; logo + tagline composited in post) |
| V1 — hook | `ref_v1_orb_916.png` | first frame |
| V2 — proof | `ref_v2_monitor_916.png` | ingredient |
| V3 — trust + CTA | `ref_v3_chain_916.png` | first frame |

## Rules that keep it professional

1. **Text-free in, text-free out.** The negative prompt already bans text; a text-free reference is
   the other half of that contract. All words (CALM, CRISIS, the CHF figure, the chain hash,
   "Don't trust us. Verify.") are composited in the edit from real app captures — that contrast
   between generated footage and pixel-sharp real UI is what reads as expensive.
2. **One palette, stated twice.** The references carry it visually; repeat the hexes in the prompt
   ("deep slate-navy #0E1420, emerald #3ECF8E, amber #F5B942, coral #FF5C5C, teal #7FD1C9").
3. **First-frame the product, ingredient the world.** Anything the product owns (orb, radar, chain,
   end card) starts from our pixels; anything cinematic (Zurich, lake, office, hands) only borrows
   our grade.
4. **Don't stack three similar refs** — one grade card + one subject reference per clip is the
   sweet spot; a third only if it adds a distinct object (e.g. the crisis orb as the colour
   destination in shots 6/7).
5. For the real-UI composites in post, use the **unblurred** captures:
   `docs/screenshots/overview_v3.png`, `proof.png`, `treasury.png`, `orb/orb_states.png`.
