"""
Entity: Project.

Represents a working session: a chosen folder (or folders) of invoice
images being processed as one batch (FR-01).

Retained from the prior Domain Layer build: Stage 04's entity examples
list does not mention Project, but FR-01 (Project management) is an
unchanged functional requirement, and dropping this entity would
regress that requirement without anything in Stage 04 superseding it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError


@dataclass(eq=False)
class Project:
    """A working project/session."""

    id: str
    name: str
    root_folder: str
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        if not self.id:
            raise ValidationError("Project id cannot be empty.")
        if not self.name or not self.name.strip():
            raise ValidationError("Project name cannot be empty.")
        if not self.root_folder or not self.root_folder.strip():
            raise ValidationError("Project root_folder cannot be empty.")
        self.name = self.name.strip()

    def rename(self, new_name: str) -> None:
        """Rename this project, keeping other fields unchanged."""
        if not new_name or not new_name.strip():
            raise ValidationError("Project name cannot be empty.")
        self.name = new_name.strip()

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Project):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        return hash(self.id)
