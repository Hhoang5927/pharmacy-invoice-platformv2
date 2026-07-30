"""
Domain Services: business logic that spans more than one entity and
therefore does not naturally belong to any single one of them (Stage 04).

    TaxCalculationService        -- VAT computation by TaxType
    InvoiceCalculationService    -- derived invoice totals, incl. tax
    PricePolicy                  -- total-consistency + price-source policy
    MedicineValidationService    -- cross-catalog medicine classification/coding
    PurchasePolicy                -- supplier/medicine resolution + duplicate checks

Replaces the prior domain.rules package (free functions); see each
service's own docstring for exactly which prior rule it folds in.
"""

from pharmacy_invoice_automation.domain.services.invoice_calculation_service import (
    InvoiceCalculationService,
)
from pharmacy_invoice_automation.domain.services.medicine_validation_service import (
    MedicineValidationService,
)
from pharmacy_invoice_automation.domain.services.price_policy import PricePolicy
from pharmacy_invoice_automation.domain.services.purchase_policy import (
    MedicineResolution,
    PurchasePolicy,
    SupplierResolution,
)
from pharmacy_invoice_automation.domain.services.tax_calculation_service import (
    TaxCalculationService,
)

__all__ = [
    "TaxCalculationService",
    "InvoiceCalculationService",
    "PricePolicy",
    "MedicineValidationService",
    "PurchasePolicy",
    "SupplierResolution",
    "MedicineResolution",
]
