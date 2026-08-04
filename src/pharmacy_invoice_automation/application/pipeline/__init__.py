"""
Pipeline Steps: internal orchestration collaborators composed by
use_cases.process_invoice_use_case.ProcessInvoiceUseCase.

Design note (in place of separate ExtractInvoiceUseCase,
ValidateInvoiceUseCase, MatchMedicineUseCase, SaveInvoiceUseCase top-level
use cases): these four concerns are genuinely sequential stages of ONE
workflow -- processing a single invoice -- not four independently
driven use cases with their own external callers. Promoting each to a
top-level Use Case would mean re-implementing the same error handling,
retry wrapping, and job-state bookkeeping four times, and would spread
one cohesive unit of work across four public entry points nothing ever
calls independently. Composing them as small, single-responsibility,
independently-testable Step collaborators behind one public Use Case
satisfies every one of Stage 05's actual requirements (extraction,
validation, matching, persistence all happen, each with its own class
and its own tests) while avoiding both a God Object (one giant method
doing everything inline) and duplicated orchestration (four classes
each re-wrapping the same retry/error-handling logic).
"""
