# Interview walkthrough

## Before the interview
1. Run `make run` and open http://127.0.0.1:8765/ (not the HTML file directly).
2. Run an offline join fan-out case once to warm the dataset and model cache.
3. Keep the PDF report and `artifacts/benchmark.json` available.
4. Optional: start the downloaded Ollama runtime with `OLLAMA_MODELS="$PWD/.tools/models" .tools/ollama serve`. The tested live model is configured through `OLLAMA_MODEL`; see the report for exact results.
5. Use Offline mode if internet or local model resources are unavailable. State clearly that this is the deterministic baseline.

## 0:00-0:45 - Problem
"A green pipeline run only tells us the code completed. A duplicated join can silently inflate revenue. I built a workbench that detects defects, investigates evidence, and proves whether a repair restores the intended output."

## 0:45-1:30 - Dataset
"The source is 541,909 real UCI retail rows. I retain cancellations, missing customer IDs, and legitimate repeated purchases. I add a provenance ID and inject known faults into isolated daily batches. The faults are synthetic; the transactions are real."

## 1:30-3:00 - Diagnosis
Use join fan-out / 2011-10-05 / seed 42 / fraction 30%. Show failed dimension and fact contracts. Open Evidence trace. Show delivery fidelity, duplicate dimension keys, and unchanged SQL. Explain that a downstream count mismatch is a symptom; the duplicated upstream key is the cause.

## 3:00-4:00 - Repair
Open Repair & review. Explain exact-row dimension deduplication and refusal to arbitrarily select conflicting records. Show 3,183 rows / GBP 99,330.93 before and 2,447 rows / GBP 75,244.43 after. Explain that all output fields are compared, not just revenue. Approve, then roll back. Show the audit trail.

## 4:00-5:00 - Counterexample
Run Genuine business change. Explain that an unusual distribution can be correct. Show source fidelity and the absence of a repair. This is why anomaly detection and repair authorization are separate.

## 5:00-6:00 - Evaluation and limits
Show the 120-case deterministic benchmark and detector comparison. State that known fault families and strong source contracts make it easier than real incident response. Discuss the separately measured live-model results, failure handling, and what would be needed for production deployment.

## Questions to prepare for
- Why not just use SQL tests? They are a strong baseline. The agent provides an evidence-gathering and review workflow; this project does not claim it replaces contracts.
- Is the offline mode an LLM? No. It is a deterministic policy in the same orchestration graph, plus a real trained novelty model.
- Why not automatically fix every alert? Source shifts can be legitimate; repair requires structural evidence, safe operations, exact output validation, and approval.
- How did you prevent label leakage? Fault name, seed, severity, and expected roots are kept outside the investigator state. Data-science training/calibration precede test dates.
- Why preserve duplicate transactions? Content equality does not imply replay. Only duplicated source-row identities are removed, and conflicts block automatic repair.
- Why does the benchmark score so well? The failures come from a known catalog and there is a trusted source snapshot. These results support a bounded laboratory claim, not arbitrary production generalization.
- What does approval actually do? It changes the run's local active snapshot pointer. It does not deploy upstream source code.
