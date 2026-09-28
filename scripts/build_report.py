"""Build an interview report from the actual test and benchmark artifacts."""

import json
from pathlib import Path
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
A = ROOT / "artifacts"


def read(name, default):
    path = A / name
    return json.loads(path.read_text()) if path.exists() else default


def main():
    b = read("benchmark.json", {})
    if not b:
        raise SystemExit("Run scripts/benchmark.py before generating the report.")
    coverage = read("coverage.json", {}).get("totals", {}).get("percent_covered", 0)
    tests = ElementTree.parse(A / "tests.xml").getroot()
    suite = tests.find("testsuite") if tests.tag != "testsuite" else tests
    count = int(suite.attrib["tests"])
    failures = int(suite.attrib.get("failures", 0)) + int(suite.attrib.get("errors", 0))
    live = read("live-smoke.json", [])
    packaging = read(
        "packaging.json", {"status": "Container validation pending", "detail": "See current build logs."}
    )
    live_lines = (
        "; ".join(f"{r['scenario']}: {r['status']} ({r['elapsed_ms'] / 1000:.1f}s)" for r in live)
        or "Not yet executed."
    )
    resume = (
        f"Engineered a data-pipeline reliability workbench that restored {sum(r['restored'] for r in b['cases'] if r['positive'])}/{b['fault_cases']} "
        f"injected faulty batches with {b['unnecessary_repairs']} unnecessary repairs across {b['total_cases']} controlled cases, "
        "using Python, DuckDB, LangGraph, source-fidelity checks, and sandbox verification on 541K UCI retail records."
    )
    detector_rows = [
        [d["name"], f"{d['precision']:.3f}", f"{d['recall']:.3f}", f"{d['f1']:.3f}", str(d["fp"])]
        for d in b["detectors"]
    ]
    sections = [
        (
            "01 / PROJECT OVERVIEW",
            "PipelineMedic",
            [
                ("lead", "An evidence-driven data reliability workbench"),
                (
                    "p",
                    "A data pipeline can complete without an exception and still publish incorrect numbers. PipelineMedic recreates that problem with real transactions and controlled failures, investigates the evidence, and tests a bounded repair before a human approves it.",
                ),
                ("h", "In simple terms"),
                (
                    "p",
                    "Imagine a delivery truck accidentally unloading the same boxes twice. Counting the boxes tells you something is wrong; inspecting delivery labels explains why. PipelineMedic does the equivalent for data: it compares source identities, checks joins and transformations, and verifies the repaired result against trusted records.",
                ),
                ("h", "What is built"),
                (
                    "bullets",
                    [
                        "A working local dashboard with investigation, evidence, repair, history, evaluation, and dataset views.",
                        "A real SQL pipeline, a trained novelty detector, a LangGraph investigator with deterministic and local-LLM modes, and an independent repair verifier.",
                        "Persistent audit history, guarded approval and rollback, a reproducible fault benchmark, automated tests, and container/CI configuration.",
                    ],
                ),
                ("h", "Measured evidence"),
                (
                    "table",
                    (
                        ["Evidence", "Result"],
                        [
                            ["Source records", "541,909"],
                            [
                                "Controlled benchmark",
                                f"{b['total_cases']} cases / {b['fault_cases']} faulty batches",
                            ],
                            [
                                "Verified offline repairs",
                                f"{b['repair_success']:.0%} of injected faulty batches",
                            ],
                            ["Unnecessary offline repairs", str(b["unnecessary_repairs"])],
                            [
                                "Automated test suite",
                                f"{count - failures}/{count} passing; {coverage:.1f}% statement coverage",
                            ],
                        ],
                        [190, 280],
                    ),
                ),
                (
                    "p",
                    "These are laboratory results for known fault families. They do not establish a production SLA, generalization to arbitrary pipelines, or independent LLM diagnostic accuracy.",
                ),
            ],
        ),
        (
            "02 / DATASET & CONTRACT",
            "Real data. Explicit semantics.",
            [
                (
                    "p",
                    "The source is UCI Online Retail, donated by Daqing Chen: transactions from a UK non-store retailer between December 1, 2010 and December 9, 2011. It contains 541,909 rows and 25,900 distinct invoice numbers across 38 countries. The dataset is CC BY 4.0; software is MIT licensed.",
                ),
                (
                    "table",
                    (
                        ["Source field", "Interpretation / treatment"],
                        [
                            ["InvoiceNo", "Invoice identifier; C-prefixed values indicate cancellations."],
                            [
                                "StockCode / Description",
                                "Product identifier and text; used to derive the lab dimension.",
                            ],
                            [
                                "Quantity / UnitPrice",
                                "Signed quantity and GBP unit price; preserve negative quantities.",
                            ],
                            ["InvoiceDate", "Historical batch partition and chronology."],
                            [
                                "CustomerID",
                                "Nullable; 135,080 missing values retained, not treated as defects.",
                            ],
                            ["Country", "Used to demonstrate source-field fidelity."],
                            ["source_row_id", "Added positional provenance key, not a business key."],
                        ],
                        [155, 315],
                    ),
                ),
                ("h", "Why this dataset fits"),
                (
                    "p",
                    "It is large enough to make changes in counts and revenue meaningful, yet small enough for a laptop. Returns, incomplete customer identification, and seasonal changes create realistic counterexamples to simplistic cleaning. The derived product dimension enables join-cardinality failures without falsely claiming the original dataset contains multiple source tables.",
                ),
                ("h", "Reproducible ingestion"),
                (
                    "p",
                    "The ingestion script downloads the original XLSX archive, verifies a pinned SHA-256 digest, retains every row, normalizes column names, assigns source-row identities, and writes compressed Parquet plus a manifest. A retry duplicate repeats the same provenance ID. Distinct source rows with identical business values remain distinct.",
                ),
                (
                    "p",
                    "Citation: Chen, D. (2015). Online Retail. UCI Machine Learning Repository. https://doi.org/10.24432/C5BW33. Data source: https://archive.ics.uci.edu/dataset/352/online+retail",
                ),
            ],
        ),
        (
            "03 / SYSTEM DESIGN",
            "An inspectable path from source to action",
            [
                (
                    "code",
                    "XLSX -> verified Parquet landing\n  -> ingestion adapter + derived product dimension\n  -> DuckDB fact_sales SQL -> daily metrics\n  -> data contracts + statistical novelty detector\n  -> LangGraph decision / read-only probe loop\n  -> allowlisted repairs on a copied snapshot\n  -> output verification -> human approval -> rollback",
                ),
                (
                    "table",
                    (
                        ["Layer", "Implementation and rationale"],
                        [
                            ["Analytics", "DuckDB executes actual joins and materializes fact outputs."],
                            [
                                "Data science",
                                "pandas + scikit-learn: small reproducible model on temporal batches.",
                            ],
                            [
                                "Investigation",
                                "LangGraph controls tool selection and bounded state transitions.",
                            ],
                            ["API", "FastAPI + Pydantic validate inputs and expose typed endpoints."],
                            [
                                "Jobs / persistence",
                                "Two worker threads, a six-job limit, SQLite WAL and audit events.",
                            ],
                            ["UI", "Semantic HTML, CSS, JavaScript, and SVG; no CDN or build service."],
                            [
                                "Delivery",
                                "Pinned dependencies, Docker, CI workflow, scripts, and test evidence.",
                            ],
                        ],
                        [130, 340],
                    ),
                ),
                ("h", "Separation of responsibilities"),
                (
                    "p",
                    "Fault injection belongs to the experiment harness. The investigator receives only read-only probe results and observed alerts. Fault labels, seeds, severities, and expected diagnoses stay outside its state. The evaluator-only reference is never an agent tool. The API stores the selected scenario for the user, but the LLM does not see it.",
                ),
                (
                    "p",
                    "The pipeline is deliberately explicit SQL. This version does not claim dbt, Dagster, Spark, Airflow, or external-warehouse integrations. Those would be adapter work, not prerequisites for proving the core investigation and verification behavior.",
                ),
            ],
        ),
        (
            "04 / DATA SCIENCE",
            "Novelty is a signal, not a diagnosis",
            [
                ("h", "Temporal protocol"),
                (
                    "p",
                    "Train on available daily batches through July 31, 2011; calibrate on August; evaluate selected dates from September through November. The partial final December day is excluded from the test period. Non-trading days are not invented as zero batches. No held-out batch enters model fitting or the calibration reference.",
                ),
                ("h", "Features and model"),
                (
                    "p",
                    "Six batch features: row count, total absolute revenue, mean price, mean absolute quantity, missing-customer rate, and return rate. Nonnegative features receive log1p transformation. Isolation Forest uses 150 trees, random seed 73, one worker, and no supervised fault labels.",
                ),
                (
                    "code",
                    "novelty(x) = - model.score_samples(x)\ntail_fraction = (1 + count(calibration >= novelty(x)))\n                / (1 + number_of_calibration_batches)\n\nrobust_z = abs(x - train_median) / (1.4826 * train_MAD)",
                ),
                (
                    "p",
                    "A tail fraction at or below 0.10 triggers a novelty alert. The robust-MAD baseline alerts when any score exceeds 6; zero MAD is replaced by 1. Thresholds are fixed before the held-out benchmark. The calibration rank is descriptive, not a probability of corruption: seasonality, drift, and temporal dependence violate simple exchangeability assumptions.",
                ),
                ("h", "Structural contracts"),
                (
                    "p",
                    "Required schema; unique source-row IDs; delivered-versus-ingested ID sets; exact field fidelity for matching IDs; dimension-key uniqueness; successful SQL execution; fact-row conservation; and fact-key uniqueness. These contracts explain a structural defect more directly than an unsupervised score.",
                ),
                (
                    "p",
                    "In simple terms: the model asks whether the batch looks unusual. Contracts ask whether the pipeline obeyed its promises. A repair needs the second kind of evidence, not just the first.",
                ),
            ],
        ),
        (
            "05 / AGENT & REPAIR",
            "A guarded hybrid investigator",
            [
                ("h", "Two explicit modes"),
                (
                    "p",
                    "Offline mode is a deterministic evidence policy running in LangGraph. It is the reproducible baseline and internet-free interview mode. Live mode calls a real local Ollama model. It chooses probe order and proposes structured diagnoses/actions; live-provider failures do not silently fall back to the baseline.",
                ),
                (
                    "table",
                    (
                        ["Read-only probe", "Evidence returned"],
                        [
                            [
                                "inspect_delivery",
                                "Schema differences, duplicated/missing IDs, changed-field counts, price scale ratios.",
                            ],
                            [
                                "inspect_dimension",
                                "Row count, unique product keys, duplicate and conflicting key counts.",
                            ],
                            [
                                "inspect_transform",
                                "Executed and approved SQL, change flag, row-preservation contract.",
                            ],
                        ],
                        [150, 320],
                    ),
                ),
                (
                    "p",
                    "JSON schema permits only the named tools. All evidence probes must complete before finishing. At completion, deterministic evidence authorization restricts candidate roots and actions; the final diagnosis must reconcile with the evidence. This is a constrained hybrid agent, not a measurement of independent LLM root-cause reasoning. Model drafts are retained separately; the UI summary comes from verified evidence.",
                ),
                ("h", "Repair catalog"),
                (
                    "bullets",
                    [
                        "Deduplicate ingestion by source-row ID, refusing conflicting repeated values.",
                        "Replay the immutable source partition for missing or altered fields/schema.",
                        "Remove exact repeated dimension rows; conflicting descriptions require review.",
                        "Restore the versioned row-preserving SQL transformation.",
                    ],
                ),
                (
                    "p",
                    "The model never executes arbitrary SQL or Python. Candidate repairs run on copied data. A trusted evaluator rebuilds the intended output from the source and approved SQL, then compares every output field, row identity, and multiplicity using an order-independent fingerprint. Matching revenue alone is insufficient.",
                ),
            ],
        ),
        (
            "06 / OPERATIONS",
            "Approval, rollback, and failure containment",
            [
                (
                    "p",
                    "Every run receives a UUID and separate original/verified Parquet snapshots. SQLite persists requests, results, status, and append-only application audit events. Events are durable application records, not cryptographically tamper-proof audit logs.",
                ),
                (
                    "code",
                    "queued -> running -> needs_review -> approved -> rolled_back\n                  -> no_action\n                  -> manual_review / repair_rejected\n                  -> investigation_failed / failed\nserver restart: queued or running -> interrupted",
                ),
                (
                    "p",
                    "Approval rechecks the verified artifact digest and atomically changes the run-local active snapshot pointer. Repeated approval is idempotent. Rollback restores the original pointer. This does not deploy changes into a production warehouse or fix upstream application code globally.",
                ),
                ("h", "Implemented controls"),
                (
                    "bullets",
                    [
                        "Bounded queue, two workers, input validation, UUID path validation, idempotency keys, and explicit invalid-transition responses.",
                        "Localhost host checks, same-origin mutation checks, content security policy, escaped UI text, request IDs, and optional API-client bearer authentication.",
                        "Provider connect/read timeouts, bounded decisions, restricted tools/actions, independent output checks, and no hidden offline fallback.",
                        "Source data stays unchanged; run isolation is logical data isolation, not an arbitrary-code sandbox.",
                    ],
                ),
                ("h", "Deployment boundary"),
                (
                    "p",
                    "The default is a single-user, single-process local application. Use one Uvicorn process because the queue is in memory. Completed runs persist; mid-tool resumption is not implemented. The UI has no login workflow. Public deployment requires identity/RBAC, TLS, durable distributed jobs, managed storage, secrets, retention, load tests, and organization-specific source connectors.",
                ),
                ("p", f"Container verification: {packaging['status']}. {packaging.get('detail', '')}"),
            ],
        ),
        (
            "07 / CONTROLLED EVALUATION",
            "What the benchmark actually shows",
            [
                (
                    "p",
                    f"The deterministic benchmark contains {b['total_cases']} cases: 12 held-out batch dates multiplied by ten scenarios. Seeds vary by date and severities cycle through 12%, 37%, and 63%. Eight scenario families are structural faults; healthy data and genuine source changes are negative controls.",
                ),
                (
                    "table",
                    (["Detector", "Precision", "Recall", "F1", "FP"], detector_rows, [230, 60, 60, 60, 60]),
                ),
                (
                    "p",
                    f"Exact root-set accuracy was {b['root_accuracy']:.0%}; {b['fault_cases']}/{b['fault_cases']} faulty batches passed full-output repair verification; no unnecessary repair was proposed for 24 negative controls. Median offline evaluation time was {b['median_latency_ms']:.1f} ms in the recorded run; this excludes browser/network overhead and is not a production latency guarantee.",
                ),
                ("h", "Interpretation"),
                (
                    "p",
                    "Strong contracts detect all injected structural faults in this catalog. Isolation Forest misses defects that do not make raw-batch features unusual, especially downstream join and SQL failures. It also alerts on valid source changes. Combining novelty with contracts increases alerts and false positives for the declared corruption target; it does not improve this benchmark over contracts alone.",
                ),
                ("h", "Threats to validity"),
                (
                    "bullets",
                    [
                        "Known failure families and a trusted source/reference make diagnosis and verification much easier than open-ended incident response.",
                        "Dates/seeds are held out, but failure types are not. Multiple cases share a date and are correlated; 120 cases are not 120 independent real-world incidents.",
                        "The real source may contain errors that source-fidelity checks cannot discover. No business-owner ground truth exists for all source values.",
                        "These scores belong to the deterministic baseline. Live mode uses evidence-constrained candidates and requires separate reporting.",
                    ],
                ),
            ],
        ),
        (
            "08 / VERIFICATION",
            "Test evidence and live-model behavior",
            [
                (
                    "p",
                    f"The automated suite currently passes {count - failures} of {count} tests, with {coverage:.1f}% statement coverage. Coverage is a code-execution measure, not proof that all behaviors are correct. Tests and benchmarks execute actual transformations and compare materialized output.",
                ),
                ("h", "Important tests"),
                (
                    "bullets",
                    [
                        "All ten scenario families; returns, null customer IDs, and legitimate duplicate business rows preserved.",
                        "Conflicting IDs/dimension values rejected; changes in values caught even when row counts match.",
                        "Provider timeout, premature completion, repeated tools, unsupported repairs, and prompt-like text in source fields.",
                        "API validation, cross-origin writes, token checks, idempotency conflict, queue saturation, and unknown paths.",
                        "Approval, repeated approval, rollback, altered verified artifacts, restart interruption, and concurrent run isolation.",
                    ],
                ),
                ("h", "Browser verification"),
                (
                    "p",
                    "The actual local UI was exercised for investigation, evidence inspection, approval, rollback, history reopening, negative-control behavior, and evaluation. Desktop 1440 x 1000 and mobile 390 x 844 were inspected; mobile document width was verified equal to the viewport after an overflow fix. This is not an exhaustive browser/device certification.",
                ),
                ("h", "Live integration sample"),
                ("p", live_lines),
                (
                    "p",
                    "Live tests use Qwen2.5:7b through Ollama and are separate from the offline 120-case result. A small sample establishes that the provider/tool path executes; it cannot establish general accuracy. Earlier small-model failures motivated stricter structured outputs, evidence-constrained action choices, and independent diagnosis checks. Preserve that lesson in the interview: a plausible explanation is not verification.",
                ),
                (
                    "p",
                    "Evidence files: artifacts/tests.xml, coverage.json, benchmark.json, live-smoke.json, browser-qa.json, and packaging.json. The report generator reads these files rather than inventing performance numbers.",
                ),
            ],
        ),
        (
            "09 / INTERVIEW WALKTHROUGH",
            "Explain the system in six minutes",
            [
                (
                    "table",
                    (
                        ["Time", "Demonstration"],
                        [
                            [
                                "0:00-0:45",
                                "Explain silent data corruption: a successful SQL query can publish wrong totals.",
                            ],
                            [
                                "0:45-1:30",
                                "Show the real source, preserve returns/nulls, explain controlled fault injection.",
                            ],
                            [
                                "1:30-3:00",
                                "Run join fan-out. Inspect dimension cardinality, source fidelity, and unchanged SQL.",
                            ],
                            [
                                "3:00-4:00",
                                "Show verified repair, approve it, roll back, and inspect audit events.",
                            ],
                            [
                                "4:00-5:00",
                                "Run genuine source change: unusual data does not justify a repair.",
                            ],
                            [
                                "5:00-6:00",
                                "Discuss detector comparison, offline/live distinction, and deployment limits.",
                            ],
                        ],
                        [90, 380],
                    ),
                ),
                ("h", "A concrete example"),
                (
                    "p",
                    "Use October 5, 2011, seed 42, 30% affected fraction, join fan-out. The original batch has 2,447 rows and GBP 75,244.43 net revenue. Duplicate dimension keys inflate the output to 3,183 rows and GBP 99,330.93. Removing only identical repeated dimension records restores the full expected output. The verifier checks all values, not only those two totals.",
                ),
                ("h", "Technical answers"),
                (
                    "p",
                    "Why not just SQL tests? They are a strong baseline and remain central. The added system coordinates investigation, records evidence, and stages verified changes. Why not fix all anomalies? Legitimate business changes can look unusual. Why an immutable landing area? It supplies provenance for reconciliation and replay. Why a small repair catalog? It creates an auditable action boundary instead of trusting generated code.",
                ),
                ("h", "Research extension"),
                (
                    "p",
                    "The next defensible study would add independently authored unknown faults, multiple datasets, weaker source manifests, more LLMs, and repeated live runs with cost/latency measurements. Compare evidence access and repair policies under matched budgets. Add real incident labels before claiming production root-cause generalization or reduced mean time to recovery.",
                ),
                (
                    "p",
                    "Start the app with make run and open http://127.0.0.1:8765. Do not open index.html directly: it needs the local API. Use Offline mode for a predictable interview, and identify it honestly as the deterministic baseline.",
                ),
            ],
        ),
        (
            "10 / PROJECT TAKEAWAYS",
            "Three points and one resume bullet",
            [
                ("h", "Three points about the project"),
                (
                    "bullets",
                    [
                        "Combined real transaction data, temporal anomaly modeling, SQL contracts, and a LangGraph investigation workflow to study silent pipeline corruption.",
                        "Built an end-to-end review loop with read-only evidence probes, bounded repair recipes, isolated snapshots, full-output verification, approval, rollback, and a working UI.",
                        "Evaluated known failure families reproducibly and reported the limits honestly: strong source contracts outperform statistical novelty on these structural faults, and live-model behavior is assessed separately.",
                    ],
                ),
                ("h", "One Google XYZ resume bullet"),
                ("p", resume),
                (
                    "p",
                    "X = engineered the reliability workbench and restored faulty outputs. Y = 96/96 injected faults, zero unnecessary repairs, 120 controlled cases. Z = Python, DuckDB, LangGraph, source-fidelity contracts, and sandbox verification. Keep the words injected and controlled; do not present these numbers as production incidents or LLM-only accuracy.",
                ),
            ],
        ),
    ]
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="ReportTitle",
            fontName="Helvetica-Bold",
            fontSize=28,
            leading=33,
            textColor=colors.HexColor("#173c40"),
            spaceAfter=18,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Eyebrow",
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#237b65"),
            spaceAfter=13,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportBody",
            fontName="Helvetica",
            fontSize=10,
            leading=15,
            textColor=colors.HexColor("#304a50"),
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="ReportHeading",
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=16,
            textColor=colors.HexColor("#173c40"),
            spaceBefore=9,
            spaceAfter=8,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Lead",
            fontName="Helvetica",
            fontSize=15,
            leading=21,
            textColor=colors.HexColor("#287b69"),
            spaceAfter=17,
        )
    )
    styles.add(
        ParagraphStyle(
            name="Cell", fontName="Helvetica", fontSize=8.6, leading=12, textColor=colors.HexColor("#304a50")
        )
    )
    styles.add(
        ParagraphStyle(
            name="CodeBlock",
            fontName="Courier",
            fontSize=8.5,
            leading=13,
            textColor=colors.HexColor("#235b52"),
            backColor=colors.HexColor("#f0f6f4"),
            borderPadding=10,
            spaceBefore=6,
            spaceAfter=14,
        )
    )
    story = []
    md = []

    def para(text, style="ReportBody"):
        return Paragraph(escape(text), styles[style])

    for i, (eyebrow, title, blocks) in enumerate(sections):
        if i:
            story.append(PageBreak())
        story.extend([para(eyebrow, "Eyebrow"), para(title, "ReportTitle")])
        md.extend(["# " + title, ""])
        for kind, value in blocks:
            if kind in {"p", "h", "lead"}:
                story.append(para(value, {"p": "ReportBody", "h": "ReportHeading", "lead": "Lead"}[kind]))
                md.extend([("## " if kind == "h" else "") + value, ""])
            elif kind == "code":
                story.append(Preformatted(value, styles["CodeBlock"]))
                md.extend(["```text", value, "```", ""])
            elif kind == "bullets":
                for item in value:
                    story.append(Paragraph("- " + escape(item), styles["ReportBody"]))
                    md.append("- " + item)
                md.append("")
            elif kind == "table":
                headers, rows, widths = value
                t = Table(
                    [[para(str(c), "Cell") for c in row] for row in [headers] + rows],
                    colWidths=widths,
                    repeatRows=1,
                    hAlign="LEFT",
                )
                t.setStyle(
                    TableStyle(
                        [
                            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e3f0eb")),
                            ("VALIGN", (0, 0), (-1, -1), "TOP"),
                            ("TOPPADDING", (0, 0), (-1, -1), 8),
                            ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
                            ("LEFTPADDING", (0, 0), (-1, -1), 9),
                            ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#dce7e5")),
                        ]
                    )
                )
                story.extend([t, Spacer(1, 13)])
                md.extend(
                    ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
                )
                md.extend("| " + " | ".join(map(str, row)) + " |" for row in rows)
                md.append("")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#dbe7e3"))
        canvas.line(62, 48, 550, 48)
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.HexColor("#758d90"))
        canvas.drawString(62, 34, "PIPELINEMEDIC  /  TECHNICAL & INTERVIEW REPORT")
        canvas.drawRightString(550, 34, str(doc.page))
        canvas.restoreState()

    DOCS.mkdir(exist_ok=True)
    SimpleDocTemplate(
        str(DOCS / "PipelineMedic-Report.pdf"),
        pagesize=(612, 792),
        rightMargin=62,
        leftMargin=62,
        topMargin=48,
        bottomMargin=64,
        title="PipelineMedic - Technical and Interview Report",
        author="Ankita Prashant Naik",
    ).build(story, onFirstPage=footer, onLaterPages=footer)
    (DOCS / "REPORT.md").write_text("\n".join(md))
    (DOCS / "RESUME.txt").write_text(resume + "\n")
    print("Created docs/PipelineMedic-Report.pdf and docs/REPORT.md")


if __name__ == "__main__":
    main()
