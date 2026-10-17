# Original-study identification — tags core_eval_20261015_doifix3

Models: {'claude-sonnet-5-5': 458}  ·  ai_version: {'8.10-core': 458}  ·  harness 1.7

Funnel: {'ok': 458, 'wrong_document_on_disk': 6, 'not_extracted': 2}

Scored papers: 458 (extractor found no replications in 19)

| Measure | Value (95% CI, paper bootstrap) |
|---|---|
| Hit rate (≥1 human original named) | 83.6% [80.1%, 86.9%] |
| Hit rate, lenient (truncated DOI tail accepted) | 83.6% |
| Hit rate, work level (another registered record of the same work accepted) | 86.0% [83.0%, 89.1%] |
| Recall of human originals (micro) | 74.9% [60.9%, 85.7%] |
| Recall of human originals, work level (micro) | 77.1% [62.6%, 88.0%] |
| Recall (macro, per paper) | 82.9% [79.5%, 86.1%] |
| Precision, lower bound (micro) | 68.3% [57.8%, 78.7%] |
| Exact set match | 74.5% [70.5%, 78.2%] |
| Hit rate where something was extracted | 87.2% |
| Extracted rows with no original DOI | 14 |

Precision is a lower bound: the human lists are not exhaustive.

| Set | Papers | Hit | Hit, work level | Recall (micro) | Precision LB |
|---|---|---|---|---|---|
| flora | 277 | 79.8% | 83.0% | 66.6% | 76.6% |
| fred_v242 | 45 | 91.1% | 91.1% | 45.9% | 40.7% |
| main_gt_fred_api | 120 | 90.0% | 90.0% | 90.3% | 75.2% |
| main_gt_human | 27 | 85.2% | 92.6% | 79.3% | 71.9% |
