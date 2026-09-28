# Architecture decision record

## 1. Real transactions, controlled failures
Use UCI Online Retail rather than claiming synthetic failures occurred in production. The original archive is checksum-pinned and CC BY 4.0 attributed. A derived product dimension deliberately supplies a relational join surface. Preserve source returns, null customer IDs, and business duplicates.

## 2. Explicit contracts before novelty
Structural invariants have direct semantics. Isolation Forest and robust MAD detect unusual distributions, not causes. Show both and evaluate them against a declared positive class. Do not let a novelty alert authorize a repair.

## 3. Bounded agent, not arbitrary code execution
LangGraph coordinates a maximum-step decision/probe workflow. The LLM can select a named read-only probe and propose a named repair. Strict JSON schema, evidence authorization, reference-output verification, and approval are separate layers. No model-produced SQL is executed. Model rationales are hypotheses; tool outputs are evidence.

## 4. Offline and live results stay separate
The offline investigator is an explicit deterministic baseline. The live investigator uses Ollama. A failed provider does not silently become an offline success. Model smoke tests are not the 120-case benchmark. This separation supports an honest interview explanation and a reliable offline fallback chosen by the user.

## 5. Snapshot promotion
Approval atomically changes a per-run workspace pointer to the verified snapshot. Before approval, its output digest is checked again. Rollback points back to the original. Upstream code deployment, a global production warehouse, and distributed job processing are not implemented.

## 6. Single-process local deployment
DuckDB is an embedded analytical engine; SQLite WAL is sufficient for this local job/audit store. Two bounded worker threads isolate per-run work. Exactly one server process owns the queue. Interrupted runs are marked on restart; resuming inside an LLM call is outside scope.

## 7. Minimal frontend dependencies
A custom semantic HTML/CSS/JavaScript UI needs no CDN, frontend package manager, or build service. The backend serves its assets. This reduces interview-day setup and still provides responsive views, real API actions, accessible labels, and persistent audit history.

## 8. What would change for a real organization
Add adapters for its source systems, versioned business contracts, genuine incident labels, queue workers, a production database, user identity/RBAC, deployment approvals, secret management, telemetry, retention, integration environments, and operational load testing. Replace source-perfect verification where no immutable oracle is available with business invariants and owner-approved reconciliation. Validate changes with the actual data owners.
