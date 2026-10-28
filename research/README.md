# Priority Ranking Experiment

## Scope

`priority_dataset.csv` is a fixed, synthetic 16-case dataset. Its `target_priority_score` values are illustrative reference labels for exercising the comparison pipeline; they are not field measurements, an evaluation claim, or a substitute for expert-labelled operational data.

The experiment runs the four CEFAP ablations from `services/cefap_pipeline.py` (M1 text-only, M2 text plus image, M3 plus location, and M4 all six signals without reliability) and `evidence_aware_v1`. Each method receives the same case rows. CEFAP's normalized CIPS outputs are multiplied by 100; the proposed method natively returns a 0-100 score. M4 time calculations use the fixed timestamp `2025-01-01T00:00:00` so repeated runs do not drift.

Metrics are mean absolute error (MAE), root mean squared error (RMSE), and pairwise rank concordance against the reference scores. The script also writes each case's score and the dataset SHA-256 to `research/results/metrics.json`, plus the score/error chart to `research/results/priority_scores.png`.

## Reproduce

From the repository root in PowerShell:

```powershell
py -3.10 -m venv .venv-research
.\.venv-research\Scripts\Activate.ps1
python -m pip install --requirement research\requirements.txt
python research\run_priority_experiment.py
```

To use another fixed CSV or output folder:

```powershell
python research\run_priority_experiment.py --dataset research\priority_dataset.csv --output-dir research\results
```

The only experiment-specific dependency is pinned in `research/requirements.txt`. Python standard-library CSV/JSON/hash/math support and the repository's CEFAP/evidence-ranking services provide the remaining runtime.