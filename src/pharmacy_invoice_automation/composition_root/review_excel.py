"""
Excel-based batch review (Composition Root, PO decision 2026-08 --
supersedes the earlier "Approved Dataset is just an internal data
contract, not a literal file" reading of TS-006 for the REVIEW step
specifically; see CLAUDE.md Deviation D7). Pure mapping/openpyxl logic
only -- no ServiceContainer, no repository, no filesystem access, so
this is testable without a real SQLite database. composition_root.cli's
run_export_review()/run_import_review() own all I/O and orchestration
and call into this module only for the row<->workbook translation.

Design (PO-confirmed 2026-08, in response to a proposed plan):
- One row per PurchaseItem (not one sheet per invoice, not a separate
  "invoices" + "items" sheet pair) -- simplest for a non-technical
  reviewer to fill by hand in Excel.
- Grouping for import is done by the hidden ``invoice_id`` column
  (columns A/B are the real, guaranteed-unique database keys), not by
  the human-readable "So hoa don" text column the PO actually looks
  at -- duplicate invoice numbers are an explicitly real, business-
  rule-acknowledged case (two genuinely different invoices under
  review at once can share the same number), so grouping by that text
  column alone could silently merge two unrelated invoices' rows.
  "So hoa don" is still shown and IS what the PO thinks of as "the
  grouping column" -- it just is not the literal key used underneath.
- Every editable column maps 1:1 onto a field
  use_cases.submit_invoice_review_use_case.SubmitInvoiceReviewUseCase
  already accepts via SubmitInvoiceReviewCommand.corrected_fields --
  no new business logic, no new accepted values invented here beyond
  the Quyet dinh (decision) column, which only ever becomes
  SubmitInvoiceReviewCommand.reviewer_approved (a bool), exactly
  mirroring composition_root.cli._review_one_invoice's own a/r choices.
- "Quyet dinh" accepts exactly "duyet" / "tu_choi" / blank (PO-
  specified exact tokens, 2026-08) -- blank means "not decided yet,
  leave this invoice alone this import," never guessed as either
  approve or reject.
- Every value is validated BEFORE being handed to the use case (unlike
  the interactive review path, which just submits whatever the
  operator typed and lets the use case's own "silently leave unchanged
  on a bad value" behavior + re-validation surface problems one field
  at a time). Batch import has no per-row human in the loop to notice
  a silently-dropped correction, so invalid cells are instead collected
  into a clear, itemized error report (PO-specified 2026-08: "in ra
  danh sach ro rang 'Cac loi can sua lai'") and that WHOLE invoice is
  excluded from this import pass entirely -- never partially applied.
  Partially applying an invoice's corrections (skip just the bad cell,
  apply the rest, still approve) risks landing an invoice at
  READY_FOR_IMPORT missing a correction the reviewer actually intended,
  with no error loud enough to have been noticed -- exactly the kind
  of silent-wrong-data failure this project's Business Rules forbid.
"""

from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from openpyxl import Workbook, load_workbook
from openpyxl.comments import Comment
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation

from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.enums.tax_type import TaxType
from pharmacy_invoice_automation.domain.exceptions.validation_error import ValidationError
from pharmacy_invoice_automation.domain.value_objects.unit import Unit

_SHEET_NAME = "Xem lại"

_VAT_LABELS: dict[TaxType, str] = {
    TaxType.STANDARD: "10%",
    TaxType.REDUCED: "5%",
    TaxType.EXEMPT: "0%",
    TaxType.EIGHT_PERCENT: "8%",
    TaxType.OTHER: "Khác",
}

_MEDICINE_TYPE_TOKENS = ("prescription", "over_the_counter", "otc")
_DECISION_APPROVE = "duyet"
_DECISION_REJECT = "tu_choi"
_DECISION_TOKENS = (_DECISION_APPROVE, _DECISION_REJECT)

# (column key, Vietnamese header). Order is the literal column order in
# the sheet -- A is index 0, etc. Keep in sync with _row_to_cells and
# _COLUMN_INDEX below.
_COLUMNS: tuple[tuple[str, str], ...] = (
    ("invoice_id", "ID hóa đơn (KHÔNG SỬA)"),
    ("item_id", "ID dòng hàng (KHÔNG SỬA)"),
    ("invoice_number", "Số hóa đơn"),
    ("invoice_date", "Ngày hóa đơn"),
    ("supplier_name", "Nhà cung cấp"),
    ("medicine_name", "Tên thuốc"),
    ("unit_code", "ĐVT"),
    ("quantity", "Số lượng"),
    ("unit_price", "Đơn giá"),
    ("vat_label", "VAT"),
    ("current_retail_ratio", "Hệ số quy đổi Viên (hiện tại)"),
    ("current_website_ratio", "Tỉ lệ ĐV web (hiện tại)"),
    ("issues", "Vấn đề cần xác nhận"),
    ("correction_invoice_number", "SỬA: Số hóa đơn"),
    ("correction_invoice_date", "SỬA: Ngày hóa đơn (YYYY-MM-DD)"),
    ("correction_retail_ratio", "SỬA: Hệ số quy đổi Viên"),
    ("correction_medicine_type", "SỬA: Loại thuốc"),
    ("correction_retail_unit_override", "SỬA: Mã ĐVT bán lẻ ghi đè"),
    ("correction_website_ratio", "SỬA: Tỉ lệ ĐV web xác nhận"),
    ("decision", "Quyết định"),
)
_COLUMN_INDEX: dict[str, int] = {key: i for i, (key, _) in enumerate(_COLUMNS)}
_REFERENCE_COLUMN_COUNT = 13  # invoice_id .. issues -- everything before the first SỬA: column

_HEADER_COMMENTS: dict[str, str] = {
    "correction_medicine_type": (
        "Chỉ chấp nhận: prescription (kê đơn) / over_the_counter (không kê đơn) / "
        "otc (không kê đơn, viết tắt). Để trống nếu không sửa."
    ),
    "correction_retail_unit_override": (
        "1 trong các mã đơn vị đã biết, ví dụ: lo, chai, tuyp, ong -- dùng khi ĐVT ghi "
        "Hộp/Thùng nhưng thực chất là 1 đơn vị bán ra hoàn chỉnh. Để trống nếu không sửa."
    ),
    "decision": (
        "Chỉ chấp nhận: duyet (duyệt) hoặc tu_choi (từ chối). Để trống = chưa quyết, "
        "bỏ qua hóa đơn này ở lần import này. Chỉ cần điền 1 lần cho mỗi hóa đơn "
        "(1 dòng bất kỳ của hóa đơn đó)."
    ),
    "correction_invoice_number": "Chỉ cần điền 1 lần cho mỗi hóa đơn (1 dòng bất kỳ).",
    "correction_invoice_date": "Chỉ cần điền 1 lần cho mỗi hóa đơn (1 dòng bất kỳ).",
}


@dataclass(frozen=True)
class ReviewRow:
    """One PurchaseItem's worth of reference data for a single exported Excel row."""

    invoice_id: str
    item_id: str
    invoice_number: str
    invoice_date: str
    supplier_name: str
    medicine_name: str
    unit_code: str
    quantity: str
    unit_price: str
    vat_label: str
    current_retail_ratio: str
    current_website_ratio: str
    issues: str


def build_export_rows(
    invoices: list[PurchaseInvoice],
    issues_by_invoice_id: dict[str, list[str]],
    supplier_name_by_invoice_id: dict[str, str],
) -> list[ReviewRow]:
    """One ReviewRow per PurchaseItem across every given invoice, in invoice order."""
    rows: list[ReviewRow] = []
    for invoice in invoices:
        issues_text = "; ".join(issues_by_invoice_id.get(invoice.id, []))
        supplier_name = supplier_name_by_invoice_id.get(invoice.id, "(chưa xác định)")
        for item in invoice.items:
            vat_label = _VAT_LABELS.get(item.tax_type, "") if item.tax_type is not None else ""
            rows.append(
                ReviewRow(
                    invoice_id=invoice.id,
                    item_id=item.id,
                    invoice_number=invoice.invoice_number,
                    invoice_date=invoice.invoice_date.isoformat(),
                    supplier_name=supplier_name,
                    medicine_name=item.medicine_name,
                    unit_code=item.unit.code,
                    quantity=str(item.quantity),
                    unit_price=str(item.unit_price),
                    vat_label=vat_label,
                    current_retail_ratio=(
                        str(item.retail_units_per_purchase_unit)
                        if item.retail_units_per_purchase_unit is not None
                        else ""
                    ),
                    current_website_ratio=(
                        str(item.confirmed_website_unit_ratio)
                        if item.confirmed_website_unit_ratio is not None
                        else ""
                    ),
                    issues=issues_text,
                )
            )
    return rows


def write_workbook(rows: list[ReviewRow]) -> bytes:
    """Builds a fresh .xlsx (header + one data row per ReviewRow) and returns its raw bytes."""
    workbook = Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = _SHEET_NAME

    header_font = Font(bold=True)
    reference_fill = PatternFill(start_color="D9D9D9", end_color="D9D9D9", fill_type="solid")
    correction_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    decision_fill = PatternFill(start_color="D9EAD3", end_color="D9EAD3", fill_type="solid")

    for col_index, (key, header) in enumerate(_COLUMNS, start=1):
        cell = sheet.cell(row=1, column=col_index, value=header)
        cell.font = header_font
        if key == "decision":
            cell.fill = decision_fill
        elif col_index > _REFERENCE_COLUMN_COUNT:
            cell.fill = correction_fill
        else:
            cell.fill = reference_fill
        if key in _HEADER_COMMENTS:
            cell.comment = Comment(_HEADER_COMMENTS[key], "pharmacy-invoice-automation")

    for row_index, row in enumerate(rows, start=2):
        for key, _ in _COLUMNS:
            value = getattr(row, key, "")
            sheet.cell(row=row_index, column=_COLUMN_INDEX[key] + 1, value=value)

    sheet.freeze_panes = "A2"
    last_row = len(rows) + 1
    if last_row >= 2:
        decision_col = _COLUMN_INDEX["decision"] + 1
        decision_letter = sheet.cell(row=1, column=decision_col).column_letter
        decision_dv = DataValidation(
            type="list", formula1=f'"{_DECISION_APPROVE},{_DECISION_REJECT}"', allow_blank=True
        )
        sheet.add_data_validation(decision_dv)
        decision_dv.add(f"{decision_letter}2:{decision_letter}{last_row}")

        medicine_type_col = _COLUMN_INDEX["correction_medicine_type"] + 1
        medicine_type_letter = sheet.cell(row=1, column=medicine_type_col).column_letter
        medicine_type_dv = DataValidation(
            type="list", formula1=f'"{",".join(_MEDICINE_TYPE_TOKENS)}"', allow_blank=True
        )
        sheet.add_data_validation(medicine_type_dv)
        medicine_type_dv.add(f"{medicine_type_letter}2:{medicine_type_letter}{last_row}")

    for col_index, (_key, header) in enumerate(_COLUMNS, start=1):
        sheet.column_dimensions[sheet.cell(row=1, column=col_index).column_letter].width = max(
            12, min(40, len(header) + 2)
        )

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


@dataclass(frozen=True)
class RowError:
    """One invalid cell, or one cross-row conflict, found while reading a filled-in workbook."""

    invoice_number: str
    medicine_name: str
    field_label: str
    raw_value: str
    reason: str


@dataclass(frozen=True)
class ParsedInvoiceReview:
    """One invoice's worth of corrections, ready to become a SubmitInvoiceReviewCommand."""

    invoice_id: str
    invoice_number: str
    corrected_fields: dict[str, str]
    reviewer_approved: bool


@dataclass(frozen=True)
class ReadResult:
    reviews: list[ParsedInvoiceReview]
    errors: list[RowError]
    skipped_invoice_ids: list[str]


def _cell_to_text(value: object) -> str:
    """Normalizes an openpyxl cell value to stripped text -- handles Excel returning a
    real datetime.date/datetime object for a cell the PO reformatted as a date type,
    not just the ISO string this module itself writes."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def _is_valid_positive_int(raw: str) -> bool:
    try:
        return int(raw) > 0
    except ValueError:
        return False


def _is_valid_positive_decimal(raw: str) -> bool:
    try:
        return Decimal(raw) > 0
    except InvalidOperation:
        return False


def _is_valid_medicine_type_token(raw: str) -> bool:
    return raw.lower() in _MEDICINE_TYPE_TOKENS


def _is_valid_unit_code(raw: str) -> bool:
    try:
        Unit(code=raw.lower())
        return True
    except ValidationError:
        return False


def _is_valid_iso_date(raw: str) -> bool:
    try:
        date.fromisoformat(raw)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class _InvoiceLevelFieldSpec:
    column_key: str
    field_label: str
    corrected_field_name: str
    is_valid: Callable[[str], bool]


_INVOICE_LEVEL_FIELDS: tuple[_InvoiceLevelFieldSpec, ...] = (
    _InvoiceLevelFieldSpec(
        "correction_invoice_number", "SỬA: Số hóa đơn", "invoice_number", lambda raw: True
    ),
    _InvoiceLevelFieldSpec(
        "correction_invoice_date",
        "SỬA: Ngày hóa đơn (YYYY-MM-DD)",
        "invoice_date",
        _is_valid_iso_date,
    ),
)

_ITEM_LEVEL_FIELDS: tuple[_InvoiceLevelFieldSpec, ...] = (
    _InvoiceLevelFieldSpec(
        "correction_retail_ratio",
        "SỬA: Hệ số quy đổi Viên",
        "retail_units_per_purchase_unit",
        _is_valid_positive_int,
    ),
    _InvoiceLevelFieldSpec(
        "correction_medicine_type",
        "SỬA: Loại thuốc",
        "medicine_type",
        _is_valid_medicine_type_token,
    ),
    _InvoiceLevelFieldSpec(
        "correction_retail_unit_override",
        "SỬA: Mã ĐVT bán lẻ ghi đè",
        "retail_unit_override",
        _is_valid_unit_code,
    ),
    _InvoiceLevelFieldSpec(
        "correction_website_ratio",
        "SỬA: Tỉ lệ ĐV web xác nhận",
        "confirmed_website_unit_ratio",
        _is_valid_positive_decimal,
    ),
)


def read_workbook(xlsx_bytes: bytes) -> ReadResult:
    """
    Reads a filled-in review workbook back and groups its rows by
    invoice (see this module's own docstring for why grouping is by
    the hidden invoice_id column, not the visible invoice-number one).
    Every invoice with at least one invalid/conflicting cell is
    excluded from ``reviews`` entirely (never partially applied) and
    every problem found for it is reported in ``errors``. An invoice
    whose decision is blank on every one of its rows is reported in
    ``skipped_invoice_ids`` -- not an error, just not decided yet.
    """
    workbook = load_workbook(io.BytesIO(xlsx_bytes), data_only=True)
    sheet = workbook[_SHEET_NAME] if _SHEET_NAME in workbook.sheetnames else workbook.active
    assert sheet is not None

    rows_by_invoice_id: dict[str, list[dict[str, str]]] = {}
    for excel_row in sheet.iter_rows(min_row=2, values_only=True):
        if excel_row is None or all(v is None for v in excel_row):
            continue
        cells = {
            key: _cell_to_text(excel_row[index]) if index < len(excel_row) else ""
            for key, index in _COLUMN_INDEX.items()
        }
        invoice_id = cells.get("invoice_id", "")
        if not invoice_id:
            continue
        rows_by_invoice_id.setdefault(invoice_id, []).append(cells)

    reviews: list[ParsedInvoiceReview] = []
    errors: list[RowError] = []
    skipped_invoice_ids: list[str] = []

    for invoice_id, item_rows in rows_by_invoice_id.items():
        invoice_number = item_rows[0]["invoice_number"]
        group_errors: list[RowError] = []

        decision_values = {r["decision"] for r in item_rows if r["decision"]}
        if not decision_values:
            skipped_invoice_ids.append(invoice_id)
            continue
        if len(decision_values) > 1:
            group_errors.append(
                RowError(
                    invoice_number=invoice_number,
                    medicine_name="(toàn hóa đơn)",
                    field_label="Quyết định",
                    raw_value=", ".join(sorted(decision_values)),
                    reason=(
                        "Các dòng của cùng 1 hóa đơn có giá trị 'Quyết định' khác nhau -- "
                        "chỉ điền 1 lần, giá trị giống nhau trên mọi dòng."
                    ),
                )
            )
            reviewer_approved = None
        else:
            (decision_value,) = decision_values
            if decision_value == _DECISION_APPROVE:
                reviewer_approved = True
            elif decision_value == _DECISION_REJECT:
                reviewer_approved = False
            else:
                group_errors.append(
                    RowError(
                        invoice_number=invoice_number,
                        medicine_name="(toàn hóa đơn)",
                        field_label="Quyết định",
                        raw_value=decision_value,
                        reason=(
                            f"Chỉ chấp nhận '{_DECISION_APPROVE}' hoặc '{_DECISION_REJECT}' "
                            "(hoặc để trống)."
                        ),
                    )
                )
                reviewer_approved = None

        corrected_fields: dict[str, str] = {}

        for spec in _INVOICE_LEVEL_FIELDS:
            values = {r[spec.column_key] for r in item_rows if r[spec.column_key]}
            if not values:
                continue
            if len(values) > 1:
                group_errors.append(
                    RowError(
                        invoice_number=invoice_number,
                        medicine_name="(toàn hóa đơn)",
                        field_label=spec.field_label,
                        raw_value=", ".join(sorted(values)),
                        reason=(
                            "Các dòng của cùng 1 hóa đơn có giá trị khác nhau -- chỉ điền "
                            "1 lần, giá trị giống nhau trên mọi dòng."
                        ),
                    )
                )
                continue
            (value,) = values
            if not spec.is_valid(value):
                group_errors.append(
                    RowError(
                        invoice_number=invoice_number,
                        medicine_name="(toàn hóa đơn)",
                        field_label=spec.field_label,
                        raw_value=value,
                        reason="Giá trị không hợp lệ.",
                    )
                )
                continue
            corrected_fields[spec.corrected_field_name] = value

        for row in item_rows:
            item_id = row["item_id"]
            for spec in _ITEM_LEVEL_FIELDS:
                raw_value = row[spec.column_key]
                if not raw_value:
                    continue
                if not spec.is_valid(raw_value):
                    group_errors.append(
                        RowError(
                            invoice_number=invoice_number,
                            medicine_name=row["medicine_name"],
                            field_label=spec.field_label,
                            raw_value=raw_value,
                            reason="Giá trị không hợp lệ.",
                        )
                    )
                    continue
                corrected_fields[f"item.{item_id}.{spec.corrected_field_name}"] = raw_value

        if group_errors:
            errors.extend(group_errors)
            continue

        assert reviewer_approved is not None
        reviews.append(
            ParsedInvoiceReview(
                invoice_id=invoice_id,
                invoice_number=invoice_number,
                corrected_fields=corrected_fields,
                reviewer_approved=reviewer_approved,
            )
        )

    return ReadResult(reviews=reviews, errors=errors, skipped_invoice_ids=skipped_invoice_ids)
