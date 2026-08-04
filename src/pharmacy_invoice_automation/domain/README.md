# Domain Layer (Package 01) -- REBUILT (Stage 04, redo)

**Note:** this Domain Layer was rebuilt against a revised Stage 04
prompt that materially diverges from the originally-approved Technical
Design Document / Implementation Blueprint / Implementation
Specification (renamed aggregate, two new entities, a new Domain
Services layer, class-based Validators, new Shared Interfaces, revised
enums/exceptions/ports). See the top-level `domain/__init__.py`
docstring and this project's chat history for the full list of
resolved discrepancies. `Project`, `TaxCode`, and `ExpiryDate` were
retained beyond the new prompt's explicit examples because unchanged
prior requirements (FR-01, supplier tax-code validation) still need them.

## Contents

| Subpackage | Contents |
|---|---|
| `entities/` | `PurchaseInvoice` (aggregate root), `PurchaseItem`, `Supplier`, `Medicine`, `Batch`, `Manufacturer`, `Project` |
| `value_objects/` | `Money`, `Quantity`, `Unit`, `OCRResult`/`OCRLineItem`, `Address`, `DateRange`, `TaxCode`, `ExpiryDate` |
| `enums/` | `InvoiceStatus`, `MedicineType`, `TaxType`, `OCRStatus`, `WorkflowState` |
| `exceptions/` | `DomainError` (base) + 8 specific exceptions |
| `events/` | `DomainEvent` (base) + `InvoiceCreated`, `MedicineAdded`, `SupplierCreated`, `OCRCompleted` |
| `validators/` | `InvoiceValidator`, `SupplierValidator`, `MedicineValidator` (class-based completeness checks) |
| `services/` | `InvoiceCalculationService`, `MedicineValidationService`, `PurchasePolicy`, `PricePolicy`, `TaxCalculationService` (Domain Services) |
| `ports/repositories/` | `PurchaseInvoiceRepository`, `MedicineRepository`, `SupplierRepository`, `BatchRepository`, `ManufacturerRepository`, `ProjectRepository` |
| `ports/services/` | `OCRProvider`, `BrowserAutomationProvider`, `AIProvider`, `FileStorageProvider`, `PriceLookupProvider`, `NotificationProvider` |
| `shared_interfaces/` | `Identifiable`, `Timestamped`, `Auditable`, `Versionable` (Protocol-based) |
| `constants.py` | Shared business-rule constants |

## Validated

- Zero forbidden imports (no `sqlite3`, `playwright`, `PySide6`, `httpx`, `pydantic`, etc.)
- Every one of 70 domain submodules imports cleanly in isolation (no circular dependencies)
- Comprehensive functional smoke test: entity construction/validation,
  Protocol structural typing (`isinstance` against `Auditable`/`Versionable`
  without inheritance), the status state machine, all 5 Domain Services,
  all 3 Validators, and the new value objects (`Unit`, `DateRange`, `OCRResult`)
- No TODO/placeholder/stub code anywhere; every non-`__init__` file has a docstring

**Next:** a future Application-layer stage builds against these now-frozen ports.
