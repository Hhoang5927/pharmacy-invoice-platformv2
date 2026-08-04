"""
Default, zero-infrastructure-dependency EventDispatcher implementation.

InMemoryEventDispatcher requires nothing beyond the standard library
(no Qt, no message broker), so it is appropriate to ship here in
Application rather than waiting for a later Infrastructure/Presentation
stage to supply one. A future stage may substitute a different
EventDispatcher (e.g. one that bridges into Qt signals) at the
Composition Root without any Application code changing, since
Application depends only on the EventDispatcher abstraction.
"""

from pharmacy_invoice_automation.application.events.in_memory_event_dispatcher import (
    InMemoryEventDispatcher,
)

__all__ = ["InMemoryEventDispatcher"]
