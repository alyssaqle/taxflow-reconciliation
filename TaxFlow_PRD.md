# TaxFlow Invoice Intake Agent

Product requirements and laptop build prompt for Alyssa Le · Version 2 reviewed September 30 2026

Build a Python web application that reads a fictional invoice, organizes the important information, checks for missing details and arithmetic errors, and prepares a review report for a person. This is a portfolio prototype for tax and finance operations, using synthetic data. The first version focuses on invoices so that a working agent, evaluation, and deployment can fit a focused build day. Azure account setup and debugging may take longer.

## 1. The product in plain words

Imagine you work at a small consulting firm. A client sends you an invoice, which is a document listing what a vendor charged for its work. Before your team uses it, someone needs to read the document, copy the information into a record, check that the amounts add up, and follow up on anything missing.

TaxFlow assists with that first review. You choose a sample or upload a fictional invoice, click Analyze, and receive an organized report. You can see where each value came from, inspect issues, leave a review note, and download the report. A person still makes the review decision.

For example, an invoice says:

| Item | Amount |
|---|---|
| Research service | USD 500.00 |
| Data preparation service | USD 300.00 |
| Stated subtotal | USD 800.00 |
| Stated tax amount | USD 80.00 |
| Stated total | USD 950.00 |

TaxFlow extracts those values, calculates USD 800.00 + USD 80.00 = USD 880.00, and flags that the stated total is USD 70.00 higher. Its recommended follow-up is to ask the sender to confirm or correct the invoice. It also checks for an invoice number, date, vendor, currency, and item details. The displayed tax amount is treated as an input; the app does not determine whether a tax rate or tax treatment is legally correct.

The finished product is a website with a document viewer and review report. It performs a workflow, including AI reading and Python checks. The initial problem is a hypothesis about document intake; no client interviews or real business impact are claimed.

## 2. Product goal and boundaries

User: a tax or finance operations analyst preparing invoice records for review.

User story: As an analyst, I want to review the extracted invoice details alongside their sources and any problems, so that I can prepare a reliable intake record and decide what needs follow-up.

Goal: reduce repetitive reading, copying, and checking while keeping the source and human decision visible. Time savings must be measured later; they are not a promised result.

Definition of intake: receiving a document and checking that it has usable information before it moves into another business process.

First version: English, USD invoices with one to five pages and no discounts, credits, shipping, or multiple tax components. A single stated tax amount is supported, including an explicit zero. Unsupported adjustment structures route to follow-up instead of an incorrect calculation.

TaxFlow is a demonstration of invoice intake assistance. It does not file taxes, calculate tax liability, pay invoices, certify compliance, or send messages. Use independent branding with no EY logo or implied EY affiliation.

## 3. Review decisions

The first PRD had useful evidence, tool calling, and evaluation requirements, but its one-day scope was too broad. This version makes the following decisions authoritative:

| Original issue | Revised decision |
|---|---|
| Phone and Replit instructions | Build locally in VS Code, save with GitHub, deploy through Streamlit Community Cloud |
| Three document types immediately | Invoice is the MVP; W-2 and 1099-NEC are later extensions |
| Upload only optional | Synthetic TXT upload is required; text-based PDF is the first extension |
| Complex field editing required | Review note and decision are required; field editing is an extension |
| Unclear approval behavior | Blocking issues prevent approval; findings remain visible after any decision |
| Agent retry budget inconsistent | At most six model requests per document, counting retries |
| Source quote treated as proof of accuracy | Verify source spans and score extracted values separately |
| Implied deployment and AI completion | Milestones explicitly distinguish UI demo, verified live agent, and published app |

## 4. Laptop setup and tool roles

| Tool | Role |
|---|---|
| VS Code with an AI coding assistant | Write, run, inspect, and debug the project on the laptop |
| Python | Implement the agent, validation, calculations, and evaluation |
| Streamlit | Turn the Python project into an interactive browser interface |
| Git and GitHub | Record changes and share the project source |
| Azure OpenAI | Preferred hosted AI model for live extraction and tool calling |
| Streamlit Community Cloud | Publish the app from its GitHub repository |

Replit and Copilot Studio are optional alternatives, not dependencies of this version. GitHub saves source; it does not itself run the Python web app through GitHub Pages.

Create a project folder and a Python virtual environment named .venv. The coding assistant should select a currently supported Python version compatible with all dependencies and the deployment host, record it in the README, and pin tested packages. Run locally using python -m streamlit run app.py and open the displayed localhost URL.

Use environment variables or a local .streamlit/secrets.toml for credentials. Provide a placeholder-only .streamlit/secrets.example.toml. Ignore .venv, local secrets, temporary uploads, and caches in Git. Do not commit keys or show their values in coding-agent chat.

## 5. Scope and milestones

| Milestone | Required behavior | Evidence |
|---|---|---|
| A Working interface | Six synthetic samples, source viewer, illustrative extraction, real Python checks | Local app runs without a key; mock status visible |
| B Verified live agent | Azure/provider extraction and genuine model function calls to Python tools | Successful live invoice run with actual tool trace |
| C Usable intake workflow | TXT upload, source references, review note, decision, JSON/CSV export | End-to-end sample and uploaded-file runs |
| D Evaluated portfolio app | Separate 24-case benchmark and published sample demo | Actual report, source repository, published URL |

Only claim live AI-agent functionality after milestone B. Milestone A alone is a UI and rules demonstration. The first-day target is A through D if accounts and credentials are available. Complete each stage before adding features.

Later extensions: text-based PDF upload, analyst field corrections with audit history, W-2 and 1099-NEC schemas, manual-versus-assisted timing study, and additional currencies. OCR, databases, external integrations, general chat, vector search, and multi-agent orchestration are outside the first version.

## 6. User journey and screens

1. Open TaxFlow. See Review invoice intake with source evidence, a short explanation, and the active mode.
2. Choose a synthetic sample. In private/local live mode, optionally upload a synthetic TXT file.
3. Read the source and select Analyze invoice. Status messages reflect actual work: Reading, Extracting, Checking, Preparing report.
4. Review vendor, invoice number/date, currency, item amounts, subtotal, tax, total, and any missing or inconsistent information.
5. Click a source reference beside a field to see the relevant page and numbered lines. The source viewer stays read-only.
6. Inspect recommended follow-up and the activity log showing executed tools. Add a review note if useful.
7. Choose Approve intake or Needs follow-up. Approval is enabled only when all required checks completed and there are no blocking findings. A document with issues can be exported as Needs follow-up.
8. Download CSV for a spreadsheet or JSON for another program. Before a decision, exports are labeled Unreviewed draft.

Desktop layout: source on the left, extracted record and findings on the right. Follow-up and review controls sit below. Use a light background, navy text, one restrained teal accent, and generous spacing. Detailed evaluation and About information can sit in separate tabs.

Use visible text labels as well as colors. Show specific errors with Retry or Reset where appropriate. Do not invent confidence percentages. At a phone viewport, stack the columns and make source references clickable without hover. Desktop is the primary design target.

Six development samples: clean invoice, missing invoice number, wrong total, wrong line-item total, instruction embedded in invoice text, and unsupported document. These are not evaluation cases.

## 7. Data model and checks

Required invoice fields under a fictional internal intake policy:

| Field | Type | Required check |
|---|---|---|
| vendor_name | String or null | Present and source-supported |
| invoice_number | String or null | Present and source-supported |
| invoice_date | ISO date or null | Unambiguous and parseable |
| currency | String or null | Explicit USD; do not infer from a dollar sign alone |
| line_items | List or null | At least one usable item |
| subtotal | Decimal string or null | Present, nonnegative, matches item sum |
| tax | Decimal string or null | Explicit amount, nonnegative; zero is valid |
| total | Decimal string or null | Present, nonnegative, matches subtotal plus tax |

Each item has description, quantity, unit_price, and stated line_total. Quantity is a positive decimal string. Monetary amounts are nonnegative decimal strings. Python Decimal performs arithmetic; round each calculated item total to cents with a documented rule, sum those rounded totals, and flag differences greater than USD 0.01. Use distinct finding codes for invalid amount, missing field, item mismatch, subtotal mismatch, total mismatch, unsupported currency, and unsupported structure.

All of those findings, unsupported evidence, and incomplete tool execution are blocking in v1. Use processing states Ready, Running, Complete, Failed, or Incomplete and separate review states Unreviewed, Approved intake, or Needs follow-up. Complete means processing finished; it can still contain blocking findings. Approval requires Complete with zero blocking findings.

When inputs needed for a check are missing or invalid, return Not checked with its reason. Do not turn a skipped check into a pass. Ambiguous dates and missing tax/currency remain null and route to follow-up.

Each extracted scalar value has evidence: document_id, page_number, line_start, line_end, exact quote, and verification status. Item fields need evidence too. Quotes must occur in the specified source span. Verify numeric/date normalization against cited text where practical; flag unsupported evidence. A matching quote alone does not establish that the chosen field interpretation is correct.

Result record: run_id, document_id, document_type (invoice or unsupported), extracted_fields, findings, check_results, checklist, workflow_status, review_status, review_note, tool_trace, and run_metadata. Keep processing completion separate from human approval. Unsupported documents route to follow-up without invented invoice fields.

Metadata: mode, provider, model/deployment, dataset/prompt/schema versions where applicable, timestamp, duration, and available token usage. Never fabricate cost or usage.

## 8. AI agent and Python tools

Pipeline: parse and number source lines → classify/extract with the model → validate schema and evidence → model tool loop → verified findings and checklist → human review.

Use typed Pydantic schemas. The model must choose tool calls through its actual function-calling interface. Python executes allowlisted tools, then returns their outputs to the model. A visible predetermined animation is not a live tool trace.

Tools:

- validate_intake(document_id) reads the current server-side draft and checks required fields, supported structure, evidence status, dates, currency, and numeric validity.
- reconcile_invoice(document_id) calculates expected item totals, subtotal, and total and returns comparisons or explicit skipped-check reasons.
- lookup_intake_policy(finding_codes) retrieves applicable rules from a bundled fictional policy with stable reference IDs. For a clean invoice it returns the normal review rule.

The document ID must resolve only to the current session's document. Tools read validated server-side state, not model-supplied invented amounts. No arbitrary code execution or external actions.

For supported invoices, require successful execution of all three tools. The model can call validation and reconciliation first, then policy lookup based on their findings. Hard limit: six model requests total, including initial extraction, schema repair, tool rounds, and transport retries. When budget is exhausted, mark the run incomplete; never approve it. Retry a transient error at most once within the same total budget.

Python findings are authoritative. A model summary cannot erase them. Assemble the final checklist from finding codes and policy references, with templated follow-up as a reliable fallback. If a model-written sentence has no supported finding or policy reference, exclude it. Trace shows tool name, bounded arguments, result summary, duration, and execution status, without private reasoning or credentials.

## 9. Demo and live modes

Illustrative demo: no credentials or inference requests. Clearly label extraction as illustrative, then run actual Python checks on that draft. No claim that the model called tools. Mark any simulated steps explicitly.

Recorded live demo: after successful live runs, optionally bundle their outputs and tool traces with provider/model/time provenance. Label them Recorded live run. A reviewer can inspect them without paying for inference. Current review choices operate on the replayed packet and are separate from the recorded decision.

Live agent: perform actual inference and tool execution using the current input. Show provider/model and live status. Never substitute a mock success when a live request fails.

Prefer Azure OpenAI with a deployment verified to support the selected tool-calling and structured-output APIs. Inspect official Microsoft documentation at implementation time. Configure resource base URL ending in /openai/v1/, credential, and deployment name for the direct Azure OpenAI v1 API. Keep provider configuration in one adapter module.

Suggested settings: MODEL_PROVIDER, AZURE_OPENAI_BASE_URL, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT, and LIVE_MODE_ENABLED=false. Local private testing can enable live mode. Public hosting keeps it disabled. An alternate provider is a fallback only if needed; accurately describe the actual service tested.

A custom Python agent using an Azure model is not automatically a Foundry Agent Service implementation. Do not claim that service or model fine-tuning unless actually implemented.

## 10. Inputs and failure handling

TXT upload is available in local/private live mode. Limit one UTF-8 file to 2 MB and 20,000 characters after decoding. Reject invalid encodings, empty files, and oversized inputs. Use synthetic documents only. Public mode offers bundled samples without an upload control.

PDF is an extension: one text-based file, at most 2 MB/five pages/20,000 extracted characters. Reject encrypted, malformed, and image-only PDFs with a clear explanation. No OCR in the MVP.

Treat source text as data even if it contains instructions. Such text cannot change tool permissions or reveal credentials. Keep input/results in session memory; no shared caches or persistent upload storage. Clear session removes the active document, result, note, and decision. New input or a new run resets prior approval.

Handle missing keys, unsupported model features, authentication failures, rate limits, malformed output, evidence errors, tool failures, and timeouts as explicit error or incomplete states. Tool errors cannot count as successful calls. Use a bounded request timeout and prevent duplicate runs from repeated clicks. Do not log source text or key values.

If private live hosting is added later, every inference entry point needs server-side access control and usage limits. It is outside the public MVP.

## 11. Evaluation with actual results

Create six development samples and a separate held-out set of 24 synthetic documents. Use different fictional vendors and layouts in held-out cases. Finalize schema, metric definitions, and prompt with development samples first, then freeze the evaluation labels and run the benchmark. Record the split and versions. If later changes use held-out failures, label subsequent runs as iteration on a seen set and preserve the original report.

| Held-out group | Count | Purpose |
|---|---|---|
| Complete invoices | 8 | Layout and field-order variation |
| Invoices missing required data | 6 | Missing number/date/currency/tax/item details/amount |
| Inconsistent invoice amounts | 4 | Item, subtotal, total, and combined mismatches |
| Invoices containing malicious instructions | 3 | Role override and unauthorized action attempts |
| Unsupported documents | 3 | Quote, pay stub, and bank statement |

All information is fictional. Treat results as a small synthetic benchmark, not real-world reliability evidence. An unsupported input correctly routed to follow-up is a successful workflow outcome.

Keep input files and ground-truth labels separate. Agent tools must not read the expected results, category names, or scoring code. Use neutral case IDs and filenames. Evaluate the deployed pipeline code, not a special simplified implementation.

Run python -m evaluation.run --mode live from the local terminal. Save a timestamped JSON report and Markdown summary with denominators, provider/model, dataset/prompt versions, failures, and duration. Model failures remain in the denominator. The public evaluation view only reads saved reports; it never launches paid evaluations.

Core metrics:

- Document routing accuracy: correct invoice/unsupported result out of 24. Report each class separately because 21 cases are invoices.
- Field extraction accuracy: correct expected non-null scalar fields out of all expected non-null scalar fields on the 21 invoices. Define included item fields, item matching, and normalization in the runner before scoring. Missing predictions count as wrong. Separately count invented non-null values where the expected value is null.
- Missing-field detection: precision and recall from required-field finding codes. Define zero-denominator results explicitly.
- Arithmetic findings: exact expected mismatch-code set on each of the four inconsistent invoices; also report false positives on consistent invoices and skipped checks.
- Evidence validity: supported source references out of non-null predicted scalar fields. Show invalid or absent references; score value correctness separately.
- Workflow completion: supported cases with correct routing, extraction, null behavior, findings, valid evidence, required successful calls, and complete packet; unsupported cases correctly routed without invented extraction. Report successes out of 24 and by class.
- Attack-case outcomes: boundaries respected and no unauthorized action or disclosure, out of three cases. This is narrow test coverage, not a security certification.
- Latency: median and p95 for successful runs; failures and their durations separately.

Targets for iteration: at least 22/24 routing outcomes correct, at least 90% extraction accuracy, at least 90% missing-field recall, at least 20/24 workflow completions, and all three attack cases passing. Targets are not measured achievements or permission to fill in resume metrics. Preserve actual results even if targets are missed.

## 12. Acceptance criteria

1. A fresh local install starts the demo without a key or inference network calls.
2. A live supported invoice invokes all three Python tools through actual model calls and displays source-backed extraction and the execution trace.
3. The example with subtotal 800.00, tax 80.00, and total 950.00 flags expected total 880.00 and difference 70.00.
4. Missing/invalid data yields null or explicit findings; skipped checks are not passes.
5. Source references resolve correctly; fabricated or unsupported evidence is flagged.
6. New input or rerun resets review state. Blocking issues disable approval. Follow-up export retains findings and reviewer notes.
7. Exports include run/document IDs, mode, original extracted values, checks, findings, and review status. JSON retains nested items; CSV uses documented stable columns or separate item rows. Escape spreadsheet-formula prefixes in text cells.
8. Malformed input, failed model/tool calls, and exhausted budgets yield recoverable error/incomplete states with no fabricated live success.
9. Benchmark uses separated labels and writes honest denominators and failed-case details.
10. Public deployment works outside localhost with live mode disabled, no upload control, and clear replay/illustrative labels.

## 13. Deliverables and meaningful checks

Suggested project files: app.py, taxflow/models.py, taxflow/parsing.py, taxflow/providers.py, taxflow/agent.py, taxflow/tools.py, taxflow/evidence.py, taxflow/exports.py, policies/intake_policy.md, samples/, evaluation/cases/, evaluation/ground_truth/, evaluation/run.py, tests/, reports/, requirements.txt, .gitignore, and placeholder secrets example.

Use meaningful offline checks for Decimal arithmetic, absent/invalid fields, evidence verification, document scoping, budget exhaustion, approval blocking/reset, and exports. Separate credential-dependent live smoke tests from offline tests. A mocked provider does not establish agent accuracy.

README should explain the product to a new reader, local setup, modes, actual model service, tool behavior, evaluation and limitations, deployment, and extensions. Include a compact architecture diagram and a 60–90 second demo script: flawed invoice → extracted fields and sources → arithmetic finding → actual recorded/live tools → follow-up/export → evaluation results.

Completion report from the builder must distinguish implemented, locally tested, live verified, and deployed requirements. Do not claim deployment or accuracy based on prepared configuration alone.

## 14. Build sequence and deployment

Suggested focused-day sequence: build the interface and deterministic checks; connect the live model and tools; finish input/review/export; run the benchmark; fix material failures; publish the sample demo and document results. Budget roughly six to eight hours with AI assistance, assuming credentials are available. Additional time may be needed. Stop adding extensions when the core workflow, evidence, and real evaluation work.

Deployment steps:

1. Verify the local app and commit only source, fictional samples, tests, policies, and non-sensitive reports. Save changes to a GitHub repository; repository publishing is a distinct action from running locally.
2. In Streamlit Community Cloud, connect the GitHub repository, choose the branch, and set app.py as the entry point. Match the tested Python version and requirements.
3. Keep live inference disabled for the public portfolio version. No model credential is needed for that sample demo. If hosting live inference later, use the host's secret settings and private access controls.
4. Publish and open the resulting streamlit.app URL outside the development session. Test clean, incomplete, inconsistent, and unsupported samples, source references, review controls, and exports.
5. Record the repository URL, deployed URL, and verified revision in the README. Code updates can trigger deployment updates; verify the hosted version after changing dependencies or behavior.

The Azure model runs the AI inference; Streamlit hosting runs the website. Account access and publishing may require the user to sign in. If those steps are unavailable, deliver a working local app and precise remaining setup without claiming a published result.

## 15. Resume evidence after completion

Use only services and results actually verified:

- Built a Python AI agent using [actual model service] to extract source-backed invoice fields, call completeness and arithmetic-checking tools, and prepare human review reports for a synthetic finance workflow.
- Evaluated the workflow across 24 held-out synthetic documents, achieving [successful/24] task completion and [measured percentage] field extraction accuracy; published an interactive sample demo and documented failure cases.

Add Azure OpenAI only after a successful Azure live run. Add W-2/1099 support only after the extension is implemented and tested. Claim time savings only after timing manual and assisted review including correction effort. There are no real clients, adoption, or legal compliance claims in this prototype.

## 16–17. Build prompts

See the original PRD for the master prompt and one-step-at-a-time prompts (milestones A → D).

## 18. Official references

Reviewed September 30, 2026; verify SDK and hosting compatibility again during implementation.

- Microsoft model endpoint documentation: https://learn.microsoft.com/en-us/azure/foundry/foundry-models/concepts/endpoints
- Microsoft SDK and service distinctions: https://learn.microsoft.com/en-us/azure/foundry/how-to/develop/sdk-overview
- Streamlit deployment from GitHub: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy
- Streamlit secret management: https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management

This PRD describes a proposed build. The app, Azure integration, benchmark, and deployment have not been completed by writing this document.
