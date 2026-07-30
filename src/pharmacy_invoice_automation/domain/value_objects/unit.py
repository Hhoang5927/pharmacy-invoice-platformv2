"""
Value Object: Unit.

Represents a validated dispensing unit for a medicine (e.g. "vien",
"tuyp"), per Business Rules: "Neu quy cach la vien -> Chon vien. Neu
quy cach la tuyp -> Chon tuyp."

Replaces the prior bare "UnitType" enum: Unit is now a full Value
Object capable of normalizing raw OCR text into itself
(``Unit.from_raw_text``), which is where the old
domain.rules.unit_mapping_rule logic now lives -- consistent with
avoiding anemic design by giving the concept real behavior rather than
just enumerating labels.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError

# Canonical unit codes. "other" is a legitimate, non-failing fallback --
# see from_raw_text -- so a line is never blocked from review purely
# over an unfamiliar unit word.
_KNOWN_CODES: frozenset[str] = frozenset(
    {"vien", "tuyp", "hop", "chai", "goi", "ong", "other"}
)

# OCR-extracted, lowercased/stripped unit text -> canonical code.
# Extend this mapping as new packaging types are encountered -- never
# hardcode a new unit string anywhere else.
_RAW_TEXT_TO_CODE: dict[str, str] = {
    "vien": "vien", "viên": "vien",
    "tuyp": "tuyp", "tuýp": "tuyp",
    "hop": "hop", "hộp": "hop",
    "chai": "chai",
    "goi": "goi", "gói": "goi",
    "ong": "ong", "ống": "ong",
}

_DISPLAY_LABELS: dict[str, str] = {
    "vien": "vien (tablet/pill)",
    "tuyp": "tuyp (tube)",
    "hop": "hop (box)",
    "chai": "chai (bottle)",
    "goi": "goi (sachet/packet)",
    "ong": "ong (ampoule/vial)",
    "other": "other (unrecognized -- confirm manually)",
}


@dataclass(frozen=True)
class Unit:
    """An immutable, validated dispensing unit."""

    code: str

    def __post_init__(self) -> None:
        if self.code not in _KNOWN_CODES:
            raise ValidationError(
                f"'{self.code}' is not a recognized unit code. "
                f"Known codes: {sorted(_KNOWN_CODES)}."
            )

    @classmethod
    def from_raw_text(cls, raw_unit_text: str) -> "Unit":
        """
        Build a Unit from free-text OCR output. Falls back to the
        "other" code (never raises) so a line is never blocked from
        review purely over an unrecognized unit word -- callers should
        treat ``Unit(code="other")`` as worth flagging for manual
        confirmation.
        """
        normalized = raw_unit_text.strip().lower() if raw_unit_text else ""
        return cls(code=_RAW_TEXT_TO_CODE.get(normalized, "other"))

    @property
    def requires_manual_confirmation(self) -> bool:
        """True if this unit could not be confidently recognized."""
        return self.code == "other"

    @property
    def display_label(self) -> str:
        """Human-readable label for this unit."""
        return _DISPLAY_LABELS[self.code]

    def __str__(self) -> str:
        return self.code
