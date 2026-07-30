"""
Repository Ports: abstract persistence contracts, one per aggregate root.

Per Stage 04's explicit examples: PurchaseInvoiceRepository,
MedicineRepository, SupplierRepository, BatchRepository. Added beyond
that list, for DDD consistency and unchanged prior requirements:
ManufacturerRepository, ProjectRepository.
"""

from pharmacy_invoice_automation.domain.ports.repositories.batch_repository import (
    BatchRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.manufacturer_repository import (
    ManufacturerRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.project_repository import (
    ProjectRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)

__all__ = [
    "PurchaseInvoiceRepository",
    "MedicineRepository",
    "SupplierRepository",
    "BatchRepository",
    "ManufacturerRepository",
    "ProjectRepository",
]
