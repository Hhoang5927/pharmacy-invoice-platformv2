# Application Layer (Package 02) -- IMPLEMENTED (Stage 05)

Orchestrates workflows, coordinates use cases, manages transactions,
handles retries, coordinates external services (through Domain's
ports), and validates execution flow. Contains **no business rules** --
every rule lives in `domain.rules`/`validators`/`services`.

## Design decisions worth knowing

- **Four pipeline Steps, not four top-level Use Cases.** Extraction,
  matching, validation, and persistence are internal collaborators
  composed by one `ProcessInvoiceUseCase`, not separate public entry
  points. See `pipeline/__init__.py`.
- **Retries are scoped to `InvoiceExtractionStep`, not the batch loop.**
  Domain's `InvoiceStatus` state machine has no path back from
  `OcrDone` to `OcrInProgress` -- retrying the *whole* pipeline after
  the invoice had already advanced would attempt an invalid transition.
  Retries happen entirely around the one OCR call, before any status
  transition past `OcrInProgress` succeeds. See that module's docstring.
- **"New supplier/medicine created" is a note, not a blocking issue.**
  The Business Rules describe resolve-or-create as fully automatic;
  treating routine catalog creation as a review-forcing issue would
  flood the Human Review Queue with correct, expected work. Only
  genuine problems (nothing resolved, AI-fallback-derived data) block.
- **Three Application-owned ports** (`TransactionCoordinator`,
  `EventDispatcher`, `InvoiceImageRegistry`) exist here rather than
  under `domain.ports` only because this stage's write-scope is
  `src/application/**` (domain/ is read-only this stage).

## Contents

| Module/Subpackage | Contents |
|---|---|
| `results.py` | `UseCaseResult[T]` -- rich outcome (errors/warnings/statistics/confidence) |
| `exceptions.py` | `ApplicationError`, `TransientInfrastructureError`, `InvoiceProcessingError`, `BatchProcessingError` |
| `configuration.py` | `RetryPolicy`, `ConfidenceThresholds`, `BatchOptions` |
| `dto.py` | Immutable read-models -- Domain entities are never exposed directly |
| `commands.py` / `queries.py` | CQRS request objects |
| `query_handlers.py` | Read-side handlers for the three queries |
| `job_state.py` | `JobState` orchestration state machine + `InvoiceJob` |
| `batch_progress.py` | Live progress tracker with ETA |
| `confidence_evaluator.py` | Confidence Pipeline (Auto Accept/Highlight/Review) |
| `batch_orchestrator.py` | The Workflow Orchestrator |
| `in_memory_invoice_image_registry.py` | Default `InvoiceImageRegistry` |
| `ports/` | `TransactionCoordinator`, `EventDispatcher`, `InvoiceImageRegistry` |
| `events/` | Default `InMemoryEventDispatcher` |
| `pipeline/` | 4 Step collaborators composed by `ProcessInvoiceUseCase` |
| `use_cases/` | `ImportInvoiceBatchUseCase`, `ProcessInvoiceUseCase`, `ResumeBatchUseCase`, `SubmitInvoiceReviewUseCase`, `ExportBatchResultsUseCase` |

## Validated

- Zero forbidden imports (no PySide6/Playwright/OCR-SDK/sqlite3/pydantic/etc.)
- Zero circular imports (all 29 submodules import cleanly in isolation)
- Zero unused imports, missing type annotations, or `type: ignore` shortcuts
- Zero lines over 100 chars
- **6 end-to-end functional test scenarios pass**, wired with in-memory
  fakes of every Domain port (no Infrastructure exists yet): auto-accept
  path, all 3 query handlers, low-confidence review routing + human
  approval, transient-failure retry, batch resume, and export
  (including a cleanly-rejected unsupported format)
- 5 real bugs found and fixed via this testing (not just claimed clean):
  a missing type annotation, a broken datetime call, an event-dispatch
  architecture flaw, a blocking/informational issue conflation that
  would have flooded the review queue, and an invalid Domain state
  transition that revealed a genuine retry-scope design flaw

**Next:** a future Infrastructure stage builds concrete implementations
of every Domain and Application port; a future Presentation stage
builds the PySide6 UI against these use cases.
