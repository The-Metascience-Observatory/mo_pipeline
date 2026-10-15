# Original-study identification — tags core_eval_20261015_doifix

Models: {'claude-sonnet-5-5': 458}  ·  ai_version: {'8.10-core': 458}  ·  harness 1.6

Funnel: {'ok': 458, 'wrong_document_on_disk': 6, 'not_extracted': 2}

Scored papers: 458 (extractor found no replications in 19)

| Measure | Value (95% CI, paper bootstrap) |
|---|---|
| Hit rate (≥1 human original named) | 80.8% [77.1%, 84.3%] |
| Hit rate, lenient (truncated DOI tail accepted) | 80.8% |
| Recall of human originals (micro) | 72.4% [58.7%, 83.2%] |
| Recall (macro, per paper) | 80.1% [76.4%, 83.5%] |
| Precision, lower bound (micro) | 66.1% [56.1%, 76.2%] |
| Exact set match | 71.6% [67.2%, 75.5%] |
| Hit rate where something was extracted | 84.3% |
| Extracted rows with no original DOI | 14 |

Precision is a lower bound: the human lists are not exhaustive.

| Set | Papers | Hit | Recall (micro) | Precision LB |
|---|---|---|---|---|
| flora | 277 | 75.8% | 63.3% | 72.9% |
| fred_v242 | 45 | 91.1% | 45.9% | 40.7% |
| main_gt_fred_api | 120 | 88.3% | 88.8% | 73.9% |
| main_gt_human | 27 | 85.2% | 79.3% | 71.9% |
