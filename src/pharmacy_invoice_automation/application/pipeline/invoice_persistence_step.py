"""
Pipeline Step: InvoicePersistenceStep.

Persists an invoice and any newly-created Supplier/Medicine records
atomically via ports.TransactionCoordinator, satisfying Stage 05's
Transaction Coordinator requirement (#13): "Entire invoice succeeds, or
entire invoice fails. Avoid partial persistence."
"""

from __future__ import annotations

from collections.abc import Sequence

from pharmacy_invoice_automation.application.ports.transaction_coordinator import (
    TransactionCoordinator,
)
from pharmacy_invoice_automation.domain.entities.medicine import Medicine
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.entities.supplier import Supplier
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)


class InvoicePersistenceStep:
    """Atomically persists an invoice together with any new suppliers/medicines it needed."""

    def __init__(
        self,
        purchase_invoice_repository: PurchaseInvoiceRepository,
        supplier_repository: SupplierRepository,
        medicine_repository: MedicineRepository,
        transaction_coordinator: TransactionCoordinator,
    ) -> None:
        self._purchase_invoice_repository = purchase_invoice_repository
        self._supplier_repository = supplier_repository
        self._medicine_repository = medicine_repository
        self._transaction_coordinator = transaction_coordinator

    def execute(
        self,
        invoice: PurchaseInvoice,
        new_suppliers: Sequence[Supplier],
        new_medicines: Sequence[Medicine],
        is_new_invoice: bool,
    ) -> None:
        """
        Persist everything in one unit of work: new suppliers, new
        medicines, and the invoice itself (created or updated). If any
        step raises, nothing here is durably committed.
        """

        def unit_of_work() -> None:
            for supplier in new_suppliers:
                self._supplier_repository.add(supplier)
            for medicine in new_medicines:
                self._medicine_repository.add(medicine)
            if is_new_invoice:
                self._purchase_invoice_repository.add(invoice)
            else:
                self._purchase_invoice_repository.update(invoice)

        self._transaction_coordinator.run_in_transaction(unit_of_work)
