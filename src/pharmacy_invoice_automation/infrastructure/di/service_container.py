"""
ServiceContainer: a minimal, generic type-to-instance registry.

Deliberately simple (register/resolve against a Python type, singleton
or factory) rather than a full-featured IoC framework -- Stage 06
explicitly asks to avoid unnecessary abstractions, and this
application's actual need is "let registration.py wire concrete
Infrastructure adapters to the abstract ports Domain/Application
declare, so a later Composition Root stage can resolve them by type."
Nothing more elaborate than that is required yet.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar, cast

TService = TypeVar("TService")


class ServiceNotRegisteredError(Exception):
    """Raised when resolve() is called for a type nothing has registered."""

    def __init__(self, service_type: type) -> None:
        super().__init__(f"No service registered for {service_type!r}.")
        self.service_type = service_type


class ServiceContainer:
    """Minimal type-to-instance/factory registry."""

    def __init__(self) -> None:
        self._singletons: dict[type, object] = {}
        self._factories: dict[type, Callable[[], object]] = {}

    def register_instance(
        self, service_type: type[TService], instance: TService
    ) -> None:
        """Register an already-constructed instance as the resolution for ``service_type``."""
        self._singletons[service_type] = instance

    def register_factory(
        self, service_type: type[TService], factory: Callable[[], TService]
    ) -> None:
        """
        Register a factory called once per resolve() -- use this
        instead of register_instance() when a fresh instance is wanted
        each time (rare in this single-connection desktop application,
        but supported for completeness).
        """
        self._factories[service_type] = factory

    def resolve(self, service_type: type[TService]) -> TService:
        """
        Return the registered instance or factory-produced instance
        for ``service_type``. Singletons take priority if both a
        singleton and a factory were registered for the same type.

        The internal registries are necessarily typed as ``object``
        (a single dict holds every heterogeneous registered type), so
        the cast back to ``TService`` here is unavoidable -- it is
        exactly as safe as the caller's own register_instance/
        register_factory call was, since both are keyed by the same
        ``service_type``.
        """
        if service_type in self._singletons:
            return cast(TService, self._singletons[service_type])
        if service_type in self._factories:
            return cast(TService, self._factories[service_type]())
        raise ServiceNotRegisteredError(service_type)

    def is_registered(self, service_type: type) -> bool:
        """True if ``service_type`` has either a singleton or a factory registered."""
        return service_type in self._singletons or service_type in self._factories
