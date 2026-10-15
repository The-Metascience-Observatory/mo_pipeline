#!/usr/bin/env python3
"""AI adjudication of the workbench_v2 reference set with Claude Opus, blind.

The 206-paper workbench (gold/workbench_v2/) holds two AI coders' candidates and an
empty decision file per paper. This script fills a stratified subset of those
decision files with an AI adjudicator, so the core extractor can be scored against
an `ai_adjudicated:<model>` reference while a human audits a sample of it.

    python benchmarking/ai_adjudicate.py select --n 60          # writes selection.csv
    python benchmarking/ai_adjudicate.py run --workers 12       # adjudicates it
    python benchmarking/ai_adjudicate.py audit-sample --n 15    # papers for the human
    python benchmarking/ai_adjudicate.py audit-pack             # pages + verdict sheet
    python benchmarking/ai_adjudicate.py status

Two passes per paper, one Claude CLI session:
  1. BLIND enumeration. The agent works in a staging folder holding copies of the
     paper's source files only -- full text, abstract, references, PDF, the
     codebook. No `<tag>/` pipeline output, no `paper.json`, no coder candidates,
     no flags. It decides eligibility and enumerates effects from the source.
  2. Candidate resolution (the same session, resumed). Only now does it see both
     coders' candidates, packet flags and any recovered source proposals. It maps
     or rejects every candidate, and may add an effect the blind pass missed --
     but only after re-checking the source, and the effect is marked
     `added_after_candidates` so the anchoring is measurable.

The decision is then checked with ground_truth_workbench.validate_decision; a
failing decision gets one resumed repair turn. Raw agent outputs are kept in
gold/workbench_v2/ai_adjudication/raw/ for the audit trail. Started decision files
are never overwritten unless --redo is given.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import random
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BENCH_DIR.parent))
sys.path.insert(1, str(BENCH_DIR))

import ground_truth_workbench as gw  # noqa: E402
from harness import CODEBOOK  # noqa: E402

WB = BENCH_DIR / "gold" / "workbench_v2"
OUT = WB / "ai_adjudication"
RAW = OUT / "raw"
STAGE = BENCH_DIR / "cache" / "adjudication_stage"     # gitignored: copies PDFs
MODEL = "claude-opus-5-5"
REVIEWER = "Claude Opus 5.5 (AI adjudicator)"
SOURCE_SUFFIXES = (".md", ".pdf", ".xml", ".html", ".txt")
SKIP_FILES = {"paper.json"}
# Never adjudicated: an input that is not the paper (the revision notice) and one
# whose outcomes are not recoverable from what we hold (scarcity, see README).
NEVER = {gw.NOTICE, gw.SCARCITY}
# Stratum groups and how many papers each contributes to a 60-paper subset.
QUOTAS = {"negative": 8, "reversal": 5, "biomed": 6, "fred": 6, "flora": 12,
          "main_gt_human": 8, "prod": 6, "other": 9}


def group_of(stratum: str) -> str:
    head = stratum.split(":")[0]
    if head in ("negative", "reversal", "fred", "flora", "main_gt_human", "prod"):
        return head
    return "biomed" if head == "biomed" else "other"


# ── selection ────────────────────────────────────────────────────────────────

def select(n: int, seed: int) -> list[dict]:
    frame = [r for r in gw.read_csv(gw.AUDIT / "frame_reconciled.csv")
             if r["replication_doi"] not in NEVER]
    scale = n / sum(QUOTAS.values())
    rng = random.Random(seed)
    by_group = defaultdict(list)
    for r in frame:
        by_group[group_of(r["stratum"])].append(r)
    picked: list[dict] = []
    for g, quota in QUOTAS.items():
        pool = sorted(by_group[g], key=lambda r: r["paper_folder"])
        k = min(len(pool), round(quota * scale))
        # Psychology is 98 of 206 papers; weight the other disciplines up so the
        # subset covers the field mix the database actually serves.
        weights = [1.0 if r["discipline"] == "psychology" else 1.5 for r in pool]
        chosen = []
        while len(chosen) < k:
            i = rng.choices(range(len(pool)), weights)[0]
            chosen.append(pool.pop(i)); weights.pop(i)
        picked += chosen
    # Every discipline in the frame gets at least one paper: swap in the missing
    # ones for a psychology paper of the same group where possible.
    have = Counter(r["discipline"] for r in picked)
    for disc in sorted({r["discipline"] for r in frame} - set(have)):
        cand = [r for r in frame if r["discipline"] == disc and r not in picked]
        if not cand:
            continue
        new = rng.choice(cand)
        same = [p for p in picked if p["discipline"] == "psychology" and group_of(p["stratum"]) == group_of(new["stratum"])]
        drop = rng.choice(same or [p for p in picked if p["discipline"] == "psychology"])
        picked[picked.index(drop)] = new
    return sorted(picked, key=lambda r: r["paper_folder"])


def cmd_select(args) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = select(args.n, args.seed)
    fields = ["paper_folder", "replication_doi", "discipline", "subdiscipline", "stratum", "source"]
    with open(OUT / "selection.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    (OUT / "selection.json").write_text(json.dumps(
        {"n": len(rows), "seed": args.seed, "quotas": QUOTAS, "excluded": sorted(NEVER),
         "made_at": dt.datetime.now().isoformat(timespec="seconds"),
         "by_group": Counter(group_of(r["stratum"]) for r in rows),
         "by_discipline": Counter(r["discipline"] for r in rows)}, indent=2))
    print(json.dumps({"n": len(rows),
                      "by_group": Counter(group_of(r["stratum"]) for r in rows),
                      "by_discipline": Counter(r["discipline"] for r in rows)}, indent=2))


# ── staging ──────────────────────────────────────────────────────────────────

def stage(folder: str, packet: dict) -> Path:
    """Copy source files only into a fresh folder away from the corpus."""
    d = STAGE / folder
    if d.exists():
        shutil.rmtree(d)
    (d / "source").mkdir(parents=True)
    paper = gw.harness.paper_dir_for(folder)
    if paper is None:
        raise RuntimeError(f"{folder}: no readable paper folder")
    for p in sorted(paper.iterdir()):
        if p.is_file() and p.name not in SKIP_FILES and (p.suffix.lower() in SOURCE_SUFFIXES
                                                        or p.name == "references.json"):
            shutil.copy2(p, d / "source" / p.name)
    for s in packet["sources"]:            # recovered extra sources (sports tables)
        p = Path(s["path"])
        if p.is_file() and not (d / "source" / p.name).exists():
            shutil.copy2(p, d / "source" / p.name)
    shutil.copy2(CODEBOOK, d / "codebook.md")
    return d


# ── prompts ──────────────────────────────────────────────────────────────────

EFFECT_SCHEMA = """{
  "effect_id": "short stable id, e.g. \\"s1:anchoring\\" (study + claim)",
  "original_reference": "First author et al. (year), as cited",
  "original_url": "https://doi.org/... of the ORIGINAL study, or \\"\\" if not stated/verifiable; never guess",
  "original_title": "title of the original study",
  "original_authors": "Last, First; Last, First",
  "original_year": "YYYY",
  "original_journal": "full journal/venue name",
  "replication_study": "which study/experiment in THIS paper (e.g. \\"Study 2\\"; \\"single study\\")",
  "outcome": "the original claim being tested (outcome/DV level)",
  "contrast": "the comparison (e.g. \\"high vs low anchor\\"); \\"not applicable: <why>\\" if none",
  "timepoint": "primary timepoint; \\"not applicable: <why>\\" if none",
  "result": "success | failure | inconclusive | reversal",
  "replication_type": "direct | close experiment | close extension | conceptual",
  "description": "ONE sentence: the ORIGINAL's claimed effect (not the replication's finding)",
  "citation_sentence": "exact sentence(s) from the paper naming the replicated study (author + year)",
  "evidence": "where the result is stated: section/table/page + a short verbatim quote",
  "gt_ambiguity": "clear | ambiguous",
  "notes": "competing readings, why a field is blank, anything an auditor needs"
}"""

PHASE1 = """You are an expert adjudicator building a reference set for scoring an automated
extractor of replication studies. Your judgment becomes ground truth, so be careful
and exhaustive, and never guess.

Your working folder contains:
- codebook.md — the AUTHORITATIVE coding rules (codebook_v2). Read it fully first.
  Ignore its statistics fields: this reference set records no statistics.
- source/ — the replication paper: full text (Markdown rendition and/or body.md),
  abstract.md, references.json and/or the PDF. Use the PDF for tables shown as
  images and anything the text rendition garbles (Read can open PDFs by page).

Paper DOI: {doi}

TASK (pass 1 of 2, blind):
1. Read the codebook, then the whole paper — introduction, methods, results AND
   discussion. Do not classify from the abstract.
2. Decide eligibility: "positive" (reports at least one completed replication of a
   prior published finding with new data), "negative" (one of the codebook's
   negative genres, or no qualifying entry), or "excluded" (the document cannot be
   scored: e.g. a registered-report protocol with no results, a notice, not the paper).
3. If positive, enumerate EVERY entry per the codebook's unit-of-coding rules: one
   entry per claim of the original, per replication study that tests it.
   Timepoints/endpoints of one claim are one entry; controls get no entry; an
   original null claim the replication also finds null is a success.
4. Label each entry's result and replication_type per the codebook. Make a best
   call; record doubt in gt_ambiguity ("ambiguous") and notes — do not leave a
   label blank.

Write your answer to ./pass1.json (in your working folder) as:
{{
  "eligibility": "positive | negative | excluded",
  "eligibility_reason": "one or two sentences, source-based",
  "enumeration_complete": true,
  "effects": [ <one object per entry, schema below>; [] if not positive ]
}}
Entry schema:
{schema}

Only read files inside your working folder. Do not use the web. When pass1.json is
written, reply with one line: the eligibility and the number of effects."""

PHASE2 = """Pass 2 of 2: candidate resolution.

Two independent AI coders (not the system being evaluated) proposed the candidate
entries below for this paper. They are proposals, often wrong or duplicated, and
agreement between them is not evidence. Candidates whose fields are blank and that
say the paper has no replications are negative-paper proposals.

PACKET FLAGS (hints from earlier review, not decisions): {flags}
PRIOR SOURCE REVIEW: {review}
RECOVERED SOURCE PROPOSALS (transcribed from images; verify against source/): {proposals}

CANDIDATES:
{candidates}

TASK:
1. For EVERY candidate_id, decide: "map" to one or more of your effect_ids (it
   describes the same claim/study, even if its labels differ), or "reject" with a
   source-based reason (not a replication, duplicate of another candidate's
   effect at a finer grain than the codebook allows, a control, wrong paper...).
   A negative-paper candidate on a paper you judged positive is a reject; on a
   paper you judged negative/excluded, every candidate is a reject (effect_ids []).
2. If a candidate reveals an entry you MISSED, re-read the source. Add it only if
   the source supports it under the codebook, and set "added_after_candidates": true
   on it. If a candidate makes you change a label or your eligibility call, re-check
   the source and record the change and why in that effect's notes (or in
   "revision_notes").
3. Write the FINAL decision to ./decision.json:
{{
  "eligibility": "...", "eligibility_reason": "...", "enumeration_complete": true,
  "effects": [ final entries, same schema as pass 1, plus "added_after_candidates": true|false ],
  "candidate_resolutions": {{ "<candidate_id>": {{"action": "map"|"reject",
                              "effect_ids": [...], "reason": "..."}} , ... }},
  "revision_notes": "what changed from pass 1 and why ('' if nothing)"
}}
Every candidate_id above must appear exactly once in candidate_resolutions.
Reply with one line when decision.json is written."""

REPAIR = """decision.json fails validation:
{errors}
Fix these in ./decision.json (re-check the source where the fix is substantive) and
reply with one line when done. Every effect of a positive paper needs non-empty
original_reference, replication_study, outcome, contrast, timepoint, result,
replication_type and evidence; every candidate_id must be resolved with a reason;
mapped effect_ids must exist; negative/excluded papers carry no effects."""


def _candidates_text(packet: dict) -> str:
    keep = ("candidate_id", "result", "replication_type", "original_url", "original_title",
            "description", "citation_sentence", "is_replication_paper", "why_negative", "notes")
    return json.dumps([{k: c.get(k, "") for k in keep if c.get(k, "") != ""} | {"candidate_id": c["candidate_id"]}
                       for c in packet["candidates"]], indent=1, ensure_ascii=False)


# ── the Claude CLI ───────────────────────────────────────────────────────────

def claude(prompt: str, cwd: Path, resume: str | None, log: Path, timeout: int) -> dict:
    cmd = ["claude", "-p", prompt, "--model", MODEL, "--output-format", "json",
           "--permission-mode", "acceptEdits",
           "--allowedTools", "Read", "Glob", "Grep", "Write", "Edit",
           "--disallowedTools", "Bash", "WebFetch", "WebSearch", "Task", "Agent"]
    if resume:
        cmd += ["--resume", resume]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    with open(log, "a") as f:
        f.write(f"\n=== {dt.datetime.now().isoformat(timespec='seconds')} exit {p.returncode} "
                f"{time.time() - t0:.0f}s resume={resume}\n{p.stdout[-4000:]}\n{p.stderr[-2000:]}\n")
    try:
        out = json.loads(p.stdout)
    except json.JSONDecodeError:
        raise RuntimeError(f"claude exit {p.returncode}: {p.stderr[-500:] or p.stdout[-500:]}")
    if out.get("is_error"):
        raise RuntimeError(f"claude error: {str(out.get('result'))[:500]}")
    return out


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def to_decision(packet: dict, agent: dict) -> dict:
    d = gw.blank_decision(packet)
    d.update(reviewer=REVIEWER, reviewer_kind="ai_adjudicator", adjudicator_model=MODEL,
             reviewed_at=dt.date.today().isoformat(),
             eligibility=agent.get("eligibility", ""),
             eligibility_reason=agent.get("eligibility_reason", ""),
             sources_checked=True,
             enumeration_complete=bool(agent.get("enumeration_complete")),
             effects=agent.get("effects") or [],
             candidate_resolutions=agent.get("candidate_resolutions") or {})
    if d["eligibility"] != "positive":
        d["effects"] = []
    d["revision_notes"] = agent.get("revision_notes", "")
    d["protocol"] = "ai_adjudicate.py: blind pass 1 (sources only), then candidate resolution"
    return d


def adjudicate(folder: str, timeout: int) -> dict:
    packet = _load(WB / "packets" / f"{folder}.json")
    raw = RAW / folder
    raw.mkdir(parents=True, exist_ok=True)
    log = raw / "cli.log"
    d = stage(folder, packet)
    rec = {"folder": folder, "cost_usd": 0.0, "turns": 0, "started": time.time()}

    def step(prompt, resume):
        out = claude(prompt, d, resume, log, timeout)
        rec["cost_usd"] += float(out.get("total_cost_usd") or 0)
        rec["turns"] += int(out.get("num_turns") or 0)
        return out["session_id"]

    sid = step(PHASE1.format(doi=packet["replication_doi"], schema=EFFECT_SCHEMA), None)
    if not (d / "pass1.json").exists():
        sid = step("pass1.json was not written. Write it now in your working folder.", sid)
    shutil.copy2(d / "pass1.json", raw / "pass1.json")
    sid = step(PHASE2.format(
        flags=json.dumps(packet.get("flags") or []),
        review=json.dumps(packet.get("prior_source_review"), ensure_ascii=False),
        proposals=json.dumps(packet.get("source_proposals") or [], ensure_ascii=False)[:20000] or "[]",
        candidates=_candidates_text(packet)), sid)
    for _ in range(2):
        if not (d / "decision.json").exists():
            sid = step("decision.json was not written. Write it now in your working folder.", sid)
            continue
        try:
            decision = to_decision(packet, _load(d / "decision.json"))
        except json.JSONDecodeError as e:
            sid = step(REPAIR.format(errors=f"- not valid JSON: {e}"), sid)
            continue
        errors = gw.validate_decision(packet, decision)
        if not errors:
            break
        sid = step(REPAIR.format(errors="\n".join("- " + e for e in errors)), sid)
    decision = to_decision(packet, _load(d / "decision.json"))
    errors = gw.validate_decision(packet, decision)
    shutil.copy2(d / "decision.json", raw / "decision.json")
    decision["adjudication_cost_usd"] = round(rec["cost_usd"], 4)
    decision["adjudication_session"] = sid
    (WB / "decisions" / f"{folder}.json").write_text(json.dumps(decision, indent=2, ensure_ascii=False))
    rec.update(seconds=round(time.time() - rec.pop("started")), errors=errors, session=sid,
               eligibility=decision["eligibility"], effects=len(decision["effects"]),
               added_after_candidates=sum(bool(e.get("added_after_candidates")) for e in decision["effects"]))
    (raw / "summary.json").write_text(json.dumps(rec, indent=2))
    return rec


def cmd_run(args) -> None:
    folders = [r["paper_folder"] for r in gw.read_csv(OUT / "selection.csv")]
    if args.only:
        folders = [f for f in folders if f in set(args.only.split(","))]
    todo = []
    for f in folders:
        dec = _load(WB / "decisions" / f"{f}.json")
        if gw.is_untouched(dec) or args.redo:
            todo.append(f)
    if args.limit:
        todo = todo[: args.limit]
    print(f"{len(todo)} paper(s) to adjudicate with {MODEL}, {args.workers} workers", flush=True)
    done = []
    with ThreadPoolExecutor(args.workers) as ex:
        futs = {ex.submit(adjudicate, f, args.timeout): f for f in todo}
        for fut in as_completed(futs):
            f = futs[fut]
            try:
                r = fut.result()
                done.append(r)
                print(f"OK  {f}: {r['eligibility']} {r['effects']} effects, +{r['added_after_candidates']} "
                      f"after candidates, ${r['cost_usd']:.2f}, {r['seconds']}s, errors={len(r['errors'])}",
                      flush=True)
            except Exception as e:  # noqa: BLE001 - one paper never sinks the batch
                print(f"ERR {f}: {e}", flush=True)
    print(json.dumps({"done": len(done), "cost_usd": round(sum(r["cost_usd"] for r in done), 2),
                      "with_errors": sum(bool(r["errors"]) for r in done)}, indent=2))


def cmd_status(args) -> None:
    rows = gw.read_csv(OUT / "selection.csv")
    c, cost = Counter(), 0.0
    for r in rows:
        dec = _load(WB / "decisions" / f"{r['paper_folder']}.json")
        if gw.is_untouched(dec):
            c["pending"] += 1
            continue
        packet = _load(WB / "packets" / f"{r['paper_folder']}.json")
        c["valid" if not gw.validate_decision(packet, dec) else "invalid"] += 1
        c["eligibility:" + dec.get("eligibility", "")] += 1
        cost += float(dec.get("adjudication_cost_usd") or 0)
    print(json.dumps(dict(c, cost_usd=round(cost, 2)), indent=2))


def cmd_audit_sample(args) -> None:
    """Sample for the human audit, built to find adjudicator errors where they hide.

    First, papers whose eligibility call contradicts the stratum the paper was
    sampled from (a "negative" stratum adjudicated positive, or a FLoRa/FReD/human
    replication adjudicated negative) -- up to a third of the sample. Then
    negatives/excluded (at least 3, so that call is audited), then positives spread
    over disciplines. The `why` column says which rule picked each paper, so the
    audit error rate can be reported per stratum rather than as one number.
    """
    rows = gw.read_csv(OUT / "selection.csv")
    rng = random.Random(args.seed)
    done = []
    for r in rows:
        dec = _load(WB / "decisions" / f"{r['paper_folder']}.json")
        if gw.is_untouched(dec):
            continue
        expected = "negative" if r["stratum"].startswith("negative") else "positive"
        done.append(dict(r, eligibility=dec["eligibility"], effects=len(dec["effects"]),
                         prior_label=expected,
                         added_after_candidates=sum(bool(e.get("added_after_candidates")) for e in dec["effects"])))
    rng.shuffle(done)
    pick: list[dict] = []

    def take(cands, k, why):
        for r in cands:
            if len(pick) >= args.n or k <= 0:
                return
            if r not in pick:
                pick.append(dict(r, why=why)); k -= 1

    disagree = [r for r in done if (r["eligibility"] == "positive") != (r["prior_label"] == "positive")]
    take(disagree, max(1, args.n // 3), "eligibility contradicts prior label")
    take([r for r in done if r["eligibility"] != "positive"], max(3, round(args.n * 0.2)) -
         sum(p["eligibility"] != "positive" for p in pick), "negative/excluded call")
    discs = Counter(p["discipline"] for p in pick)
    for r in sorted([r for r in done if r["eligibility"] == "positive"], key=lambda r: discs[r["discipline"]]):
        if discs[r["discipline"]] < 2:
            take([r], 1, "positive, discipline spread"); discs[r["discipline"]] += 1
    take([r for r in done if r["eligibility"] == "positive"], args.n, "positive, random")
    fields = ["paper_folder", "replication_doi", "discipline", "stratum", "prior_label", "eligibility",
              "effects", "added_after_candidates", "why"]
    with open(OUT / "audit_sample.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fields, extrasaction="ignore")
        w.writeheader(); w.writerows(sorted(pick, key=lambda r: r["paper_folder"]))
    print(f"{len(pick)} papers -> {OUT / 'audit_sample.csv'}; "
          f"{len(disagree)} of {len(done)} adjudicated papers contradict their prior label")


def cmd_audit_pack(args) -> None:
    """One readable page per audit paper plus a sheet for the human's verdicts.

    audit/<folder>.md shows the source location, the eligibility call and every
    effect; audit/audit_sheet.csv has one row for the eligibility call, one per
    effect and one "missing effects" row per paper. The auditor fills
    `human_verdict` (agree | disagree | unsure) and, on disagree, `human_correction`.
    Read the source BEFORE the page, so the adjudicator's reading does not anchor yours.
    """
    adir = OUT / "audit"
    adir.mkdir(exist_ok=True)
    sheet = []
    for r in gw.read_csv(OUT / "audit_sample.csv"):
        folder = r["paper_folder"]
        dec = _load(WB / "decisions" / f"{folder}.json")
        paper = gw.harness.paper_dir_for(folder)
        srcs = sorted(p.name for p in paper.iterdir() if p.is_file() and p.suffix.lower() in SOURCE_SUFFIXES) if paper else []
        L = [f"# {r['replication_doi']}", "",
             f"- discipline: {r['discipline']}; stratum: {r['stratum']}; why sampled: {r['why']}",
             f"- source folder: `{paper}`", f"- files: {', '.join(srcs)}", "",
             f"## Eligibility: **{dec['eligibility']}**", "", dec["eligibility_reason"], ""]
        sheet.append(dict(paper_folder=folder, item="eligibility", adjudicator_value=dec["eligibility"],
                          detail=dec["eligibility_reason"]))
        for e in dec["effects"]:
            L += [f"## Effect `{e['effect_id']}`", "",
                  f"| field | value |", "|---|---|"]
            for k in ("original_reference", "original_url", "original_title", "replication_study", "outcome",
                      "contrast", "timepoint", "result", "replication_type", "description",
                      "citation_sentence", "evidence", "gt_ambiguity", "notes"):
                v = str(e.get(k, "")).replace("|", "\\|").replace("\n", " ")
                L.append(f"| {k} | {v} |")
            L.append("")
            sheet.append(dict(paper_folder=folder, item=e["effect_id"],
                              adjudicator_value=f"{e.get('result')} / {e.get('replication_type')}",
                              detail=f"{e.get('original_reference')} -- {e.get('outcome')}"))
        if dec.get("revision_notes"):
            L += ["## Changes after seeing the coders' candidates", "", dec["revision_notes"], ""]
        sheet.append(dict(paper_folder=folder, item="missing_effects", adjudicator_value="(none listed)",
                          detail="List any eligible effect the adjudicator missed"))
        (adir / f"{folder}.md").write_text("\n".join(L), encoding="utf-8")
    for row in sheet:
        row.update(human_verdict="", human_correction="", notes="")
    with open(adir / "audit_sheet.csv", "w", newline="") as f:
        w = csv.DictWriter(f, ["paper_folder", "item", "adjudicator_value", "detail",
                               "human_verdict", "human_correction", "notes"])
        w.writeheader(); w.writerows(sheet)
    print(f"{len(sheet)} audit rows for {len({r['paper_folder'] for r in sheet})} papers -> {adir}/")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("select"); s.add_argument("--n", type=int, default=60)
    s.add_argument("--seed", type=int, default=20261015); s.set_defaults(func=cmd_select)
    s = sub.add_parser("run"); s.add_argument("--workers", type=int, default=12)
    s.add_argument("--limit", type=int, default=None); s.add_argument("--only", default=None)
    s.add_argument("--redo", action="store_true", help="re-adjudicate papers with a started decision")
    s.add_argument("--timeout", type=int, default=2400, help="seconds per CLI call")
    s.set_defaults(func=cmd_run)
    s = sub.add_parser("status"); s.set_defaults(func=cmd_status)
    s = sub.add_parser("audit-sample"); s.add_argument("--n", type=int, default=15)
    s.add_argument("--seed", type=int, default=20261015); s.set_defaults(func=cmd_audit_sample)
    s = sub.add_parser("audit-pack"); s.set_defaults(func=cmd_audit_pack)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
