"""Central-bank statement fetcher (phase 29, part A) — official English texts, nothing else.

Four sources, four document types, all free, timestamped and never revised:

* FOMC  — "Federal Reserve issues FOMC statement" press releases (federalreserve.gov)
* ECB   — "Monetary policy decisions" press releases (ecb.europa.eu)
* SNB   — quarterly "Monetary policy assessment" press releases (snb.ch)
* BOE   — the "Monetary Policy Summary" (not the minutes) of each MPC meeting (bankofengland.co.uk)

Every document is stored once under data/cb/<BANK>_<YYYY-MM-DD>.json with the bank, type, URL,
publication timestamp at the bank's documented FIXED release time, fetch time, the extracted text
and its sha256. Dedup is by (bank, date); a file on disk is never re-fetched, so the CLI is
idempotent and cheap to re-run. The fetch loop sleeps one second between requests and sends an
identifying User-Agent. HTML is turned into text with the standard-library html.parser — no new
dependencies.

No news sites, no speeches, no minutes, no third-party mirrors — ever (phase-29 "do not").
"""

from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import logging
import re
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from fxradar import config

log = logging.getLogger(__name__)

# Phase-20 deploy date: the first day the live ledger recorded a forecast
# (data/live_record.json "since"). Everything published before it is HISTORY and may only be
# touched by the frozen word lists (cb_lexicon); FinBERT / LLM scoring is refused for it.
DEPLOY_DATE = date(2026, 8, 17)

BANKS: tuple[str, ...] = ("FOMC", "ECB", "SNB", "BOE")
DOC_TYPES: dict[str, str] = {
    "FOMC": "fomc_statement",
    "ECB": "monetary_policy_decisions",
    "SNB": "monetary_policy_assessment",
    "BOE": "monetary_policy_summary",
}
# Documented fixed publication times (local wall clock, IANA zone). Unscheduled releases
# (e.g. SNB 2015-01-15 10:30 CET) are stamped with the scheduled time — every such case is still
# before the 17:00 New York FX close, so the trading-day assignment is unaffected.
PUBLICATION_TIMES: dict[str, tuple[str, str]] = {
    "FOMC": ("14:00", "America/New_York"),
    "ECB": ("14:15", "Europe/Berlin"),
    "SNB": ("09:30", "Europe/Zurich"),
    "BOE": ("12:00", "Europe/London"),
}

CB_DIR = config.DATA_DIR / "cb"
INDEX_PATH = CB_DIR / "index.json"
USER_AGENT = "fx-regime-radar/2.x (educational research; github.com/OWNER/REPO)"
SLEEP_S = 1.0
TIMEOUT_S = 30

FED_BASE = "https://www.federalreserve.gov"
FED_CALENDAR = f"{FED_BASE}/monetarypolicy/fomccalendars.htm"
FED_HISTORICAL = f"{FED_BASE}/monetarypolicy/fomchistorical{{year}}.htm"
ECB_BASE = "https://www.ecb.europa.eu"
ECB_YEAR_INDEX = f"{ECB_BASE}/press/govcdec/mopo/{{year}}/html/index_include.en.html"
SNB_BASE = "https://www.snb.ch"
SNB_DECISIONS = f"{SNB_BASE}/en/the-snb/mandates-goals/monetary-policy/decisions"
BOE_BASE = "https://www.bankofengland.co.uk"
BOE_MONTH = f"{BOE_BASE}/monetary-policy-summary-and-minutes/{{year}}/{{month}}-{{year}}"


# --------------------------------------------------------------------------------------
# HTML -> paragraphs (stdlib only)
# --------------------------------------------------------------------------------------
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "li"}
_SKIP_TAGS = {"script", "style", "nav", "header", "footer", "noscript"}


class _ParagraphParser(HTMLParser):
    """Collects (tag, text) for every p/h1-h4/li block outside script/style/nav/header/footer."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._cur: list[str] | None = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag in _BLOCK_TAGS:
            self._cur = []
        if tag == "br" and self._cur is not None:
            self._cur.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        if tag in _BLOCK_TAGS and self._cur is not None:
            text = re.sub(r"[^\S\n]+", " ", " ".join(self._cur))
            text = re.sub(r" *\n[ \n]*", "\n", text).strip()
            if text:
                self.blocks.append((tag, text))
            self._cur = None

    def handle_data(self, data: str) -> None:
        if self._skip == 0 and self._cur is not None:
            self._cur.append(data)


def html_to_blocks(html: str) -> list[tuple[str, str]]:
    """(tag, text) blocks in document order — the raw material for `extract_statement`."""
    parser = _ParagraphParser()
    parser.feed(html)
    parser.close()
    return parser.blocks


def page_title(html: str) -> str:
    """Text of the first <h1> (empty string if none)."""
    for tag, text in html_to_blocks(html):
        if tag == "h1":
            return text
    return ""


def _window(
    blocks: list[tuple[str, str]],
    start: Callable[[str, str], bool],
    stop: Callable[[str, str], bool],
) -> list[str]:
    """Paragraph texts strictly after the first block matching `start`, up to the first `stop`."""
    out: list[str] = []
    inside = False
    for tag, text in blocks:
        if not inside:
            inside = start(tag, text)
            continue
        if stop(tag, text):
            break
        if tag == "p":
            out.append(text)
    return out


def extract_statement(bank: str, html: str) -> str:
    """The statement body as plain text (paragraphs joined by blank lines), bank-specific window.

    FOMC: after the "FOMC statement" heading, until the media-inquiries / implementation note.
    ECB:  after the "Monetary policy decisions" heading, until "Related topics".
    SNB:  after the "Monetary policy assessment" heading, until the download box.
    BOE:  the "Monetary Policy Summary" section only — the minutes are NOT taken.
    Returns "" when the expected markers are missing (caller logs and skips).
    """
    blocks = html_to_blocks(html)
    low = lambda s: s.lower()  # noqa: E731
    if bank == "FOMC":
        paras = _window(
            blocks,
            start=lambda t, s: t in {"h1", "h2", "h3"} and "fomc statement" in low(s),
            stop=lambda t, s: low(s).startswith("for media inquiries")
            or low(s).startswith("implementation note")
            or low(s).startswith("last update"),
        )
    elif bank == "ECB":
        paras = _window(
            blocks,
            start=lambda t, s: t == "h1" and "monetary policy decisions" in low(s),
            stop=lambda t, s: t in {"h2", "h3", "h4"} and "related topics" in low(s),
        )
        paras = [p for p in paras if p.strip("* ") and not _is_date_line(p)]
    elif bank == "SNB":
        paras = _window(
            blocks,
            start=lambda t, s: t == "h1" and "monetary policy" in low(s),
            stop=lambda t, s: (t in {"h2", "h3"} and "download" in low(s))
            or low(s).startswith("your settings"),
        )
    elif bank == "BOE":
        paras = _window(
            blocks,
            start=lambda t, s: t in {"h1", "h2"} and low(s).startswith("monetary policy summary"),
            stop=lambda t, s: t in {"h1", "h2"}
            and ("minutes of the monetary policy committee" in low(s) or low(s) == "minutes"),
        )
        if not paras:  # 2020-21 layout: no heading; consecutive <p> (or one <p> with <br>)
            for j, (tag, text) in enumerate(blocks):
                if tag == "p" and _BOE_SUMMARY_START.match(text):
                    run = []
                    for tag2, text2 in blocks[j:]:
                        if tag2 != "p" or text2.lower().startswith("back to top"):
                            break
                        run.extend(x.strip() for x in text2.split("\n") if x.strip())
                    paras = run
                    break
    else:
        raise ValueError(f"unknown bank {bank!r}")
    return "\n\n".join(paras).strip()


_DATE_LINE = re.compile(r"^\d{1,2} [A-Z][a-z]+ \d{4}$")
_BOE_SUMMARY_START = re.compile(
    r"^The (Bank of England.s )?Monetary Policy Committee \(MPC\) sets monetary policy"
)


def _is_date_line(text: str) -> bool:
    return bool(_DATE_LINE.match(text.strip()))


# --------------------------------------------------------------------------------------
# documents
# --------------------------------------------------------------------------------------
def published_at(bank: str, day: date) -> datetime:
    """Timezone-aware publication timestamp at the bank's documented fixed release time."""
    hhmm, zone = PUBLICATION_TIMES[bank]
    hour, minute = (int(x) for x in hhmm.split(":"))
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=ZoneInfo(zone))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_doc(bank: str, day: date, url: str, text: str, fetched_at: datetime | None = None) -> dict:
    """The on-disk document record (contract of data/cb/<BANK>_<date>.json)."""
    fetched = fetched_at or datetime.now(UTC)
    return {
        "bank": bank,
        "type": DOC_TYPES[bank],
        "url": url,
        "published_at": published_at(bank, day).isoformat(),
        "fetched_at": fetched.replace(microsecond=0).isoformat(),
        "text": text,
        "sha256": sha256_text(text),
    }


def doc_path(bank: str, day: date, cb_dir: Path = CB_DIR) -> Path:
    return cb_dir / f"{bank}_{day.isoformat()}.json"


def doc_date(doc: dict) -> date:
    """Calendar date of publication in the bank's local zone (the date in the file name)."""
    return datetime.fromisoformat(doc["published_at"]).date()


def save_doc(doc: dict, cb_dir: Path = CB_DIR) -> Path:
    cb_dir.mkdir(parents=True, exist_ok=True)
    path = doc_path(doc["bank"], doc_date(doc), cb_dir)
    path.write_text(json.dumps(doc, indent=1, ensure_ascii=False), encoding="utf-8")
    return path


def load_docs(cb_dir: Path = CB_DIR) -> list[dict]:
    """All stored documents, sorted by (published_at, bank). Empty list if the folder is absent."""
    if not cb_dir.exists():
        return []
    docs = []
    for path in sorted(cb_dir.glob("*_????-??-??.json")):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log.warning("skipping unreadable %s", path)
            continue
        if doc.get("bank") in BANKS and doc.get("text"):
            docs.append(doc)
    docs.sort(key=lambda d: (d["published_at"], d["bank"]))
    return docs


def write_index(docs: list[dict], path: Path = INDEX_PATH) -> dict:
    """data/cb/index.json — a small catalogue (no text) so the app never has to glob the folder."""
    per_bank = {b: sum(d["bank"] == b for d in docs) for b in BANKS}
    index = {
        "generated_at_utc": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "n_docs": len(docs),
        "per_bank": per_bank,
        "first": docs[0]["published_at"] if docs else None,
        "last": docs[-1]["published_at"] if docs else None,
        "docs": [
            {k: d[k] for k in ("bank", "type", "url", "published_at", "sha256")} for d in docs
        ],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(index, indent=1), encoding="utf-8")
    return index


# --------------------------------------------------------------------------------------
# listing (one function per bank) — each returns [(date, url)] of candidate statements
# --------------------------------------------------------------------------------------
Getter = Callable[[str], str | None]


def _http_get(url: str) -> str | None:
    """GET with a polite UA; None on any failure (the callers log and move on)."""
    import requests

    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        log.warning("GET %s failed: %s", url, type(exc).__name__)
        return None
    if r.status_code != 200:
        log.info("GET %s -> %s", url, r.status_code)
        return None
    return r.content.decode("utf-8", errors="replace")  # all four sites serve UTF-8


_FED_LINK = re.compile(r'href="(/newsevents/pressreleases/monetary(\d{8})a\.htm)"')
_ECB_LINK = re.compile(r'href="(/press/pr/date/\d{4}/html/ecb\.mp(\d{6})~[0-9a-f]+\.en\.html)"')
_SNB_LINK = re.compile(
    r'href="(/en/publications/communication/press-releases(?:-restricted|/\d{4})/pre_(\d{8})[^"]*)"'
)


def list_fomc(since_year: int, get: Getter = _http_get, sleep: float = SLEEP_S) -> list:
    """FOMC statement links from the calendar page (recent years) + historical year pages."""
    found: dict[date, str] = {}
    html = get(FED_CALENDAR) or ""
    for path, ymd in _FED_LINK.findall(html):
        found[datetime.strptime(ymd, "%Y%m%d").date()] = FED_BASE + path
    covered_from = min(found) if found else None
    year = since_year
    while covered_from is None or year < covered_from.year:
        if year > date.today().year:
            break
        time.sleep(sleep)
        html = get(FED_HISTORICAL.format(year=year)) or ""
        for path, ymd in _FED_LINK.findall(html):
            found[datetime.strptime(ymd, "%Y%m%d").date()] = FED_BASE + path
        year += 1
    return sorted((d, u) for d, u in found.items() if d.year >= since_year)


def list_ecb(since_year: int, get: Getter = _http_get, sleep: float = SLEEP_S) -> list:
    """ECB 'Monetary policy decisions' press releases from the per-year index includes."""
    found: dict[date, str] = {}
    for year in range(since_year, date.today().year + 1):
        html = get(ECB_YEAR_INDEX.format(year=year)) or ""
        for path, ymd in _ECB_LINK.findall(html):
            found[datetime.strptime(ymd, "%y%m%d").date()] = ECB_BASE + path
        time.sleep(sleep)
    return sorted(found.items())


def list_snb(since_year: int, get: Getter = _http_get, sleep: float = SLEEP_S) -> list:
    """SNB monetary policy decisions: the bank's own decisions page lists every press release."""
    html = get(SNB_DECISIONS) or ""
    found: dict[date, str] = {}
    for path, ymd in _SNB_LINK.findall(html):
        d = datetime.strptime(ymd, "%Y%m%d").date()
        if d.year >= since_year:
            found[d] = SNB_BASE + path
    return sorted(found.items())


def list_boe(since_year: int, get: Getter = _http_get, sleep: float = SLEEP_S) -> list:
    """BoE Monetary Policy Summary pages live at .../<year>/<month>-<year>; probe each month."""
    found: list[tuple[date, str]] = []
    today = date.today()
    for year in range(since_year, today.year + 1):
        for m in range(1, 13):
            if (year, m) > (today.year, today.month):
                break
            url = BOE_MONTH.format(year=year, month=calendar.month_name[m].lower())
            html = get(url)
            time.sleep(sleep)
            if not html:
                continue
            day = _boe_publication_date(html, year, m)
            if day is not None:
                found.append((day, url))
    return sorted(found)


_BOE_PUBLISHED = re.compile(r"Published on\s+(\d{1,2} [A-Z][a-z]+ \d{4})")
_BOE_MEETING = re.compile(r"meeting ending on (\d{1,2} [A-Z][a-z]+ \d{4})")


def _boe_publication_date(html: str, year: int, month: int) -> date | None:
    """The page's 'Published on <date>' stamp; else the MPC meeting-end date + 1 day (the
    summary is released at 12:00 London on the day after the meeting ends)."""
    m = _BOE_PUBLISHED.search(html)
    if m:
        try:
            return datetime.strptime(m.group(1), "%d %B %Y").date()
        except ValueError:
            pass
    for _tag, text in html_to_blocks(html):
        m = _BOE_MEETING.search(text)
        if m:
            try:
                return datetime.strptime(m.group(1), "%d %B %Y").date() + timedelta(days=1)
            except ValueError:
                continue
    return date(year, month, 1)


LISTERS: dict[str, Callable[..., list]] = {
    "FOMC": list_fomc,
    "ECB": list_ecb,
    "SNB": list_snb,
    "BOE": list_boe,
}


# --------------------------------------------------------------------------------------
# fetch loop
# --------------------------------------------------------------------------------------
_SNB_PDF = re.compile(r'href="(/public/asset/en/[^"]*pre_\d{8}[^"]*\.pdf)"')


def _http_get_bytes(url: str) -> bytes | None:
    import requests

    try:
        r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_S)
    except requests.RequestException as exc:
        log.warning("GET %s failed: %s", url, type(exc).__name__)
        return None
    return r.content if r.status_code == 200 else None


def pdf_to_text(data: bytes) -> str:
    """Text of a PDF via pypdf (optional extra in requirements-nlp.txt); "" if unavailable."""
    try:
        import io

        from pypdf import PdfReader  # optional: only the SNB's pre-2025 assessments need it
    except ImportError:
        log.info("pypdf not installed — SNB PDF-only assessments are skipped")
        return ""
    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [(page.extract_text() or "") for page in reader.pages]
    except Exception as exc:  # corrupt/encrypted file: skip, never crash the pipeline
        log.warning("pdf parse failed: %s", type(exc).__name__)
        return ""
    return "\n".join(pages)


def _snb_statement_from_pdf(text: str) -> str:
    """Body of an SNB assessment PDF: drop the letterhead, stop at the page-footer boilerplate,
    glue the hard-wrapped lines back into paragraphs."""
    lines = [ln.strip() for ln in text.splitlines()]
    body: list[str] = []
    started = False
    for ln in lines:
        low_ln = ln.lower()
        if not started:
            if low_ln.startswith("monetary policy assessment") or "swiss national bank" in low_ln:
                started = True
            continue
        if (
            low_ln.startswith("page ")
            or low_ln.startswith("communications")
            or low_ln.startswith("p.o. box")
        ):
            continue
        body.append(ln)
    joined = re.sub(r"-\n(?=[a-z])", "", "\n".join(body))  # re-join hyphenated line breaks
    paras = re.split(r"\n\s*\n", joined)
    paras = [re.sub(r"\s+", " ", p).strip() for p in paras]
    return "\n\n".join(p for p in paras if len(p) > 40)


def fetch_bank(
    bank: str,
    since_year: int,
    cb_dir: Path = CB_DIR,
    get: Getter = _http_get,
    sleep: float = SLEEP_S,
) -> dict:
    """List + fetch + extract + save every missing statement of one bank. Never raises."""
    summary = {"bank": bank, "listed": 0, "fetched": 0, "skipped": 0, "failed": 0}
    try:
        candidates = LISTERS[bank](since_year, get=get, sleep=sleep)
    except Exception as exc:  # listing is network code: log and move on
        log.warning("%s: listing failed: %s", bank, type(exc).__name__)
        return summary
    summary["listed"] = len(candidates)
    for day, url in candidates:
        if doc_path(bank, day, cb_dir).exists():
            summary["skipped"] += 1
            continue
        time.sleep(sleep)
        html = get(url)
        if not html:
            summary["failed"] += 1
            continue
        if bank == "SNB" and "monetary policy assessment" not in page_title(html).lower():
            log.info(
                "SNB %s: not a monetary policy assessment (%s) — skipped", day, page_title(html)
            )
            summary["skipped"] += 1
            continue
        text = extract_statement(bank, html)
        if bank == "SNB" and len(text) < 200:  # pre-2025 layout: PDF only
            m = _SNB_PDF.search(html)
            data = _http_get_bytes(SNB_BASE + m.group(1)) if m else None
            text = _snb_statement_from_pdf(pdf_to_text(data)) if data else ""
        if len(text) < 200:  # a statement is never this brief: wrong page or layout change
            log.warning("%s %s: no statement text found at %s", bank, day, url)
            summary["failed"] += 1
            continue
        save_doc(make_doc(bank, day, url, text), cb_dir)
        summary["fetched"] += 1
        log.info("%s %s fetched (%d chars)", bank, day, len(text))
    return summary


def fetch_all(
    since_year: int,
    banks: tuple[str, ...] = BANKS,
    cb_dir: Path = CB_DIR,
    get: Getter = _http_get,
    sleep: float = SLEEP_S,
) -> list[dict]:
    """Fetch all banks, then rewrite data/cb/index.json. Returns the per-bank summaries."""
    summaries = [fetch_bank(b, since_year, cb_dir, get, sleep) for b in banks]
    write_index(load_docs(cb_dir), cb_dir / "index.json")
    return summaries


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    ap = argparse.ArgumentParser(description="fetch official central-bank statements into data/cb/")
    ap.add_argument("--backfill", action="store_true", help="fetch every statement since --since")
    ap.add_argument("--since", type=int, default=date.today().year, help="first year (e.g. 2020)")
    ap.add_argument("--banks", nargs="*", default=list(BANKS), choices=BANKS)
    args = ap.parse_args()
    since = args.since if args.backfill else date.today().year
    summaries = fetch_all(since, tuple(args.banks))
    for s in summaries:
        print(
            f"{s['bank']:<5} listed={s['listed']:<3} fetched={s['fetched']:<3} "
            f"already={s['skipped']:<3} failed={s['failed']}"
        )
    docs = load_docs()
    print(f"{len(docs)} documents on disk -> {INDEX_PATH}")


if __name__ == "__main__":
    main()
