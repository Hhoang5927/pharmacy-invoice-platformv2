"""
Repository Port: ProjectRepository.

Persistence contract for the Project entity. Added beyond Stage 04's
explicit Repository Ports examples list, for the same reason Project
itself was retained as an entity: FR-01 (Project management) still
requires it, and nothing in Stage 04 superseded that requirement.
Renamed from "IProjectRepository" per Stage 04's updated naming
convention (no "I" prefix) for consistency with the rest of this
package.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from pharmacy_invoice_automation.domain.entities.project import Project


class ProjectRepository(ABC):
    """Abstract persistence contract for Project."""

    @abstractmethod
    def add(self, project: Project) -> None:
        """Persist a newly created Project."""

    @abstractmethod
    def get_by_id(self, project_id: str) -> Project | None:
        """Return the Project with this id, or None if not found."""

    @abstractmethod
    def list_all(self) -> list[Project]:
        """Return every known Project."""

    @abstractmethod
    def update(self, project: Project) -> None:
        """Persist changes to an existing Project."""
