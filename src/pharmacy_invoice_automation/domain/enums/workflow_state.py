"""
Enum: WorkflowState.

Overall batch-run control state, matching the UI Requirements'
Start / Pause / Resume / Stop controls. Distinct from InvoiceStatus,
which tracks one invoice at a time -- WorkflowState tracks the batch
run as a whole.
"""

from __future__ import annotations

from enum import Enum


class WorkflowState(str, Enum):
    """Control state of an entire batch run."""

    NOT_STARTED = "not_started"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"
