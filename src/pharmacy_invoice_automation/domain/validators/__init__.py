"""
Reusable business validators: class-based completeness checks that go
beyond entity construction-time invariants, answering "is this ready
for the next pipeline step?" rather than "is this internally
consistent?".

Replaces the prior domain.rules package (pure functions) per Stage 04's
"Validators" and "Domain Services" split: structural/completeness
checks live here as Validators; cross-entity policy decisions live in
domain.services as Domain Services.
"""

from pharmacy_invoice_automation.domain.validators.invoice_validator import (
    InvoiceValidationReport,
    InvoiceValidator,
)
from pharmacy_invoice_automation.domain.validators.medicine_validator import (
    MedicineValidationReport,
    MedicineValidator,
)
from pharmacy_invoice_automation.domain.validators.supplier_validator import (
    SupplierValidationReport,
    SupplierValidator,
)

__all__ = [
    "InvoiceValidator",
    "InvoiceValidationReport",
    "SupplierValidator",
    "SupplierValidationReport",
    "MedicineValidator",
    "MedicineValidationReport",
]
