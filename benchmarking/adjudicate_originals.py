#!/usr/bin/env python3
"""Blind AI adjudication of disputed original-study identifications.

`harness.py originals` scores the extractor against human-labelled originals
(FLoRa, FReD, the Feb-2026 human rows). Where the extractor names a different
study than the label, either side can be wrong: FLoRa records one original per
paper and sometimes names a dataset, an instrument or a correction notice. This
script puts each such dispute to Claude Opus, blind:

  - the agent works in a staging copy of the paper's source files (no `<tag>/`
    pipeline output, no paper.json) -- ai_adjudicate.stage();
  - it sees the union of both sides' candidate originals, shuffled under neutral
    letters, never which side proposed which;
  - for every candidate it decides whether the paper replicates that study
    (`replicated`), cites it in another role (`cited_not_replicated`) or does not
    concern it (`not_relevant`), and it names the replicated original(s) itself.

    python benchmarking/adjudicate_originals.py prepare --results <originals dir>
    python benchmarking/adjudicate_originals.py run --workers 12
    python benchmarking/adjudicate_originals.py summarize

Outputs live in benchmarking/results/<originals dir>/adjudication/. The verdicts
are an AI reference (`ai_adjudicated:claude-opus-5-5`), reported beside -- never
merged into -- the human labels.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parent))
sys.path.insert(1, str(BENCH_DIR))

import ai_adjudicate as aa  # noqa: E402
import harness as h  # noqa: E402
import matching  # noqa: E402

DEFAULT_RESULTS = h.RESULTS_DIR / "2026-10-15_core_originals_human"
TAG = "core_eval_20261015"

PROMPT = """You are an expert adjudicator checking which ORIGINAL study a replication paper
replicates. Your verdicts become a reference for scoring an automated extractor.

Your working folder holds source/ (the replication paper: full text, abstract,
references, and/or PDF) and codebook.md (the coding rules; its unit-of-coding and
negative-paper sections define what counts as a replication).

Replication paper DOI: {doi}

Below are candidate original studies, in random order. They come from different
sources; some may be wrong (a dataset, a measurement instrument, a correction
notice, a paper cited only for background, or a mis-resolved DOI).

{candidates}

TASK:
1. Read the paper (introduction, methods, results, discussion) and determine which
   prior published finding(s) it reports a replication of, per the codebook.
2. For EVERY candidate letter decide:
   - "replicated": the paper reports a replication of a finding from this study
     (also when the candidate's DOI or metadata is a variant of the right work);
   - "cited_not_replicated": the paper cites it, but in another role (data source,
     instrument, theory, background, a different study by the same authors);
   - "not_relevant": the paper does not concern this study, or the metadata does
     not identify a real work the paper cites.
   Also flag "metadata_problem" if the title/authors/year/DOI look internally
   inconsistent (e.g. the DOI belongs to a different paper than the title).
3. List the replicated original(s) as YOU identify them from the paper.

Write ./originals_verdict.json:
{{
  "is_replication_paper": true | false,
  "replicated_originals": [{{"reference": "Author (year) title", "doi": "10.... or \\"\\""}}],
  "candidates": {{"A": {{"verdict": "replicated|cited_not_replicated|not_relevant",
                        "metadata_problem": false, "reason": "source-based, one or two sentences"}}, ...}},
  "notes": ""
}}
Only read files inside your working folder; do not use the web. Reply with one line
when the file is written."""


def _crossref(doi: str) -> dict | None:
    for attempt in range(4):
        try:
            url = "https://api.crossref.org/works/" + urllib.parse.quote(doi) + "?mailto=delton17@gmail.com"
            m = json.load(urllib.request.urlopen(url, timeout=30))["message"]
            authors = "; ".join(f"{a.get('family', '')}, {a.get('given', '')}".strip(", ")
                                for a in (m.get("author") or [])[:6])
            year = ((m.get("issued") or {}).get("date-parts") or [[None]])[0][0]
            return {"title": (m.get("title") or [""])[0], "authors": authors, "year": year or "",
                    "journal": (m.get("container-title") or [""])[0]}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {}
            time.sleep(2 + 3 * attempt)
        except Exception:  # noqa: BLE001 - network hiccup: retry
            time.sleep(2 + 3 * attempt)
    return None


def out_dir(results: Path) -> Path:
    return results / "adjudication"


def cmd_prepare(args) -> None:
    results = Path(args.results)
    disputes = [x for x in json.loads((results / "miss_classification.json").read_text())
                if x[0] == "different study named"]
    per_paper = {r["replication_doi"]: r for r in h.read_csv(results / "per_paper.csv")}
    rng = random.Random(args.seed)
    items = []
    for _, rep_doi, sets, _ in disputes:
        r = per_paper[rep_doi]
        px = h.load_extraction(r["paper_folder"], [TAG], h.config.PAPERS_DIR)
        cands = []
        for d in filter(None, r["gt_originals"].split(";")):
            meta = _crossref(d) or {}
            cands.append(dict(side="human", doi=d, title=meta.get("title", ""), authors=meta.get("authors", ""),
                              year=meta.get("year", ""), journal=meta.get("journal", "")))
        seen = set()
        for row in px.get("rows", []):
            key = (matching.doi_of(row, "original_url"), (row.get("original_title") or "").lower())
            if key in seen:
                continue
            seen.add(key)
            cands.append(dict(side="extractor", doi=key[0], title=row.get("original_title", ""),
                              authors=row.get("original_authors", ""), year=row.get("original_year", ""),
                              journal=row.get("original_journal", "")))
        rng.shuffle(cands)
        for i, c in enumerate(cands):
            c["letter"] = chr(ord("A") + i)
        items.append(dict(paper_folder=r["paper_folder"], replication_doi=rep_doi, sets=sets, candidates=cands))
    od = out_dir(results)
    od.mkdir(exist_ok=True)
    (od / "disputes.json").write_text(json.dumps(items, indent=1, ensure_ascii=False))
    print(f"{len(items)} disputes -> {od / 'disputes.json'}")


def _render(cands: list[dict]) -> str:
    return "\n".join(f"{c['letter']}. {c['title'] or '(no title)'} | {c['authors'] or '(no authors)'} | "
                     f"{c['year']} | {c['journal']} | DOI {c['doi'] or '(none)'}" for c in cands)


def adjudicate(item: dict, od: Path, timeout: int) -> dict:
    folder = item["paper_folder"]
    raw = od / "raw" / folder
    raw.mkdir(parents=True, exist_ok=True)
    d = _stage(folder)
    rec = {"folder": folder, "cost_usd": 0.0}
    out = aa.claude(PROMPT.format(doi=item["replication_doi"], candidates=_render(item["candidates"])),
                    d, None, raw / "cli.log", timeout)
    rec["cost_usd"] += float(out.get("total_cost_usd") or 0)
    if not (d / "originals_verdict.json").exists():
        out = aa.claude("originals_verdict.json was not written. Write it now.", d, out["session_id"],
                        raw / "cli.log", timeout)
        rec["cost_usd"] += float(out.get("total_cost_usd") or 0)
    verdict = json.loads((d / "originals_verdict.json").read_text())
    (raw / "originals_verdict.json").write_text(json.dumps(verdict, indent=1, ensure_ascii=False))
    rec["verdict"] = verdict
    return rec


def _stage(folder: str) -> Path:
    """ai_adjudicate.stage under a separate name, so the two staging trees never collide."""
    d = aa.stage(folder, {"sources": []})
    target = aa.STAGE.parent / "originals_stage" / folder
    if target.exists():
        import shutil
        shutil.rmtree(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    d.rename(target)
    return target


def cmd_run(args) -> None:
    od = out_dir(Path(args.results))
    items = json.loads((od / "disputes.json").read_text())
    done = {p.parent.name for p in (od / "raw").glob("*/originals_verdict.json")} if (od / "raw").exists() else set()
    todo = [i for i in items if i["paper_folder"] not in done or args.redo]
    print(f"{len(todo)} dispute(s) with {aa.MODEL}, {args.workers} workers", flush=True)
    cost = 0.0
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(adjudicate, i, od, args.timeout): i["paper_folder"] for i in todo}
        for fut in as_completed(futs):
            try:
                r = fut.result()
                cost += r["cost_usd"]
                v = {k: x.get("verdict") for k, x in r["verdict"].get("candidates", {}).items()}
                print(f"OK  {r['folder']}: {v} ${r['cost_usd']:.2f}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"ERR {futs[fut]}: {e}", flush=True)
    print(f"cost ${cost:.2f}")


def cmd_summarize(args) -> None:
    """Per dispute: was the human label right, was the extractor right?"""
    od = out_dir(Path(args.results))
    rows, tally = [], Counter()
    for item in json.loads((od / "disputes.json").read_text()):
        p = od / "raw" / item["paper_folder"] / "originals_verdict.json"
        if not p.exists():
            tally["not adjudicated"] += 1
            continue
        v = json.loads(p.read_text())
        verdicts = v.get("candidates", {})
        side_ok = {s: any(verdicts.get(c["letter"], {}).get("verdict") == "replicated"
                          for c in item["candidates"] if c["side"] == s) for s in ("human", "extractor")}
        if not v.get("is_replication_paper", True):
            outcome = "not a replication paper"
        elif side_ok["extractor"] and side_ok["human"]:
            outcome = "both right"
        elif side_ok["extractor"]:
            outcome = "extractor right, label wrong"
        elif side_ok["human"]:
            outcome = "label right, extractor wrong"
        else:
            outcome = "neither named"
        tally[outcome] += 1
        rows.append(dict(replication_doi=item["replication_doi"], sets=item["sets"], outcome=outcome,
                         human=" | ".join(c["title"][:80] for c in item["candidates"] if c["side"] == "human"),
                         extractor=" | ".join(c["title"][:80] for c in item["candidates"] if c["side"] == "extractor"),
                         adjudicator=" | ".join(o.get("reference", "")[:100] for o in v.get("replicated_originals", []))))
    h.write_csv(od / "summary.csv", rows)
    (od / "summary.json").write_text(json.dumps(dict(tally), indent=2))
    print(json.dumps(dict(tally), indent=2))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(DEFAULT_RESULTS))
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("prepare"); s.add_argument("--seed", type=int, default=20261015); s.set_defaults(func=cmd_prepare)
    s = sub.add_parser("run"); s.add_argument("--workers", type=int, default=12)
    s.add_argument("--timeout", type=int, default=1800); s.add_argument("--redo", action="store_true")
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("summarize"); s.set_defaults(func=cmd_summarize)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
