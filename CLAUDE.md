# CLAUDE.md — Pharmacy Invoice Automation System

This file is the operating manual for any AI assistant (Claude Code or
otherwise) working in this repository. It is built from two sources,
per an explicit, approved precedence rule (see "Precedence Rule" below):

- **`docs/`** — the full specification (Business Rules, Architecture,
  Domain Model, Technical Specification, Development Guide, Testing &
  Deployment). Written as the project's documentation baseline.
- **The actual, already-implemented codebase** — Domain Layer and
  Application Layer are **frozen**; Infrastructure Layer Phase 1
  (logging, configuration, file storage, persistence, DI) is
  **implemented and tested**. These layers embody real architectural
  decisions made *after* the documentation baseline was written.

## Precedence Rule (read this first)

> The documentation is the primary source of truth for **business
> requirements** and **overall architecture direction**. The current
> implementation already contains **approved architectural
> refinements** made after the documentation was written.
>
> **Do not redesign or roll back the implementation to match the
> documentation.** Treat the documentation as the baseline
> specification and the existing implementation decisions as approved
> evolutions of it.
>
> **Whenever the documentation and the implementation disagree on
> something structural** (an entity name, an aggregate boundary, a
> required field, a workflow step), **stop and ask before making any
> structural change** — in either direction. Do not silently pick a
> side. See "Documented Deviations" below for the ones already known;
> if you find a new one, add it to that list rather than resolving it
> unilaterally.

---

## 1. What This Project Is

An internal, production-grade Windows desktop application that
automates processing pharmaceutical **purchase invoices**: photograph
invoices → Gemini Vision OCR → AI-assisted structured extraction →
business validation → human review → automated data entry into
`webnhathuoc.com` (the pharmacy management website) via Playwright.

**Scale:** hundreds of invoices per dossier (a dossier spans ~3 years),
tens of thousands of invoices system-wide.

**Priority order (never violate this ordering):**
1. Accuracy
2. Reliability
3. Maintainability
4. Recoverability
5. Scalability
Speed is never optimized at the expense of correctness.

**This is not** an OCR product, an AI chatbot, or a browser-automation
tool in isolation — it is one integrated business workflow that
happens to use those technologies. Technology serves the workflow; it
never redefines it.

**Explicitly out of scope:** accounting software, tax declaration,
financial accounting, inventory management, replacing human approval.

---

## 2. Architecture (as actually implemented)

Clean Architecture + Domain-Driven Design, four layers, dependencies
point inward only:

```
Presentation → Application → Domain ← Infrastructure
```

- **Domain** (`src/pharmacy_invoice_automation/domain/`) — **FROZEN**.
  Entities, value objects, domain services, validators, repository and
  service ports. Zero dependencies on anything outside Domain +
  Python stdlib. Never imports sqlite3, Playwright, PySide6, an OCR
  SDK, or any concrete Infrastructure.
- **Application** (`.../application/`) — **implemented, currently
  being re-verified package-by-package** (audit in progress; do not
  add features here, only verify/test what exists). Use cases, CQRS
  commands/queries, DTOs, the workflow orchestrator, confidence
  pipeline, retry policy, job state machine. Depends only on Domain.
- **Infrastructure** (`.../infrastructure/`) — **Phase 1 implemented
  and tested** (logging, config/secrets, file storage, SQLite
  persistence + migrations + unit of work + all 6 repositories, a
  minimal DI container). OCR (Gemini) and Automation (Playwright)
  adapters are **still scaffolds** — next planned work.
- **Presentation** (`.../presentation/`) — scaffold only, not yet
  implemented (PySide6 desktop UI).
- **Composition Root** — scaffold only, not yet implemented (wires
  every layer together for the running app).

**Dependency rules (enforced, verified by import-graph tests every
stage):**
- Domain depends on nothing outside itself.
- Application depends only on Domain.
- Infrastructure implements ports Domain/Application define; it never
  contains business logic.
- Infrastructure never imports Presentation.
- No circular imports, anywhere.

**Tech stack:** Python 3.12, SQLite (WAL mode, foreign keys on),
Playwright, Google Gemini Vision (OCR), PySide6 (planned UI),
`cryptography`/Fernet for local secret encryption with an OS-keyring
primary path, `tomllib` + env vars for layered configuration.
`pydantic`/`keyring` are the originally-planned libraries for
config/secrets but are not installable in the current dev sandbox
(no network) — dataclass-based / Fernet-fallback substitutes are used
instead and are functionally equivalent; swap back if/when those
packages become available in the real environment.

---

## 3. Core Business Rules (condensed from `docs/Pack01_Business_Rules`)

These are business-tier rules and apply regardless of which layer
implements them.

**Workflow:** Receive Invoice → Organize Files → OCR → AI Extraction →
Business Validation → Human Review → Generate Approved/Ready Dataset →
Browser Automation → Verification → Completed.

**Human-in-the-loop is mandatory.** Automation never bypasses required
human validation. Human approval always overrides AI/OCR output.
Approved data is treated as immutable once approved.

**Never fabricate data.** If a value can't be extracted confidently,
flag for review — never guess, never invent. (Matches the already-built
"blocking issue vs. informational note" distinction in
`pipeline.party_matching_step` — routine catalog creation is *not* a
fabrication and does not by itself require review; genuine gaps do.)

**Medicine:** Required — Name, Unit, Quantity, Unit Price, VAT.
Optional — Batch, Expiry, Manufacturer. Never invent or guess medicine
data; unknown medicines require human review before creation (already
matches current auto-create-with-notification design — see Deviation
D6 below on whether creation itself should require review).

**Invoice:** Required — Invoice Number (unique), Invoice Date,
Supplier, at least one Purchase Item. Cannot be approved while
validation errors exist. Duplicate invoice numbers require human
review, not automatic rejection.

**Batch:** Batch Number, when present on the invoice, must be
preserved exactly (no reformatting) with only leading/trailing
whitespace trimmed. Not required to be unique within an invoice
(multiple items may share a batch). Expiry Date is optional; invalid
calendar dates (e.g. 31/02) fail validation. Low OCR confidence on
batch data routes to human review.

**Price:** Purchase Price is mandatory, numeric, must be > 0 — never
invented, always sourced from the invoice. VAT is mandatory; standard
allowed values are 0%, 5%, 8%, 10% (see Deviation D5 — current
`TaxType` enum categories don't cleanly cover 8% as a distinct case).
Retail Price is a **separate, optional** concept: it may be *suggested*
via a Long Châu price-reference lookup, but the operator always has
final authority, and the suggestion never overwrites an operator
decision (see Deviation D3 — no Retail Price field exists in the
current `PurchaseItem` entity, which only tracks the purchase-side
`unit_price`).

**Validation is read-only.** It never modifies data, only evaluates it
and assigns a severity (Critical → stop; High → human review; Medium →
warning, continue; Low → log only).

**Human Review:** triggered by — unknown supplier, unknown medicine,
missing required field, low OCR/AI confidence, validation failure,
duplicate invoice/medicine, price deviation beyond threshold. Reviewer
actions: Approve / Edit / Reject / Skip. New supplier/medicine creation
during review is expected, normal behavior, not an error state.

**Automation:** consumes only approved/validated data — never OCR
output, never raw AI output directly. One invoice processed at a time;
one line completed before the next begins. Every entered value is
verified against the approved source after entry; verification failure
stops processing (never silently continues). Retry is allowed only for
transient technical failures (network, slow page, browser hiccup) —
never for business/validation failures. Automation never modifies
approved values, never invents missing ones, never makes business
decisions.

**Error handling:** every error is classified (Business / Validation /
Technical / Infrastructure / External Service / Security /
Configuration / Unexpected) and logged; only Technical and External
Service errors are ever retried automatically (matches the existing
`TransientInfrastructureError` design exactly — do not extend
automatic retry to business/validation errors).

**Audit:** every significant action across OCR, AI extraction,
validation, review, and automation must be traceable. Audit records
are read-only/append-only once written.

**Configuration:** OCR/AI confidence thresholds, retry counts/delays,
browser timeout, review-required threshold, logging level, export/temp
folders must all be externally configurable, never hardcoded.

---

## 4. Naming & Coding Conventions (as actually used in this codebase)

- **Language:** Python throughout (the documentation's naming-guide
  examples are written for TypeScript/React — camelCase functions,
  `.ts` files, React hooks — and do **not** apply verbatim; PEP 8 /
  Python idiom governs instead, per the precedence rule).
- Classes: `PascalCase`. Files/functions/variables: `snake_case`.
  Constants: `UPPER_SNAKE_CASE`. Enum member names: `UPPER_SNAKE_CASE`;
  current enum *values* are lowercase strings (e.g.
  `InvoiceStatus.PENDING.value == "pending"`) — this is an intentional,
  existing choice, not an oversight.
- **No `I`-prefix on ports/interfaces** (`SupplierRepository`, not
  `ISupplierRepository`) — this already matches the documentation's own
  stated convention.
- **Domain objects carry no suffix** (`Supplier`, `PurchaseItem`,
  `Batch`, `Medicine` — not `SupplierEntity`/`SupplierModel`).
  Repositories carry `Repository`; DTOs carry `DTO`
  (`PurchaseInvoiceDTO`).
- **Current aggregate root is named `PurchaseInvoice`**, not `Invoice`
  — see Deviation D1. Use `PurchaseInvoice`/`PurchaseItem` consistently
  everywhere in code; do not introduce `Invoice` as an alternate name
  without an explicit decision to rename (a real, tracked migration,
  not an incidental one).
- SOLID, DRY, KISS, YAGNI. Prefer composition over inheritance; avoid
  inheritance deeper than two levels. Prefer immutable objects
  (frozen dataclasses with tuple/`MappingProxyType` fields, as already
  used throughout Domain/Application).
- **No placeholder code** — no bare `TODO`, `pass`, `raise
  NotImplementedError`, or silently-wrong `return None` in anything
  presented as finished. If something is genuinely out of scope for
  the current stage, it stays an explicit, documented scaffold — not a
  silent stub pretending to be real.
- Comments explain *why*, not *what*. No dead code, no commented-out
  code, no magic numbers/strings (use named constants/enums — already
  the pattern in `domain/constants.py` and `application/configuration.py`).
- Empty catch/except blocks are prohibited. Every exception is
  handled, logged, or intentionally propagated — never silently
  swallowed.
- Dependencies are injected via constructor parameters, never
  constructed internally by the class that uses them (already the
  pattern throughout Application/Infrastructure).

---

## 5. Git Workflow

- Branches: `main` (protected), `feature/*`, `bugfix/*`, `hotfix/*`,
  `docs/*`, `chore/*`. No direct commits to `main`.
- Commit format: `type(scope): summary` — types: `feat`, `fix`,
  `refactor`, `docs`, `style`, `test`, `build`, `ci`, `perf`, `chore`,
  `revert`. Example: `feat(persistence): add batch repository`.
- Commits are atomic, one purpose each, and should pass local
  validation (compile + relevant tests) before committing.
- **AI-generated code is committed to feature branches only, reviewed
  before merge, never pushed directly to `main`.** If using Claude
  Code interactively: auto-commit locally is fine; keep `git push`
  behind explicit confirmation.

---

## 6. AI Assistant Rules (non-negotiable)

1. Read relevant documentation (`docs/`) *and* the current code before
   implementing anything.
2. Never invent business rules. Never redesign the workflow or
   architecture without explicit approval.
3. Never rename an already-approved domain concept (e.g. don't rename
   `PurchaseInvoice` back to `Invoice`) without an explicit, tracked
   decision to do so.
4. Ask when requirements are ambiguous or when documentation conflicts
   with implementation — see the Precedence Rule above. Prefer
   correctness over assumptions.
5. Domain and Application layers are frozen/under audit — do not
   modify them to "fix" a documentation mismatch; flag it instead (add
   to Documented Deviations below).
6. Every implementation phase ends with real, executed validation
   (compile, import-graph check, and functional tests against real
   inputs — not just "it compiles"). This project's history shows
   real bugs are reliably found this way; skipping it isn't optional.
7. Work in small, independently-reviewable packages/phases, matching
   how this project has been built so far — not one large,
   context-exhausting pass.

---

## 7. Documented Deviations (Documentation ↔ Implementation)

Per the precedence rule: **none of these should be silently resolved.**
Each is flagged for an explicit decision before any structural change.

| # | Documentation says | Implementation has | Status |
|---|---|---|---|
| D1 | Aggregate root and all references are named **`Invoice`** ("no alternative naming is permitted") | Named **`PurchaseInvoice`** throughout Domain/Application (an intentional rename made during a prior stage) | Keep `PurchaseInvoice` — do not rename without an explicit decision |
| D2 | `Batch` is a simple value bundle (Batch Number + Expiry + Manufacture Date) owned 1:1 by a `PurchaseItem`; "Purchase Item must contain one Batch" (mandatory) | `Batch` is an independent aggregate root with its own repository, `quantity_received`, `manufacturer_id`, and optimistic-concurrency `version`; `PurchaseItem.batch_id` is **optional** | Keep current richer model — flag for discussion whether Batch should become mandatory-per-item |
| D3 | Distinct **Purchase Price** (from invoice, mandatory) vs. **Retail Price** (optional, Long Châu-suggested, operator-confirmed) as two separate fields | `PurchaseItem` has only one price field (`unit_price`) — no Retail Price concept exists | Real gap — needs a decision: add a Retail Price field, or confirm retail pricing is out of this system's scope entirely |
| D4 | Medicine has a `registrationNumber` (regulatory registration) field | `Medicine` entity has no such field (`specification` is the closest free-text field) | Flag — confirm whether registration number tracking is actually needed |
| D5 | VAT allowed values are literally 0%, 5%, 8%, 10% | **Resolved 2026-08 (PO-confirmed):** `TaxType` gained a fifth member, `EIGHT_PERCENT` (value `"eight_percent"`, rate `0.08`), added alongside the existing four rather than folded into `REDUCED` — 8% is Vietnam's 10% `STANDARD` rate temporarily cut under stimulus decrees, not a permanent goods category like the 5% `REDUCED` rate. `OTHER` keeps its original role as the fallback for genuinely unusual rates. No DB migration needed (`purchase_items.tax_type` is a plain `TEXT` column). Historical rows already stored as `"other"` are not retroactively reclassified. | Closed |
| D6 | New Supplier/Medicine creation happens under "Human Review," implying a review context | Current design treats routine auto-creation as an **informational note**, not a review-forcing issue (deliberate fix made after finding this exact conflation would flood the review queue) | Keep current behavior — this was a deliberately corrected design, not an oversight |
| D7 | "Excel Dataset"/"Approved Dataset" appears throughout Business Rules as if it were a literal exported file automation reads from | **Resolved 2026-08 (PO reversal, final):** the earlier "just an internal data contract, not a literal file" reading of `TS-006` was wrong for the human REVIEW step specifically. `export-review`/`import-review` CLI commands (`composition_root/review_excel.py`) now produce and consume a real `.xlsx` (one row per line item) so a PO can batch-review many `UNDER_REVIEW` invoices in Excel instead of one at a time via the PowerShell-interactive `review` command (kept, unremoved, still useful for a single ad-hoc invoice). Every correction/decision in the sheet is applied through the exact same, unmodified `SubmitInvoiceReviewUseCase` the interactive flow already used — no business logic was duplicated. This does **not** extend to automation itself: `PlaywrightBrowserAutomationProvider` still reads the validated `PurchaseInvoice` directly from SQLite once an invoice reaches `READY_FOR_IMPORT`, exactly as `TS-006` described — only the human-review handoff step gained a literal file. | Closed |
| D8 | Logging categories include VALIDATION, REVIEW, API, SYSTEM, CONFIGURATION as distinct categories; a single Correlation ID should propagate end-to-end across the whole pipeline | `LoggerFactory` currently has 6 categories (ocr, gemini_api, automation, database, error, retry); no end-to-end Correlation ID exists yet | Real gap — worth addressing when Composition Root / OCR phase is built, not urgent now |
| D9 | `Pack05_Development_Guide`'s Project Structure (`DG-001`) and Naming Conventions (`DG-003`) describe a TypeScript/React `apps/frontend` + `apps/backend` + `package.json` monorepo | Actual project is a single Python desktop app (`pyproject.toml`, `src/pharmacy_invoice_automation/...`) | These two documents appear to be generic/templated and do not apply to this project's real stack — follow the actual Python structure, not `DG-001`/`DG-003`'s literal examples |
| D10 | An invoice's stated grand total should reconcile against its own validated line items (implicit in the Business Rules' total-consistency requirement) | **Resolved 2026-08 (PO-confirmed, final — no exceptions):** the VAT!=5% exclusion (`SupplementClassificationService`/`PartyMatchingStep`) is deliberate, correct filtering, not an anomaly, and must never itself cause a false "does not reconcile." `PartyMatchingOutcome` now carries `excluded_supplement_total` (the tax-inclusive sum of every line removed for VAT!=5%, captured before removal), threaded through `ProcessInvoiceUseCase` into `InvoiceValidationStep.execute()`, which passes it to `InvoiceCalculationService.calculate_reconciled_grand_total(invoice, excluded_supplement_total)` — added back on top of (remaining items with tax, minus CKTM) before comparing against `raw_grand_total`. Verified against the real invoice (`invoice.pdf`, Traphaco #00000874): "does not reconcile" no longer fires; the residual gap is 1,345 VND (0.41%), well inside the 1% tolerance and fully explained by CKTM's own untracked tax portion (see D-CKTM's `calculate_reconciled_grand_total` docstring) — not an unexplained mismatch. | Closed |

*Full reading note: this CLAUDE.md was built from a complete read of
`Pack01_Business_Rules`, `Pack02_Architecture` (overview + system
architecture), `Pack03_Domain_Model`, `Pack04_Technical_Specification`
(Web Automation + Data Exchange specs), and `Pack05_Development_Guide`
(Coding Standards, Naming, Project Structure, Error Handling, Logging,
Git Workflow). `Pack04`'s remaining specs (OCR, AI Extraction,
Validation, Review, Configuration) and all of `Pack06_Testing_Deployment`
were not yet cross-checked against code in detail — consult them
directly when their respective implementation phases begin (OCR/Gemini,
Testing/CI setup).*
