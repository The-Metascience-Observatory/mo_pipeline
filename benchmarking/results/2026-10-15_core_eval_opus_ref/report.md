# Extraction benchmark — gold / tags core_eval_20261015 / split all

## Provenance

- models: {'claude-sonnet-5-5': 41}  | ai_version in results: {'8.10-core': 41}
- prompt version now: 8.10 (prompts dirty in git: True); git 705bb8fdca
- claude CLI: 2.1.301 (Claude Code) | harness 1.6 | 2026-10-15T20:46:12Z
- ground truth: gold files ['benchmarking/gold/workbench_v2/export_ai_adjudicator/gold_rows.csv', 'benchmarking/gold/workbench_v2/export_ai_adjudicator/gold_negatives.csv']
- matcher: {'mode': 'llm', 'provider': 'claude_cli', 'model': 'sonnet', 'prompt_version': '2.0', 'calls': 207, 'cache_hits': 0, 'failures': 0, 'offline': False}
- input tiers: {'xml': 17, 'grobid': 24}

## Coverage funnel

papers in GT: 41; not downloaded/converted: 0; not extracted under these tags: 0; bad json: 0; pipeline said no replications: 0; wrong document on disk: 0; scored: 41

## Entry-level matching (effect-level GT only)

TP 144  FN 63  FP 13 + 18 on negative papers  → end-to-end precision 82.3%, recall 69.6%, F1 75.4%
conditional: precision on positive papers 91.7%, recall on papers with usable output 69.6%
FN breakdown: 0 judged different_original, 63 no candidate row, 0 paper reported no replications, 0 no usable extraction output
granularity misses (same original, other effect): 9; wrong-original errors flagged by judge: 0; paper-level GT extra rows (unpenalized): 0

## Paper-level (contains_replications)

positives: TP 41 FN 0 | negatives: TN 9 FP 8 (not evaluated: 0) → precision 83.7%, negative-set FPR 47.1%

## Result classification (3-value; reversal→failure where the GT source lacks the class)

n=144  accuracy 78.5% [55.7%, 96.6%]  κ 0.684  macro-F1 75.7%  (collapse applied on 0 rows)

| class | support | predicted | recall | precision | F1 |
|---|---|---|---|---|---|
| success | 56 | 46 | 80.4% | 97.8% | 88.2% |
| failure | 62 | 47 | 72.6% | 95.7% | 82.6% |
| inconclusive | 23 | 48 | 87.0% | 41.7% | 56.3% |

confusion (rows = GT, cols = pipeline):

| | success | failure | inconclusive |
|---|---|---|---|
| **success** | 45 | 0 | 11 |
| **failure** | 0 | 45 | 17 |
| **inconclusive** | 1 | 2 | 20 |

## Result classification (4-value, strict, gold/human rows only)

n=144  accuracy 78.5% [55.7%, 96.6%]  κ 0.684  macro-F1 81.8%

reversal: support 3, predicted 3, recall 100.0%, precision 100.0%

Pipeline `reversal` across all scored rows (raw, before collapse): predicted 3; GT reversal support 3.

## Replication type

4-class n=144: accuracy 84.7% [71.5%, 93.5%], adjacent-or-exact 96.5%, κ 0.72; 2-class (FReD 'direct or close' vs conceptual) n=0: n/a

## Original study identification

original DOI exact (n=99): 100.0% [100.0%, 100.0%]; pipeline left DOI empty on 0.0%
bibliographic (n=144): title 99.3%, authors 79.2%, year 100.0%, journal 97.2%
citation_sentence: present 100.0%; author+year of GT original found in it 34.7%

## Statistics

Not scored: neither side carries statistics. This arm ran stat-free (core) and the ground truth was coded without them, so there is nothing to compare. Blank here means never measured, not measured as zero.

## Matcher

{'methods': {'doi+judge': 99, 'llm': 45}, 'relations': {'same_effect': 143, 'subanalysis_of_gt': 1}, 'judge_calls': 207, 'cache_hits': 0, 'judge_failures': 0}

## Breakdowns (3-value result accuracy)

**by source**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| biomed_initiative | 45 | 6 | 40.0% | 100.0% |
| curate_science | 3 | 1 | 100.0% | n/a |
| flora | 22 | 10 | 86.4% | 100.0% |
| fred_v242 | 14 | 5 | 100.0% | 100.0% |
| main_gt_human | 10 | 4 | 100.0% | 100.0% |
| medical_slice | 12 | 3 | 100.0% | 100.0% |
| negative_adversarial | 1 | 1 | 100.0% | n/a |
| prod_slice | 24 | 5 | 95.8% | 100.0% |
| replication_wiki | 5 | 2 | 100.0% | 100.0% |
| reversal_stratum | 8 | 4 | 100.0% | 100.0% |

**by provenance**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| ai_adjudicated:claude-opus-5-5 | 144 | 41 | 78.5% | 100.0% |

**by discipline_group**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| biomed | 80 | 18 | 66.2% | 100.0% |
| lang_edu | 5 | 3 | 60.0% | 100.0% |
| other | 9 | 3 | 88.9% | 100.0% |
| psych | 29 | 11 | 100.0% | 100.0% |
| socsci | 21 | 6 | 95.2% | 100.0% |

**by gt_type**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| close experiment | 5 | 3 | 100.0% | 100.0% |
| close extension | 44 | 16 | 100.0% | 100.0% |
| conceptual | 4 | 4 | 75.0% | 100.0% |
| direct | 91 | 25 | 67.0% | 100.0% |

**by tier**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| grobid | 65 | 24 | 95.4% | 100.0% |
| xml | 79 | 17 | 64.6% | 100.0% |

**by year_bucket**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| unknown | 144 | 41 | 78.5% | 100.0% |

**by split**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| dev | 144 | 41 | 78.5% | 100.0% |

**by gt_ambiguity**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| ambiguous | 64 | 29 | 76.6% | 100.0% |
| clear | 80 | 35 | 80.0% | 100.0% |

**by match_method**

| value | n rows | n papers | accuracy | DOI acc |
|---|---|---|---|---|
| doi+judge | 99 | 26 | 69.7% | 100.0% |
| llm | 45 | 17 | 97.8% | n/a |
