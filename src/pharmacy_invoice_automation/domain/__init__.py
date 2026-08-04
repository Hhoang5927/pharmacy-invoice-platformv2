"""
Domain layer -- entities, value objects, enums, exceptions, domain
events, validators, domain services, and ports.

Depends on nothing outside the Python standard library, except for
shared.result.Result (a generic, zero-business-logic Result/Outcome
type -- see shared/result.py for why this one dependency is necessary
and intentional).

Rebuilt per Stage 04 (redo): entities renamed (Invoice ->
PurchaseInvoice, InvoiceLine -> PurchaseItem), two new entities (Batch,
Manufacturer), a new Domain Services layer, class-based Validators
replacing the prior free-function rules, and new Protocol-based Shared
Interfaces. Project, TaxCode, and ExpiryDate are retained beyond Stage
04's explicit examples because unchanged prior requirements (FR-01,
supplier tax-code validation) still need them.

Subpackages:
    entities          -- PurchaseInvoice, PurchaseItem, Supplier,
                          Medicine, Batch, Manufacturer, Project
    value_objects      -- Money, Quantity, Unit, OCRResult, Address,
                          DateRange, TaxCode, ExpiryDate
    enums              -- InvoiceStatus, MedicineType, TaxType,
                          OCRStatus, WorkflowState
    exceptions         -- DomainError and 8 specific exceptions
    events             -- DomainEvent and 4 specific events
    validators         -- InvoiceValidator, SupplierValidator,
                          MedicineValidator
    services           -- 5 Domain Services (see domain.services docstring)
    ports.repositories -- 6 Repository Port interfaces
    ports.services     -- 6 External Service Port interfaces
    shared_interfaces  -- Identifiable, Timestamped, Auditable, Versionable

Module:
    constants          -- shared business-rule constants
"""
