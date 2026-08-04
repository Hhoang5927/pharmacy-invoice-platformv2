"""
SqliteProjectRepository: implements
domain.ports.repositories.ProjectRepository against SQLite.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from pharmacy_invoice_automation.domain.entities.project import Project
from pharmacy_invoice_automation.domain.ports.repositories.project_repository import (
    ProjectRepository,
)
from pharmacy_invoice_automation.infrastructure.persistence.connection_manager import (
    SqliteConnectionManager,
)


class SqliteProjectRepository(ProjectRepository):
    """SQLite-backed persistence for Project."""

    def __init__(self, connection_manager: SqliteConnectionManager) -> None:
        self._connection_manager = connection_manager

    @property
    def _connection(self) -> sqlite3.Connection:
        return self._connection_manager.connection

    def add(self, project: Project) -> None:
        """Persist a newly created Project."""
        self._connection.execute(
            "INSERT INTO projects (id, name, root_folder, created_at) VALUES (?, ?, ?, ?);",
            (project.id, project.name, project.root_folder, project.created_at.isoformat()),
        )

    def get_by_id(self, project_id: str) -> Project | None:
        """Return the Project with this id, or None if not found."""
        row = self._connection.execute(
            "SELECT id, name, root_folder, created_at FROM projects WHERE id = ?;", (project_id,)
        ).fetchone()
        return self._to_entity(row) if row is not None else None

    def list_all(self) -> list[Project]:
        """Return every known Project."""
        rows = self._connection.execute(
            "SELECT id, name, root_folder, created_at FROM projects;"
        ).fetchall()
        return [self._to_entity(row) for row in rows]

    def update(self, project: Project) -> None:
        """Persist changes to an existing Project."""
        self._connection.execute(
            "UPDATE projects SET name = ?, root_folder = ? WHERE id = ?;",
            (project.name, project.root_folder, project.id),
        )

    @staticmethod
    def _to_entity(row: sqlite3.Row) -> Project:
        return Project(
            id=row["id"],
            name=row["name"],
            root_folder=row["root_folder"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )
