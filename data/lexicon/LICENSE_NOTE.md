# Lexicon provenance and licence note (phase 29)

These word lists are the ONLY thing allowed to touch historical (pre-2026-08-17) central-bank
statements. They have no memory of any market outcome, so they are history-safe. Each file is
frozen: `hashes.json` records its sha256 and `tests/test_cb_index.py` asserts the hashes match.
Changing a list means bumping `LEXICON_VERSION` in `src/fxradar/cb_lexicon.py`, re-recording the
hashes and re-running the event study — it is a model change, not an edit.

## lm_uncertainty.txt — Loughran-McDonald "Uncertainty" word list (297 words)

* Source: Loughran-McDonald Master Dictionary 1993-2025 (`Loughran-McDonald_MasterDictionary_1993-2025.csv`),
  downloaded 2026-08-19 from https://sraf.nd.edu/loughranmcdonald-master-dictionary/ (Google Drive
  link on that page). Master-file sha256: `e2d1328682bab7d2187684fb9f5420bb730401c9eefc00daf835edd203f4859d`.
  The list here is every word whose `Uncertainty` column is non-zero, lower-cased, sorted.
* Citation: Loughran, T. and McDonald, B. (2011), "When Is a Liability Not a Liability? Textual
  Analysis, Dictionaries, and 10-Ks", Journal of Finance 66(1), 35-65.
* Licence: the authors make the dictionary available free of charge for academic and
  non-commercial research; commercial use requires a licence from the authors
  (loughranmcdonald@gmail.com). This repository is an educational, non-commercial project.
  The file is vendored unchanged in content (only the Uncertainty subset, lower-cased) so the
  scores are reproducible without a network.

## hawkish.txt / dovish.txt — monetary-policy tone lexicon (121 / 129 terms)

There is no Loughran-McDonald hawkish list. These two lists were compiled for this project from
the published central-bank communication dictionaries below, restricted to terms that are
unambiguous about the *policy stance* (tighter vs looser) or the *inflation / activity balance*
that drives it. Uni-, bi- and trigrams; lower-case; hyphens written as spaces. They are a
deliberately small, readable, frozen list — not a fitted model.

* Apel, M. and Blix Grimaldi, M. (2012/2014), "The Information Content of Central Bank Minutes",
  Sveriges Riksbank Working Paper 261 — the noun x adjective hawkish/dovish combinations
  (inflation/price/growth/demand/employment x high/strong/increasing vs low/weak/decreasing).
* Bennani, H. and Neuenkirch, M. (2017), "The (home) bias of European central bankers: new
  evidence based on speeches", Applied Economics 49(11) — hawkish/dovish keyword dictionary.
* Picault, M. and Renault, T. (2017), "Words are not all created equal: A new measure of ECB
  communication", Journal of International Money and Finance 79 — ECB field-specific lexicon.
* Gorodnichenko, Y., Pham, T. and Talavera, O. (2023), "The Voice of Monetary Policy",
  American Economic Review 113(2) — hawkish/dovish term families for FOMC communication.
* Tobback, E., Nardelli, S. and Martens, D. (2017), "Between hawks and doves: measuring central
  bank communication", ECB Working Paper 2085.
* SNB-specific terms (franc "highly valued", willingness to intervene, negative interest) follow
  the SNB's own standing phrasing in its monetary policy assessments.

Known limitation, on purpose: a word list cannot read negation or context ("will not tighten"
counts as hawkish). That is why the index is reported as a *tone surprise* against the bank's own
recent statements and evaluated with a placebo band, never as a trading signal.
