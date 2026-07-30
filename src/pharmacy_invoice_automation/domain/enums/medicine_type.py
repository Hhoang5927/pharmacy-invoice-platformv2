"""
Enum: MedicineType.

Prescription vs. over-the-counter classification, per Business Rules:
"Neu thuoc la thuoc ke don -> Nhom = Thuoc ke don. Neu thuoc khong ke
don -> Nhom = Thuoc khong ke don."

Renamed from the prior "MedicineGroup" per Stage 04's updated
terminology; semantics are unchanged.
"""

from __future__ import annotations

from enum import Enum


class MedicineType(str, Enum):
    """Prescription-status classification of a Medicine."""

    PRESCRIPTION = "prescription"            # Thuoc ke don
    OVER_THE_COUNTER = "over_the_counter"    # Thuoc khong ke don
