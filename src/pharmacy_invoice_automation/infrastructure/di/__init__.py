"""
Dependency Injection: ServiceContainer (a minimal type-to-instance
registry) and register_infrastructure_services (wires every concrete
Infrastructure adapter built in Phase 1 against its abstract port).
"""

from pharmacy_invoice_automation.infrastructure.di.registration import (
    register_infrastructure_services,
)
from pharmacy_invoice_automation.infrastructure.di.service_container import (
    ServiceContainer,
    ServiceNotRegisteredError,
)

__all__ = ["ServiceContainer", "ServiceNotRegisteredError", "register_infrastructure_services"]
