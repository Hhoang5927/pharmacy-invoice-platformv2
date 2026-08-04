"""
Value Object: Unit.

Represents a validated dispensing/retail unit for a medicine. The
canonical code list matches, exactly, the 39 "don vi xuat le" options
the target website (webnhathuoc.com) offers in its retail-unit
dropdown -- confirmed directly against the live dropdown, not assumed.
This value object was originally scoped to only 6 common codes
(vien/tuyp/hop/chai/goi/ong); it was deliberately widened to the full,
confirmed 39-code list so that real, valid units (e.g. "Vi", "Lo",
"Thung") are not incorrectly flagged as unrecognized and forced into
manual review -- a correction of a genuine data mismatch against the
real target system, not a speculative feature addition.

Replaces the prior bare "UnitType" enum: Unit is now a full Value
Object capable of normalizing raw OCR text into itself
(``Unit.from_raw_text``), which is where the old
domain.rules.unit_mapping_rule logic now lives -- consistent with
avoiding anemic design by giving the concept real behavior rather than
just enumerating labels.

Known limitation (documented, not silently papered over): "Lo" (dozen,
a counting unit) and "Lo" (bottle/jar) are two distinct, real dropdown
options that become identical once Vietnamese diacritics are stripped
("lo"). When raw OCR text arrives with correct diacritics ("lo^"" vs
"lo.") this value object maps each to its own distinct code correctly.
When raw text arrives already diacritic-stripped and ambiguous, it
resolves to "lo" (bottle/jar, the more common pharmacy unit) rather
than "lo_dozen" -- callers processing bulk/wholesale-count invoices
where "lo" (dozen) is expected should be aware of this default.
"""

from __future__ import annotations

from dataclasses import dataclass

from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError

# Canonical unit codes -- the exact 39 retail-unit options confirmed
# from the live webnhathuoc.com "don vi xuat le" dropdown, plus "other"
# as a legitimate, non-failing fallback (see from_raw_text) so a line
# is never blocked from review purely over a genuinely unfamiliar word.
_KNOWN_CODES: frozenset[str] = frozenset(
    {
        "banh", "bao", "bich", "binh", "bo", "cai", "can", "cap", "chai",
        "chiec", "coc", "cu", "cuon", "day", "doi", "goi", "hop",
        "hop_nho", "hop_to", "kien", "kit", "la", "lieu", "lo_dozen",
        "lo", "loc", "lon", "mieng", "ong", "que", "tep", "thanh",
        "thoi", "thung", "tui", "tuyp", "vi", "vien", "xap",
        "other",
    }
)

# OCR-extracted, lowercased/stripped unit text -> canonical code.
# Both diacritic and diacritic-stripped forms are mapped, since source
# text (OCR or the invoice itself) may arrive either way. Extend this
# mapping as new packaging types are encountered -- never hardcode a
# new unit string anywhere else.
_RAW_TEXT_TO_CODE: dict[str, str] = {
    "banh": "banh", "bánh": "banh",
    "bao": "bao",
    "bich": "bich", "bịch": "bich",
    "binh": "binh", "bình": "binh",
    "bo": "bo", "bộ": "bo",
    "cai": "cai", "cái": "cai",
    "can": "can",
    "cap": "cap", "cặp": "cap",
    "chai": "chai",
    "chiec": "chiec", "chiếc": "chiec",
    "coc": "coc", "cọc": "coc",
    "cu": "cu", "củ": "cu",
    "cuon": "cuon", "cuộn": "cuon",
    "day": "day", "dây": "day",
    "doi": "doi", "đôi": "doi",
    "goi": "goi", "gói": "goi",
    "hop": "hop", "hộp": "hop",
    "hop nho": "hop_nho", "hộp nhỏ": "hop_nho", "hop_nho": "hop_nho",
    "hop to": "hop_to", "hộp to": "hop_to", "hop_to": "hop_to",
    "kien": "kien", "kiện": "kien",
    "kit": "kit",
    "la": "la", "lá": "la",
    "lieu": "lieu", "liều": "lieu",
    "lố": "lo_dozen",  # diacritic-precise -> unambiguous
    "lọ": "lo",  # diacritic-precise -> unambiguous
    "lo": "lo",  # diacritic-stripped + ambiguous -> defaults to bottle/jar (see module docstring)
    "loc": "loc", "lốc": "loc",
    "lon": "lon",
    "mieng": "mieng", "miếng": "mieng",
    "ong": "ong", "ống": "ong",
    "que": "que",
    "tep": "tep", "tép": "tep",
    "thanh": "thanh",
    "thoi": "thoi", "thỏi": "thoi",
    "thung": "thung", "thùng": "thung",
    "tui": "tui", "túi": "tui",
    "tuyp": "tuyp", "tuýp": "tuyp",
    "vi": "vi", "vỉ": "vi",
    "vien": "vien", "viên": "vien",
    "xap": "xap", "xấp": "xap",
}

_DISPLAY_LABELS: dict[str, str] = {
    "banh": "banh (banh/cake unit)",
    "bao": "bao (sack)",
    "bich": "bich (pouch)",
    "binh": "binh (jug/canister)",
    "bo": "bo (set)",
    "cai": "cai (piece/item)",
    "can": "can (jerrycan)",
    "cap": "cap (pair/set)",
    "chai": "chai (bottle)",
    "chiec": "chiec (piece)",
    "coc": "coc (stack)",
    "cu": "cu (tuber/root -- count unit)",
    "cuon": "cuon (roll)",
    "day": "day (strip/strand)",
    "doi": "doi (pair)",
    "goi": "goi (sachet/packet)",
    "hop": "hop (box)",
    "hop_nho": "hop nho (small box)",
    "hop_to": "hop to (large box)",
    "kien": "kien (crate)",
    "kit": "kit",
    "la": "la (leaf/sheet)",
    "lieu": "lieu (dose)",
    "lo_dozen": "lo (dozen -- count unit, ambiguous with lo/bottle when diacritics are stripped)",
    "lo": "lo (bottle/jar)",
    "loc": "loc (pack)",
    "lon": "lon (can)",
    "mieng": "mieng (piece/slice)",
    "ong": "ong (ampoule/vial)",
    "que": "que (stick)",
    "tep": "tep (small pack)",
    "thanh": "thanh (bar)",
    "thoi": "thoi (bar/ingot)",
    "thung": "thung (carton/drum)",
    "tui": "tui (bag)",
    "tuyp": "tuyp (tube)",
    "vi": "vi (blister pack)",
    "vien": "vien (tablet/pill)",
    "xap": "xap (stack/bundle)",
    "other": "other (unrecognized -- confirm manually)",
}


@dataclass(frozen=True)
class Unit:
    """An immutable, validated dispensing/retail unit."""

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
