# Original-study identification — tags core_eval_20261015

Models: {'claude-sonnet-5-5': 458}  ·  ai_version: {'8.10-core': 458}  ·  harness 1.6

Funnel: {'ok': 458, 'wrong_document_on_disk': 6, 'not_extracted': 2}

Scored papers: 458 (extractor found no replications in 19)

| Measure | Value (95% CI, paper bootstrap) |
|---|---|
| Hit rate (≥1 human original named) | 76.6% [72.5%, 80.3%] |
| Hit rate, lenient (truncated DOI tail accepted) | 76.6% |
| Recall of human originals (micro) | 68.9% [55.6%, 79.4%] |
| Recall (macro, per paper) | 75.9% [71.8%, 79.7%] |
| Precision, lower bound (micro) | 62.8% [53.2%, 72.7%] |
| Exact set match | 67.5% [63.1%, 71.6%] |
| Hit rate where something was extracted | 80.0% |
| Extracted rows with no original DOI | 14 |

Precision is a lower bound: the human lists are not exhaustive.

| Set | Papers | Hit | Recall (micro) | Precision LB |
|---|---|---|---|---|
| flora | 277 | 70.8% | 59.1% | 68.0% |
| fred_v242 | 45 | 86.7% | 44.0% | 39.0% |
| main_gt_fred_api | 120 | 86.7% | 87.3% | 72.7% |
| main_gt_human | 27 | 81.5% | 75.9% | 68.8% |
