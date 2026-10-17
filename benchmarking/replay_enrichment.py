#!/usr/bin/env python3
"""Re-run the core extractor's post-processing on saved model replies.

`extract_core.py` saves each paper's raw reply in `<tag>/debug_log.json`
(`assistant_text`). This replays everything after the model call -- parse,
postprocess, validation, DOI check, metadata enrichment -- with the CURRENT code
and writes the result under a new tag, leaving the original untouched. The model
output is identical, so a score difference between the two tags is attributable
to the post-processing change alone (first used for the 2026-10-15 fix that drops
a DOI resolving to a different work than the extracted title).

    python benchmarking/replay_enrichment.py --tag core_eval_20261015 \
        --new-tag core_eval_20261015_doifix --include-list a.txt [--include-list b.txt]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parent))
sys.path.insert(1, str(BENCH_DIR))

import harness as h  # noqa: E402
from mo_pipeline.corpus.models import folder_to_doi_url  # noqa: E402
from mo_pipeline.discover.screening_backend import parse_json_reply  # noqa: E402
from mo_pipeline.extract import extract as ex  # noqa: E402
from mo_pipeline.extract import extract_core as core  # noqa: E402


def replay(folder: str, tag: str, new_tag: str, resume: bool = True) -> str:
    paper = h.paper_dir_for(folder)
    if paper is None or not (paper / tag / "debug_log.json").exists():
        return "skipped"
    src, dst = paper / tag, paper / new_tag
    if resume and (dst / "replay_log.txt").exists():
        log = (dst / "replay_log.txt").read_text()
        return f"ok, {log.count('dropped DOI')} DOI(s) dropped (resumed)"
    debug = json.loads((src / "debug_log.json").read_text())
    data = parse_json_reply(debug.get("assistant_text") or "")
    if data is None:
        return "unparseable"
    data = core.postprocess(data, paper, debug.get("prompt_version") or "")
    data, log = ex.validate_extraction(data)
    mismatches, cache = ex.validate_original_dois(data)
    # The replication paper's own metadata does not depend on the post-processing
    # being replayed and costs a full multi-API lookup per paper: carry it over
    # from the source tag's result instead of fetching it again.
    prior = src / f"{folder}{core.RESULT_SUFFIX}"
    rep_meta = json.loads(prior.read_text()).get("replication_metadata") if prior.exists() else None
    # The input the model was given, re-assembled exactly as extract_core does,
    # so the DOI-provenance check tests against what the model actually saw.
    from mo_pipeline import config
    source_text, _ = core.assemble_input(paper, core.paper_artifacts(paper), config.EXTRACT_CORE_MAX_INPUT_CHARS)
    doi_sources: dict = {}
    data, msgs = ex.enrich_metadata(
        data, replication_doi="" if rep_meta else (ex._extract_doi_from_url(folder_to_doi_url(folder)) or ""),
        original_doi_cache=cache, source_text=source_text,
        references=ex._load_references(paper), doi_sources=doi_sources)
    if rep_meta:
        data["replication_metadata"] = rep_meta
    debug["doi_sources"] = {str(k): v for k, v in doi_sources.items()}
    dst.mkdir(exist_ok=True)
    (dst / "debug_log.json").write_text(json.dumps(debug, indent=2, default=str))
    if (src / "provenance.json").exists():
        shutil.copy2(src / "provenance.json", dst / "provenance.json")
    prov_path = dst / "provenance.json"
    if prov_path.exists():
        prov = json.loads(prov_path.read_text())
        prov["replayed_postprocessing"] = {"from_tag": tag, "code_fingerprint_at_replay": _fingerprint()}
        prov_path.write_text(json.dumps(prov, indent=2))
    (dst / f"{folder}{core.RESULT_SUFFIX}").write_text(json.dumps(data, indent=2))
    (dst / "replay_log.txt").write_text("\n".join(log + msgs))
    return f"ok, {sum('dropped DOI' in m for m in msgs)} DOI(s) dropped"


def _fingerprint() -> str:
    try:
        from mo_pipeline import version
        return version.code_fingerprint()
    except Exception:  # noqa: BLE001
        return ""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True); ap.add_argument("--new-tag", required=True)
    ap.add_argument("--include-list", action="append", required=True)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    folders = sorted({ln.strip() for f in args.include_list for ln in Path(f).read_text().splitlines() if ln.strip()})
    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(lambda f: (f, replay(f, args.tag, args.new_tag)), folders))
    dropped = sum(int(r.split(", ")[1].split()[0]) for _, r in results if r.startswith("ok"))
    for f, r in results:
        if "dropped" in r and not r.startswith("ok, 0"):
            print(f"{f}: {r}")
    print(json.dumps({"papers": len(folders), "ok": sum(r.startswith("ok") for _, r in results),
                      "skipped": sum(r == "skipped" for _, r in results),
                      "unparseable": sum(r == "unparseable" for _, r in results),
                      "dois_dropped": dropped}, indent=2))


if __name__ == "__main__":
    main()
