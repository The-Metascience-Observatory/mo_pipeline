#!/usr/bin/env python3
"""Read-only audit of original-study DOIs in the published replications database.

The published database was produced by pipeline versions that kept a DOI the
model recalled from memory (fixed in prompt 8.11 / extract.enrich_metadata on
2026-10-16). This audit resolves every distinct `original_url` DOI in the newest
`replications_database_*.csv` (config.latest_replications_db -- never written to,
CLAUDE.md invariant 2) and flags rows whose DOI

  nonexistent     is registered nowhere (Crossref 404 and the doi.org handle
                  system has no record), or
  title_mismatch  is registered to a work whose title does not match the row's
                  original_title (the shared title-similarity helper, as the
                  extractor uses it),

and proposes a replacement DOI from a title lookup. Corrections go through the
manual ingest in the website repo, not from here.

    python benchmarking/audit_published_dois.py [--workers 8] [--limit N] [--no-proposals]

Output: benchmarking/results/<date>_published_doi_audit/{suspect_rows.csv,summary.json}.
Crossref answers are cached in benchmarking/cache/published_doi_audit.json.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parent))

from mo_pipeline import config  # noqa: E402
from mo_pipeline.shared.fetch_metadata_from_title import (  # noqa: E402
    _title_similarity, fetch_metadata_from_title)

MAILTO = "dan@metascienceobservatory.org"
CACHE = config.BENCH_CACHE_DIR / "published_doi_audit.json"
# Stop only at whitespace and quotes: old Wiley SICI DOIs contain < > ; ( ),
# e.g. 10.1002/(sici)1099-0771(199806)11:2<107::aid-bdm292>3.0.co;2-y.
_DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"']+")
_lock = threading.Lock()


def bare_doi(url: str) -> str | None:
    m = _DOI_RE.search(urllib.parse.unquote(url or ""))
    if not m:
        return None
    d = m.group(0).rstrip(".,;]")
    while d.endswith(")") and d.count(")") > d.count("("):   # keep "(2001/052)"
        d = d[:-1].rstrip(".,;]")
    return d.lower()


def _get_json(url: str) -> tuple[int, dict | None]:
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.status, json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, None
            time.sleep(2 + 3 * attempt)
        except Exception:  # noqa: BLE001 - network: retry
            time.sleep(2 + 3 * attempt)
    return 0, None


def _plain(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).split())


def titles_agree(row_title: str, registered: str) -> bool:
    """The shared helper on punctuation-folded titles (hyphen vs em dash, stray
    line breaks), also accepting a registered main title that the row's title
    starts with (registries often drop the subtitle)."""
    a, b = _plain(row_title), _plain(registered)
    if not a or not b:
        return True
    if a.startswith(b) or b.startswith(a):
        return True
    ta, tb = set(a.split()), set(b.split())
    if min(len(ta), len(tb)) >= 4 and len(ta & tb) / min(len(ta), len(tb)) >= 0.9:
        return True
    return _title_similarity(a, b, threshold=0.55) > 0.0


def resolve(doi: str) -> dict:
    """{status: crossref|registered_elsewhere|nonexistent|lookup_failed, title, year}."""
    # Encode the whole DOI: a "/" inside the suffix, e.g. 10.1044/1092-4388(2001/052),
    # otherwise reaches the handle API as a path separator and reads as unregistered.
    enc = urllib.parse.quote(doi, safe="")
    status, body = _get_json(f"https://api.crossref.org/works/{enc}?mailto={MAILTO}")
    if status == 200 and body:
        m = body["message"]
        return {"status": "crossref", "title": (m.get("title") or [""])[0],
                "year": ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0]}
    if status == 404:
        # Not Crossref: DataCite (OSF, Zenodo), mEDRA, ... or not registered at all.
        prefix, _, suffix = doi.partition("/")
        hs, hb = _get_json(f"https://doi.org/api/handles/{prefix}/{urllib.parse.quote(suffix, safe='')}")
        if hs == 200 and hb and hb.get("responseCode") == 1:
            return {"status": "registered_elsewhere", "title": "", "year": None}
        if hs in (200, 404):
            return {"status": "nonexistent", "title": "", "year": None}
    return {"status": "lookup_failed", "title": "", "year": None}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--limit", type=int, default=None, help="audit only the first N distinct DOIs")
    ap.add_argument("--no-proposals", action="store_true", help="skip the title lookup for suspects")
    args = ap.parse_args()

    db = config.latest_replications_db()
    if not db or not db.exists():
        sys.exit("ERROR: no published replications database resolves (config.latest_replications_db)")
    csv.field_size_limit(sys.maxsize)
    with open(db, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    dois = sorted({d for r in rows if (d := bare_doi(r.get("original_url")))})[: args.limit]
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    # A "nonexistent" verdict is the one that matters, so it is always re-checked.
    todo = [d for d in dois if d not in cache or cache[d]["status"] in ("lookup_failed", "nonexistent")]
    print(f"{db.name}: {len(rows)} rows, {len(dois)} distinct original DOIs, {len(todo)} to resolve", flush=True)

    def one(d):
        res = resolve(d)
        with _lock:
            cache[d] = res
            if len(cache) % 200 == 0:
                CACHE.parent.mkdir(parents=True, exist_ok=True)
                CACHE.write_text(json.dumps(cache))
        return res

    with ThreadPoolExecutor(args.workers) as pool:
        for n, _ in enumerate(pool.map(one, todo), 1):
            if n % 500 == 0:
                print(f"  resolved {n}/{len(todo)}", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache))

    suspects, tally = [], Counter()
    audited = set(dois)
    for i, r in enumerate(rows):
        d = bare_doi(r.get("original_url"))
        if not d or d not in audited:
            continue
        res = cache.get(d, {"status": "lookup_failed"})
        tally[res["status"]] += 1
        issue = ""
        if res["status"] == "nonexistent":
            issue = "nonexistent"
        elif res["status"] == "crossref" and res["title"] and r.get("original_title") \
                and not titles_agree(r["original_title"], res["title"]):
            issue = "title_mismatch"
        if issue:
            tally["suspect:" + issue] += 1
            suspects.append({"row": i + 2, "replication_url": r.get("replication_url", ""),
                             "original_url": r.get("original_url", ""), "original_title": r.get("original_title", ""),
                             "original_authors": r.get("original_authors", ""), "original_year": r.get("original_year", ""),
                             "issue": issue, "registered_title": res.get("title", ""),
                             "registered_year": res.get("year") or "", "proposed_doi": "", "proposed_title": "",
                             "ai_version": r.get("ai_version", "")})

    if not args.no_proposals:
        def propose(s):
            try:
                meta = fetch_metadata_from_title(s["original_title"], authors=s["original_authors"],
                                                 year=s["original_year"])
            except Exception:  # noqa: BLE001 - best-effort
                return
            if meta and meta.get("doi") and meta.get("title") \
                    and titles_agree(s["original_title"], meta["title"]):
                if meta["doi"].lower() != bare_doi(s["original_url"]):
                    s["proposed_doi"], s["proposed_title"] = meta["doi"], meta["title"]
        unique = {}
        for s in suspects:                       # one lookup per distinct (title, DOI)
            unique.setdefault((s["original_title"], s["original_url"]), []).append(s)
        with ThreadPoolExecutor(min(args.workers, 6)) as pool:
            list(pool.map(lambda group: propose(group[0]), unique.values()))
        for group in unique.values():
            for s in group[1:]:
                s["proposed_doi"], s["proposed_title"] = group[0]["proposed_doi"], group[0]["proposed_title"]

    out = config.BENCHMARKING_DIR / "results" / f"{time.strftime('%Y-%m-%d')}_published_doi_audit"
    out.mkdir(parents=True, exist_ok=True)
    fields = list(suspects[0].keys()) if suspects else ["row"]
    with open(out / "suspect_rows.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fields)
        w.writeheader()
        w.writerows(suspects)
    summary = {"database": db.name, "rows": len(rows), "distinct_original_dois": len(dois),
               "rows_by_status": dict(tally),
               "suspect_rows": len(suspects),
               "suspect_distinct_dois": len({bare_doi(s["original_url"]) for s in suspects}),
               "with_proposal": sum(bool(s["proposed_doi"]) for s in suspects),
               "by_ai_version": dict(Counter(s["ai_version"] or "(blank)" for s in suspects))}
    (out / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    print(f"wrote {out}/")


if __name__ == "__main__":
    main()
