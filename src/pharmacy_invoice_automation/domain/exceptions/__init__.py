"""
Domain exception hierarchy. Every exception here derives from
DomainError.

Renamed/added per Stage 04: InvalidInvoiceDataError -> InvalidInvoiceError;
added ValidationError, SupplierNotFoundError, MedicineNotFoundError.
DuplicateSupplierError and InvalidBusinessRuleError are retained
unchanged from the prior Domain Layer build.
"""

from pharmacy_invoice_automation.domain.exceptions.domain_error import DomainError
from pharmacy_invoice_automation.domain.exceptions.duplicate_invoice_error import (
    DuplicateInvoiceError,
)
from pharmacy_invoice_automation.domain.exceptions.duplicate_medicine_error import (
    DuplicateMedicineError,
)
from pharmacy_invoice_automation.domain.exceptions.duplicate_supplier_error import (
    DuplicateSupplierError,
)
from pharmacy_invoice_automation.domain.exceptions.invalid_business_rule_error import (
    InvalidBusinessRuleError,
)
from pharmacy_invoice_automation.domain.exceptions.invalid_invoice_error import (
    InvalidInvoiceError,
)
from pharmacy_invoice_automation.domain.exceptions.medicine_not_found_error import (
    MedicineNotFoundError,
)
from pharmacy_invoice_automation.domain.exceptions.supplier_not_found_error import (
    SupplierNotFoundError,
)
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError

__all__ = [
    "DomainError",
    "ValidationError",
    "InvalidInvoiceError",
    "DuplicateSupplierError",
    "DuplicateMedicineError",
    "DuplicateInvoiceError",
    "SupplierNotFoundError",
    "MedicineNotFoundError",
    "InvalidBusinessRuleError",
]
