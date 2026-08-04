"""
Concrete SQLite repository implementations of every Domain repository
port: SqliteProjectRepository, SqliteSupplierRepository,
SqliteMedicineRepository, SqliteBatchRepository,
SqliteManufacturerRepository, SqlitePurchaseInvoiceRepository.
"""

from pharmacy_invoice_automation.infrastructure.persistence.sqlite_repositories import (
    batch_repository,
    manufacturer_repository,
    medicine_repository,
    project_repository,
    purchase_invoice_repository,
    supplier_repository,
)

SqliteBatchRepository = batch_repository.SqliteBatchRepository
SqliteManufacturerRepository = manufacturer_repository.SqliteManufacturerRepository
SqliteMedicineRepository = medicine_repository.SqliteMedicineRepository
SqliteProjectRepository = project_repository.SqliteProjectRepository
SqlitePurchaseInvoiceRepository = purchase_invoice_repository.SqlitePurchaseInvoiceRepository
SqliteSupplierRepository = supplier_repository.SqliteSupplierRepository

__all__ = [
    "SqliteProjectRepository",
    "SqliteSupplierRepository",
    "SqliteMedicineRepository",
    "SqliteBatchRepository",
    "SqliteManufacturerRepository",
    "SqlitePurchaseInvoiceRepository",
]
