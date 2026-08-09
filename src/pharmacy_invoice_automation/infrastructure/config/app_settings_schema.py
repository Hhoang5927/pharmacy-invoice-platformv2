"""
AppSettings: the typed, validated shape of every configurable setting
(FR-14), layered from defaults -> config file -> environment variables
-> UI-set overrides by settings_manager.SettingsManager.

Environment note: the original Technology Stack decision (Technical
Design Document Section 3) specified Pydantic for this schema.
Pydantic and pydantic-settings are not installable in this sandboxed
environment (no network access, confirmed by direct attempt -- the
same constraint already documented for ruff/mypy). To keep this file
both compiling and genuinely functionally tested here (not merely
syntax-checked), it is implemented as a stdlib dataclass with explicit
__post_init__ validation instead -- functionally equivalent (type
coercion + validation) and consistent with the pattern Domain and
Application already use throughout. Swap in Pydantic once it is
actually installable in the real target environment, if still wanted;
nothing about SettingsManager's public interface would need to change.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AppSettings:
    """Typed, validated application settings (non-secret values only)."""

    # --- OCR ---
    # Confirmed current (2026-07) as a real, multimodal, vision-capable
    # model via https://ai.google.dev/gemini-api/docs/models -- Gemini
    # 2.5 Pro/Flash are being sunset (Oct 2026); this is a plain
    # configuration value, never a hardcoded assumption elsewhere in code.
    gemini_model: str = "gemini-3.6-flash"
    ocr_concurrency_limit: int = 5
    ocr_retry_count: int = 3
    # Live-tested against the real Gemini API (2026-07-31): a real
    # structured-output OCR call on a real invoice PDF took ~27s, right
    # at the edge of a 30s timeout -- 60s leaves real margin.
    ocr_timeout_seconds: float = 60.0

    # --- Automation ---
    automation_headless: bool = True
    automation_timeout_seconds: float = 30.0
    automation_retry_count: int = 3
    automation_navigation_timeout_seconds: float = 30.0
    # How long a run pauses for a human to manually resolve an ambiguous
    # medicine-name search result (Part 3 of the multi-result-
    # disambiguation feature, PO-confirmed 2026-08: "vài phút", a few
    # minutes) before failing cleanly instead of hanging forever.
    automation_human_disambiguation_timeout_seconds: float = 180.0

    # --- Medicine catalog ---
    # PO decision (2026-08): each pharmacy this system processes invoices
    # for is a separate, independent operation with its own catalog
    # (Business Rules: "Ma thuoc: TH1, TH2, TH3..."), so this must be
    # changeable per run (e.g. "DTN") without a code change -- "TH"
    # remains the default when left unconfigured. Consumed by
    # infrastructure.persistence.sqlite_repositories.medicine_repository
    # .SqliteMedicineRepository and threaded through
    # application.pipeline.party_matching_step.PartyMatchingStep into
    # domain.services.medicine_validation_service.MedicineValidationService
    # .generate_next_medicine_code.
    medicine_code_prefix: str = "TH"

    # --- Price lookup ---
    price_cache_ttl_hours: float = 24.0

    # --- Logging ---
    log_level: str = "INFO"
    log_retention_days: int = 14

    # --- Paths ---
    default_working_folder: str = ""
    database_path: str = "./data/project.sqlite3"

    def __post_init__(self) -> None:
        if self.ocr_concurrency_limit < 1:
            raise ValueError(
                f"ocr_concurrency_limit must be at least 1, got {self.ocr_concurrency_limit}."
            )
        if self.ocr_retry_count < 1:
            raise ValueError(f"ocr_retry_count must be at least 1, got {self.ocr_retry_count}.")
        if self.ocr_timeout_seconds <= 0:
            raise ValueError("ocr_timeout_seconds must be positive.")
        if self.automation_timeout_seconds <= 0:
            raise ValueError("automation_timeout_seconds must be positive.")
        if self.automation_retry_count < 1:
            raise ValueError("automation_retry_count must be at least 1.")
        if self.automation_navigation_timeout_seconds <= 0:
            raise ValueError("automation_navigation_timeout_seconds must be positive.")
        if self.automation_human_disambiguation_timeout_seconds <= 0:
            raise ValueError("automation_human_disambiguation_timeout_seconds must be positive.")
        if not self.medicine_code_prefix.strip():
            raise ValueError("medicine_code_prefix cannot be empty.")
        if self.price_cache_ttl_hours < 0:
            raise ValueError("price_cache_ttl_hours cannot be negative.")
        if self.log_level not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError(f"log_level {self.log_level!r} is not a recognized logging level.")
        if self.log_retention_days < 1:
            raise ValueError("log_retention_days must be at least 1.")
        if not self.database_path.strip():
            raise ValueError("database_path cannot be empty.")
