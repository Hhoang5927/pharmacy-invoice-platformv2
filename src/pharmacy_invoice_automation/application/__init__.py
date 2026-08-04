"""
Application layer -- orchestrates workflows, coordinates use cases,
manages transactions, handles retries, coordinates external services
(through Domain's ports), and validates execution flow. Contains no
business rules: every rule lives in domain.rules/validators/services.

Depends only on domain.* and the Python standard library. Never
imports PySide6, Playwright, an OCR/Gemini SDK, sqlite3, or any
concrete infrastructure implementation -- every external capability is
reached exclusively through a domain.ports.services port or an
application.ports abstraction, injected by whatever composes this
layer (a future Composition Root stage).

Top-level modules:
    results          -- UseCaseResult[T], the rich outcome every use case returns
    exceptions       -- ApplicationError hierarchy, incl. TransientInfrastructureError
    configuration    -- RetryPolicy, ConfidenceThresholds, BatchOptions
    dto              -- immutable read-models crossing the Application boundary
    commands         -- CQRS command (write-intent) objects
    queries          -- CQRS query (read-intent) objects
    query_handlers   -- read-side handlers for the three queries above
    job_state        -- JobState (orchestration-level state machine) + InvoiceJob
    batch_progress   -- BatchProgress, the live progress tracker
    confidence_evaluator -- the Confidence Pipeline (Auto Accept/Highlight/Review)
    batch_orchestrator   -- the Workflow Orchestrator (batch iteration, failure
                isolation, pause/resume/stop; per-invoice retry lives in
                pipeline.invoice_extraction_step -- see that module's docstring for why)
    in_memory_invoice_image_registry -- default InvoiceImageRegistry implementation

Subpackages:
    ports    -- Application-owned abstractions (TransactionCoordinator,
                EventDispatcher, InvoiceImageRegistry) -- see ports/__init__.py
                for why these live here rather than under domain.ports
    events   -- default, zero-infrastructure EventDispatcher implementation
    pipeline -- internal Step collaborators composed by ProcessInvoiceUseCase
                (see pipeline/__init__.py for why these are Steps, not
                separate top-level use cases)
    use_cases -- the five public entry points: ImportInvoiceBatchUseCase,
                ProcessInvoiceUseCase, ResumeBatchUseCase,
                SubmitInvoiceReviewUseCase, ExportBatchResultsUseCase
"""
