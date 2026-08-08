"""
CLI command implementations (Composition Root, Stage B, PO-confirmed
2026-08): a plain-text terminal front end driving the same real
Application use cases a future PySide6 Presentation layer would --
Presentation itself is still scaffold-only, but the business pipeline
underneath it is real, tested, and usable today.

run_scan() is Stage B's own deliverable: discover every invoice image
in a folder, run each one through use_cases.process_invoice_use_case.ProcessInvoiceUseCase
(exactly the same use case, not a reimplementation), and print a clear,
human-readable summary per invoice. Later stages add commands here for
reviewing UnderReview invoices (Stage C) and running browser automation
against ReadyForImport ones (Stage D) -- this module is the natural,
growing home for all three, not the DI wiring itself (see bootstrap.py).
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from pharmacy_invoice_automation.application.commands import (
    ProcessInvoiceCommand,
    SubmitInvoiceReviewCommand,
)
from pharmacy_invoice_automation.application.configuration import ConfidenceThresholds, RetryPolicy
from pharmacy_invoice_automation.application.dto import PurchaseInvoiceDTO
from pharmacy_invoice_automation.application.events.in_memory_event_dispatcher import (
    InMemoryEventDispatcher,
)
from pharmacy_invoice_automation.application.job_state import InvoiceJob, JobState
from pharmacy_invoice_automation.application.pipeline.invoice_extraction_step import (
    InvoiceExtractionStep,
)
from pharmacy_invoice_automation.application.pipeline.invoice_persistence_step import (
    InvoicePersistenceStep,
)
from pharmacy_invoice_automation.application.pipeline.invoice_validation_step import (
    InvoiceValidationStep,
)
from pharmacy_invoice_automation.application.pipeline.party_matching_step import (
    PartyMatchingStep,
)
from pharmacy_invoice_automation.application.ports.transaction_coordinator import (
    TransactionCoordinator,
)
from pharmacy_invoice_automation.application.results import UseCaseResult
from pharmacy_invoice_automation.application.use_cases.process_invoice_use_case import (
    ProcessInvoiceUseCase,
)
from pharmacy_invoice_automation.application.use_cases.submit_invoice_review_use_case import (
    SubmitInvoiceReviewUseCase,
)
from pharmacy_invoice_automation.domain.entities.project import Project
from pharmacy_invoice_automation.domain.entities.purchase_invoice import PurchaseInvoice
from pharmacy_invoice_automation.domain.enums.invoice_status import InvoiceStatus
from pharmacy_invoice_automation.domain.ports.repositories.medicine_repository import (
    MedicineRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.project_repository import (
    ProjectRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.purchase_invoice_repository import (
    PurchaseInvoiceRepository,
)
from pharmacy_invoice_automation.domain.ports.repositories.supplier_repository import (
    SupplierRepository,
)
from pharmacy_invoice_automation.domain.ports.services.browser_automation_provider import (
    AutomationOutcome,
    BrowserAutomationProvider,
)
from pharmacy_invoice_automation.domain.ports.services.file_storage_provider import (
    FileStorageProvider,
)
from pharmacy_invoice_automation.domain.ports.services.ocr_provider import OCRProvider
from pharmacy_invoice_automation.domain.services.invoice_calculation_service import (
    InvoiceCalculationService,
)
from pharmacy_invoice_automation.domain.services.medicine_validation_service import (
    MedicineValidationService,
)
from pharmacy_invoice_automation.domain.services.price_policy import PricePolicy
from pharmacy_invoice_automation.domain.services.purchase_policy import PurchasePolicy
from pharmacy_invoice_automation.domain.services.supplement_classification_service import (
    SupplementClassificationService,
)
from pharmacy_invoice_automation.domain.validators.invoice_validator import InvoiceValidator
from pharmacy_invoice_automation.infrastructure.automation.automation_errors import (
    UnitMismatchError,
)
from pharmacy_invoice_automation.infrastructure.di.service_container import ServiceContainer

_INVOICE_IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".pdf")


def _print(text: str = "") -> None:
    """
    print(), but never crashes on Vietnamese diacritics against a
    default-cp1252 Windows console (the same real failure mode already
    documented and handled in
    tests/golden/ocr_golden_files/test_gemini_adapter_live.py's own
    _print helper) -- degrades unencodable characters to a visible
    backslash escape rather than raising UnicodeEncodeError and losing
    every remaining line of output.
    """
    encoding = sys.stdout.encoding or "utf-8"
    print(text.encode(encoding, errors="backslashreplace").decode(encoding))

_STATUS_LABELS_VI = {
    "ready_for_import": "TỰ ĐỘNG DUYỆT (sẵn sàng nhập)",
    "under_review": "CẦN XEM LẠI (Human Review)",
    "ocr_failed": "LỖI OCR",
    "import_failed": "LỖI NHẬP DỮ LIỆU",
    "imported": "ĐÃ NHẬP",
    "pending": "CHỜ XỬ LÝ",
    "ocr_in_progress": "ĐANG OCR",
    "ocr_done": "ĐÃ OCR XONG",
}


def _build_party_matching_step(container: ServiceContainer) -> PartyMatchingStep:
    """
    Shared by build_process_invoice_use_case() (the original OCR
    pipeline) and run_review() (SubmitInvoiceReviewUseCase's reviewer-
    driven medicine resolution, bug fix PO-confirmed 2026-08) -- exactly
    one PartyMatchingStep construction, not duplicated. ai_provider=None/
    allow_ai_fallback_classification=False: no AIProvider implementation
    exists yet (out of scope for this stage) -- PartyMatchingStep's own
    AI-fallback path is already written to require both a provider AND
    this flag, so this is a real "not available yet," not a guess.
    """
    return PartyMatchingStep(
        purchase_policy=PurchasePolicy(),
        medicine_validation_service=MedicineValidationService(),
        supplement_classification_service=SupplementClassificationService(),
        supplier_repository=container.resolve(SupplierRepository),
        medicine_repository=container.resolve(MedicineRepository),
        ai_provider=None,
        allow_ai_fallback_classification=False,
    )


def build_process_invoice_use_case(container: ServiceContainer) -> ProcessInvoiceUseCase:
    """
    Assemble a real ProcessInvoiceUseCase from what Stage A registered
    plus the Domain services/pipeline steps it needs -- these are pure,
    dependency-free Domain objects (PurchasePolicy,
    MedicineValidationService, SupplementClassificationService,
    InvoiceValidator, InvoiceCalculationService, PricePolicy), never
    registered in the DI container themselves since nothing else needs
    to resolve them independently.
    """
    party_matching_step = _build_party_matching_step(container)
    validation_step = InvoiceValidationStep(
        invoice_validator=InvoiceValidator(),
        invoice_calculation_service=InvoiceCalculationService(),
        price_policy=PricePolicy(),
    )
    persistence_step = InvoicePersistenceStep(
        purchase_invoice_repository=container.resolve(PurchaseInvoiceRepository),
        supplier_repository=container.resolve(SupplierRepository),
        medicine_repository=container.resolve(MedicineRepository),
        transaction_coordinator=container.resolve(TransactionCoordinator),
    )
    extraction_step = InvoiceExtractionStep(
        ocr_provider=container.resolve(OCRProvider), retry_policy=RetryPolicy()
    )
    return ProcessInvoiceUseCase(
        extraction_step=extraction_step,
        party_matching_step=party_matching_step,
        validation_step=validation_step,
        persistence_step=persistence_step,
        event_dispatcher=InMemoryEventDispatcher(),
        confidence_thresholds=ConfidenceThresholds(),
    )


def run_scan(
    container: ServiceContainer, image_folder: Path, project_name: str
) -> list[UseCaseResult[PurchaseInvoiceDTO]]:
    """
    Discover every invoice image under ``image_folder``, run each
    through a real ProcessInvoiceUseCase, and print a clear,
    human-readable result per invoice: status, invoice number,
    supplier, surviving line items, and every warning/note (including
    exactly which lines were excluded for a non-5% VAT rate and why --
    services.supplement_classification_service.SupplementClassificationService's
    own notes text, surfaced here verbatim, not reworded).

    Returns the per-invoice UseCaseResult list (one per discovered
    image, same order) -- the CLI itself only needs the printed output,
    but returning this too costs nothing and lets a caller (e.g. a
    test, or a future Presentation layer) inspect real results directly
    instead of re-parsing terminal text.
    """
    file_storage_provider = container.resolve(FileStorageProvider)
    image_paths = file_storage_provider.list_files(
        str(image_folder), list(_INVOICE_IMAGE_EXTENSIONS)
    )
    if not image_paths:
        _print(f"Không tìm thấy ảnh hóa đơn nào trong '{image_folder}'.")
        return []

    try:
        process_invoice_use_case = build_process_invoice_use_case(container)
    except RuntimeError as exc:
        _print(f"Không thể khởi tạo pipeline xử lý: {exc}")
        return []

    project_repository = container.resolve(ProjectRepository)
    project = Project(id=str(uuid.uuid4()), name=project_name, root_folder=str(image_folder))
    project_repository.add(project)

    _print(f"Tìm thấy {len(image_paths)} ảnh hóa đơn trong '{image_folder}'.")
    _print(f"Dự án: '{project_name}' (id={project.id})\n")

    results: list[UseCaseResult[PurchaseInvoiceDTO]] = []
    for index, image_path in enumerate(image_paths, start=1):
        _print(f"[{index}/{len(image_paths)}] {Path(image_path).name}")
        _print("-" * 70)
        result = _process_one_image(process_invoice_use_case, container, project.id, image_path)
        results.append(result)
        _print()

    return results


def _process_one_image(
    process_invoice_use_case: ProcessInvoiceUseCase,
    container: ServiceContainer,
    project_id: str,
    image_path: str,
) -> UseCaseResult[PurchaseInvoiceDTO]:
    file_storage_provider = container.resolve(FileStorageProvider)
    image_bytes = file_storage_provider.read_file(image_path)

    invoice = PurchaseInvoice(
        id=str(uuid.uuid4()),
        project_id=project_id,
        invoice_number=f"PENDING-{uuid.uuid4().hex[:8]}",
        invoice_date=date.today(),
    )
    job = InvoiceJob(invoice_id=invoice.id)
    job.transition_to(JobState.QUEUED)
    command = ProcessInvoiceCommand(invoice_id=invoice.id, image_bytes=image_bytes)

    result = process_invoice_use_case.execute(
        command, invoice, job, is_new_invoice=True
    )
    _print_result(result, container)
    return result


def _print_result(result: UseCaseResult[PurchaseInvoiceDTO], container: ServiceContainer) -> None:
    if not result.is_success:
        _print("  Trạng thái: LỖI (không tạo được hóa đơn)")
        for error in result.errors:
            _print(f"    - {error}")
        return

    invoice = result.value
    assert invoice is not None
    status_label = _STATUS_LABELS_VI.get(invoice.status, invoice.status)
    _print(f"  Trạng thái: {status_label}")
    _print(f"  Số hóa đơn: {invoice.invoice_number}")
    _print(f"  Nhà cung cấp: {_resolve_supplier_name(invoice.supplier_id, container)}")
    if result.confidence is not None:
        _print(f"  Độ tin cậy OCR tổng thể: {result.confidence:.2f}")

    if invoice.items:
        _print(f"  Dòng hàng ({len(invoice.items)}):")
        for item in invoice.items:
            tax_label = item.tax_type or "?"
            _print(
                f"    - {item.medicine_name}: SL={item.quantity} "
                f"Đơn giá={item.unit_price} VAT={tax_label} "
                f"Thành tiền={item.line_total}"
            )
    else:
        _print("  Dòng hàng: (không còn dòng nào sau khi lọc)")

    if result.warnings:
        _print("  Ghi chú / cảnh báo:")
        for warning in result.warnings:
            _print(f"    * {warning}")


def _resolve_supplier_name(supplier_id: str | None, container: ServiceContainer) -> str:
    if supplier_id is None:
        return "(chưa xác định)"
    supplier_repository = container.resolve(SupplierRepository)
    supplier = supplier_repository.get_by_id(supplier_id)
    return supplier.name if supplier is not None else f"(không tìm thấy: {supplier_id})"


# --- Stage C: minimal command-line review ----------------------------------

_REVIEW_PROMPT = (
    "  Chọn: a=Duyệt  s=Sửa 1 trường  r=Từ chối  (Enter=Bỏ qua hóa đơn này) > "
)
_CORRECTION_FIELD_HINT = (
    "    Tên trường (vd: invoice_number, invoice_date [YYYY-MM-DD], "
    "item.<item_id>.retail_units_per_purchase_unit, "
    "item.<item_id>.medicine_type [prescription/over_the_counter/otc], "
    "item.<item_id>.retail_unit_override [1 trong 39 mã đơn vị, vd lo/chai/tuyp/ong -- "
    "dùng khi ĐVT ghi Hộp/Thùng nhưng thực chất là 1 đơn vị bán ra hoàn chỉnh], hoặc "
    "item.<item_id>.confirmed_website_unit_ratio [số dương, vd 1 -- xác nhận tỉ lệ quy đổi "
    "khi automate báo đơn vị trên web khác đơn vị trên hóa đơn cho dòng này]): "
)


def run_review(
    container: ServiceContainer, input_fn: Callable[[str], str] = input
) -> list[UseCaseResult[PurchaseInvoiceDTO]]:
    """
    Minimal interactive review over the command line (Stage C,
    PO-confirmed 2026-08): every PurchaseInvoice currently UNDER_REVIEW,
    one at a time -- show its details plus InvoiceValidator's CURRENT
    issues (re-run fresh here, read-only, per Domain's own "Validation
    is read-only" rule; the original processing pass's issues/notes
    were never persisted anywhere, matching run_scan()'s own printed-
    only warnings), then let the operator approve (a), correct one or
    more fields and then decide (s), or reject (r) --
    use_cases.submit_invoice_review_use_case.SubmitInvoiceReviewUseCase
    does the actual work, exactly as already built, not reimplemented
    here.

    ``input_fn`` defaults to the real builtin input() -- overridable so
    a test can drive this with real, controlled keystrokes instead of
    needing an actual interactive terminal.
    """
    purchase_invoice_repository = container.resolve(PurchaseInvoiceRepository)
    invoices = purchase_invoice_repository.list_by_status(InvoiceStatus.UNDER_REVIEW)
    if not invoices:
        _print("Không có hóa đơn nào đang chờ xem lại (UNDER_REVIEW).")
        return []

    submit_review_use_case = SubmitInvoiceReviewUseCase(
        purchase_invoice_repository=purchase_invoice_repository,
        medicine_repository=container.resolve(MedicineRepository),
        invoice_validator=InvoiceValidator(),
        transaction_coordinator=container.resolve(TransactionCoordinator),
        party_matching_step=_build_party_matching_step(container),
    )

    _print(f"Có {len(invoices)} hóa đơn đang chờ xem lại.\n")

    results: list[UseCaseResult[PurchaseInvoiceDTO]] = []
    for index, invoice in enumerate(invoices, start=1):
        _print(f"=== Hóa đơn {index}/{len(invoices)} ===")
        result = _review_one_invoice(invoice, container, submit_review_use_case, input_fn)
        if result is not None:
            results.append(result)
        _print()

    return results


def _review_one_invoice(
    invoice: PurchaseInvoice,
    container: ServiceContainer,
    submit_review_use_case: SubmitInvoiceReviewUseCase,
    input_fn: Callable[[str], str],
) -> UseCaseResult[PurchaseInvoiceDTO] | None:
    _print(f"  ID: {invoice.id}")
    _print(f"  Số hóa đơn: {invoice.invoice_number}")
    _print(f"  Nhà cung cấp: {_resolve_supplier_name(invoice.supplier_id, container)}")
    _print(f"  Dòng hàng ({len(invoice.items)}):")
    for item in invoice.items:
        tax_label = item.tax_type.value if item.tax_type else "?"
        ratio_label = (
            item.retail_units_per_purchase_unit
            if item.retail_units_per_purchase_unit is not None
            else "?"
        )
        website_unit_ratio_label = (
            item.confirmed_website_unit_ratio
            if item.confirmed_website_unit_ratio is not None
            else "chưa xác nhận"
        )
        _print(
            f"    [item_id={item.id}] {item.medicine_name}: SL={item.quantity} "
            f"Đơn giá={item.unit_price} VAT={tax_label} "
            f"Hệ số quy đổi Viên={ratio_label} "
            f"Tỉ lệ đơn vị web={website_unit_ratio_label}"
        )

    issues = InvoiceValidator().validate(invoice).unwrap().issues
    if issues:
        _print("  Vấn đề hiện tại:")
        for issue in issues:
            _print(f"    - {issue}")

    corrected_fields: dict[str, str] = {}
    command: SubmitInvoiceReviewCommand | None = None
    while command is None:
        choice = input_fn(_REVIEW_PROMPT).strip().lower()

        if choice == "s":
            field_name = input_fn(_CORRECTION_FIELD_HINT).strip()
            if not field_name:
                continue
            field_value = input_fn("    Giá trị mới: ").strip()
            corrected_fields[field_name] = field_value
            _print(f"    (Đã ghi nhận: {field_name} = {field_value!r}. Chọn tiếp a/s/r.)")
            continue
        if choice == "a":
            command = SubmitInvoiceReviewCommand(
                invoice_id=invoice.id, corrected_fields=corrected_fields, reviewer_approved=True
            )
        elif choice == "r":
            command = SubmitInvoiceReviewCommand(
                invoice_id=invoice.id, corrected_fields=corrected_fields, reviewer_approved=False
            )
        elif choice == "":
            _print("  Bỏ qua hóa đơn này.")
            return None
        else:
            _print("  Lựa chọn không hợp lệ, thử lại.")

    result = submit_review_use_case.execute(command)
    if result.is_success:
        assert result.value is not None
        status_label = _STATUS_LABELS_VI.get(result.value.status, result.value.status)
        _print(f"  -> Kết quả: {status_label}")
        for warning in result.warnings:
            _print(f"     * {warning}")
    else:
        _print("  -> LỖI, hóa đơn vẫn ở trạng thái chờ xem lại:")
        for error in result.errors:
            _print(f"     - {error}")
    return result


# --- Stage D: browser automation against the real website -------------------

# PO-confirmed 2026-08: deliberately a full phrase, not a single-letter
# shortcut like Stage C's a/s/r -- this writes real data to a real,
# live business system. Must be typed exactly (case-sensitive, no
# trimmed-and-lowercased leniency) -- there is no default that proceeds
# on its own.
_AUTOMATION_CONFIRMATION_PHRASE = "XAC NHAN"


@dataclass(frozen=True)
class AutomationRunOutcome:
    """One READY_FOR_IMPORT invoice's outcome from a run_automate() pass."""

    invoice_id: str
    invoice_number: str
    skipped: bool
    dry_run: bool
    outcome: AutomationOutcome | None  # None only when skipped is True
    final_status: str


def _should_pause_for_dry_run_review(
    results: list[AutomationRunOutcome], dry_run: bool
) -> bool:
    """
    PO-confirmed 2026-08, after the first fully-successful --dry-run
    run: browser.close() in run_automate()'s own finally previously ran
    unconditionally, closing the browser the instant a dry-run pass
    finished -- defeating dry-run's whole purpose, since the PO never
    got to actually look at the browser before it vanished. A real
    (non-dry-run) run must never pause here.

    BUG FIX (2026-08, PO-confirmed after seeing the new
    _wait_for_row_settled safety check itself correctly catch a real
    problem and stop): originally only paused when every ATTEMPTED
    invoice succeeded -- but a FAILURE is exactly when the PO most
    needs to see the browser's actual state before it disappears
    (e.g. to inspect what a VerificationFailedError caught). Now
    pauses whenever at least one invoice was genuinely attempted
    (skipped ones don't count -- nothing was filled for those),
    regardless of whether it succeeded or failed.
    """
    if not dry_run:
        return False
    return any(not result.skipped for result in results)


def _dry_run_review_had_a_failure(results: list[AutomationRunOutcome]) -> bool:
    """Whether any genuinely-attempted invoice in this dry-run pass failed -- used only to
    pick the right message for _should_pause_for_dry_run_review's own pause prompt."""
    return any(
        result.outcome is not None and not result.outcome.success
        for result in results
        if not result.skipped
    )


def run_automate(
    container: ServiceContainer,
    input_fn: Callable[[str], str] = input,
    dry_run: bool = False,
    headless: bool = False,
) -> list[AutomationRunOutcome]:
    """
    Automate every PurchaseInvoice currently READY_FOR_IMPORT against
    the real webnhathuoc.com (Composition Root Stage D, PO-confirmed
    2026-08) -- the highest-risk stage: this writes real data to a
    real, live business system. Layered safety, on top of what was
    already built:

    - A real Playwright browser+page is launched HERE (not by Stage A's
      registration.py, which only wires the SUPPORTING pieces --
      SelectorRegistry, PlaywrightAutomationConfig -- since a browser's
      lifetime is this command's, not the DI container's) and
      registered into ``container`` before resolving
      BrowserAutomationProvider, exactly matching that factory's own
      documented expectation.
    - Every invoice's full detail (supplier, every line item's
      medicine/quantity/price) is printed BEFORE automating it, and the
      operator must type the full phrase "XAC NHAN" exactly -- no
      single-key shortcut, no default -- or that invoice is skipped.
    - Every line item's medicine is resolved on-site -- searched for,
      and created via the existing Package 2 create_medicine() (reusing
      its already-built "Nhom thuoc chon co san" group-selection path)
      if not already in the catalog -- immediately before that same
      line is selected and filled, one medicine at a time (see
      PlaywrightBrowserAutomationProvider._search_and_select_medicine_for_line
      and _create_medicine_for_line). NOT a separate pre-pass over
      every item any more (bug fix, PO-confirmed 2026-08 via direct
      real-time observation of a dry-run: the old
      composition_root.cli._resolve_medicine_on_site pre-pass typed
      every line item's name into the search box back-to-back with no
      selection/commit in between, before fill_and_save_invoice ever
      ran -- not how the real site's own workflow works, and suspected
      of leaving the site's search widget in a broken state).
    - ``dry_run=True`` runs every real step (login, resolve supplier,
      resolve/create every line's medicine, fill every line) but never
      clicks the final save -- see
      PlaywrightBrowserAutomationProvider.fill_and_save_invoice's own
      docstring.
    - Status integrity: READY_FOR_IMPORT -> IMPORT_IN_PROGRESS is
      persisted before the real save attempt (domain.constants.VALID_STATUS_TRANSITIONS
      requires this intermediate step -- there is no direct
      READY_FOR_IMPORT -> IMPORTED transition). On confirmed success
      (fill_and_save_invoice's own invoice.save_success_indicator
      check, not an assumption), IMPORT_IN_PROGRESS -> IMPORTED. On
      ANY failure -- an AutomationOutcome(success=False) OR an
      unexpected exception -- IMPORT_IN_PROGRESS -> IMPORT_FAILED ->
      READY_FOR_IMPORT, so the invoice always ends up at exactly one of
      READY_FOR_IMPORT (safe to retry) or IMPORTED (done) -- never left
      ambiguous. dry_run never touches persisted status at all --
      nothing was really attempted.
    """
    purchase_invoice_repository = container.resolve(PurchaseInvoiceRepository)
    invoices = purchase_invoice_repository.list_by_status(InvoiceStatus.READY_FOR_IMPORT)
    if not invoices:
        _print("Không có hóa đơn nào ở trạng thái READY_FOR_IMPORT.")
        return []

    _print(f"Có {len(invoices)} hóa đơn sẵn sàng nhập lên website.")
    if dry_run:
        _print(
            "*** CHẾ ĐỘ DRY-RUN: sẽ điền đầy đủ nhưng KHÔNG bấm 'Ghi Phiếu', "
            "không lưu gì thật lên website. ***"
        )
    _print()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        page = browser.new_page()
        try:
            container.register_instance(Page, page)
            try:
                provider = container.resolve(BrowserAutomationProvider)
            except RuntimeError as exc:
                _print(f"Không thể khởi tạo BrowserAutomationProvider: {exc}")
                return []

            login_outcome = provider.login()
            if not login_outcome.success:
                _print(f"Đăng nhập thất bại: {login_outcome.failure_reason}")
                return []
            _print("Đăng nhập thành công.\n")

            results: list[AutomationRunOutcome] = []
            for index, invoice in enumerate(invoices, start=1):
                _print(f"=== Hóa đơn {index}/{len(invoices)} ===")
                results.append(
                    _automate_one_invoice(invoice, container, provider, input_fn, dry_run)
                )
                _print()

            if _should_pause_for_dry_run_review(results, dry_run):
                if _dry_run_review_had_a_failure(results):
                    _print(
                        "*** DRY-RUN: CÓ LỖI xảy ra khi tự động hóa. Kiểm tra trạng thái "
                        "trên trình duyệt trước khi đóng. Nhấn Enter để đóng trình duyệt "
                        "và kết thúc... ***"
                    )
                else:
                    _print(
                        "*** DRY-RUN: đã điền xong, CHƯA lưu gì thật lên website. Kiểm tra "
                        "trình duyệt trước khi tiếp tục. Nhấn Enter để đóng trình duyệt và "
                        "kết thúc... ***"
                    )
                input_fn("")

            return results
        finally:
            browser.close()


def _automate_one_invoice(
    invoice: PurchaseInvoice,
    container: ServiceContainer,
    provider: BrowserAutomationProvider,
    input_fn: Callable[[str], str],
    dry_run: bool,
) -> AutomationRunOutcome:
    supplier_name = _resolve_supplier_name(invoice.supplier_id, container)
    _print(f"  Số hóa đơn: {invoice.invoice_number}")
    _print(f"  Nhà cung cấp: {supplier_name}")
    _print(f"  Dòng hàng ({len(invoice.items)}):")
    for item in invoice.items:
        _print(
            f"    - {item.medicine_name}: SL={item.quantity} "
            f"Đơn giá={item.unit_price} Thành tiền={item.line_total}"
        )

    confirmation = input_fn(
        f"  Gõ chính xác \"{_AUTOMATION_CONFIRMATION_PHRASE}\" để tiếp tục tự động hóa "
        "hóa đơn này lên website thật (bất kỳ giá trị nào khác sẽ bỏ qua) > "
    )
    if confirmation != _AUTOMATION_CONFIRMATION_PHRASE:
        _print("  Đã bỏ qua (không gõ đúng xác nhận).")
        return AutomationRunOutcome(
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            skipped=True,
            dry_run=dry_run,
            outcome=None,
            final_status=invoice.status.value,
        )

    purchase_invoice_repository = container.resolve(PurchaseInvoiceRepository)

    # Transitioned BEFORE any real automation step (not just before
    # fill_and_save_invoice): domain.constants.VALID_STATUS_TRANSITIONS
    # only allows READY_FOR_IMPORT -> IMPORT_IN_PROGRESS -> {IMPORTED,
    # IMPORT_FAILED} -- there is no direct READY_FOR_IMPORT ->
    # IMPORT_FAILED. If open_import_invoice_form() or supplier
    # resolution fails before fill_and_save_invoice is ever called,
    # _finish_automation_attempt still needs a valid IMPORT_FAILED
    # transition to reach from, or PurchaseInvoice.transition_to()
    # itself would raise. dry_run never touches persisted status at
    # all -- nothing was really attempted.
    if not dry_run:
        invoice.transition_to(InvoiceStatus.IMPORT_IN_PROGRESS)
        purchase_invoice_repository.update(invoice)

    try:
        open_form_outcome = provider.open_import_invoice_form()
        if not open_form_outcome.success:
            _print(f"  Lỗi mở phiếu nhập: {open_form_outcome.failure_reason}")
            return _finish_automation_attempt(
                invoice, purchase_invoice_repository, open_form_outcome, dry_run
            )

        supplier_outcome = _resolve_supplier_on_site(invoice, container, provider, supplier_name)
        if not supplier_outcome.success:
            _print(f"  Lỗi xử lý nhà cung cấp: {supplier_outcome.failure_reason}")
            return _finish_automation_attempt(
                invoice, purchase_invoice_repository, supplier_outcome, dry_run
            )

        fill_outcome = provider.fill_and_save_invoice(invoice, dry_run=dry_run)
    except UnitMismatchError as exc:
        # Distinguished from the generic Exception handler below
        # (PO decision, 2026-08 -- "Coldi-B DNH" 1 Hop = 1 Lọ proved a
        # unit-label mismatch is sometimes a genuine, correct
        # site-vs-invoice naming difference, not a bug): this invoice
        # still stops safely here, exactly like any other automation
        # failure, but the operator is pointed at the specific fix --
        # confirming a ratio via the review step -- instead of a
        # generic "unexpected error" message.
        _print(f"  LỖI LỆCH ĐƠN VỊ: {exc}")
        _print(
            f"  -> Xác nhận tỉ lệ quy đổi qua bước 'review' (item.{exc.purchase_item_id}."
            "confirmed_website_unit_ratio) trước khi chạy lại automate cho hóa đơn này."
        )
        fill_outcome = AutomationOutcome(success=False, failure_reason=str(exc))
        return _finish_automation_attempt(
            invoice, purchase_invoice_repository, fill_outcome, dry_run
        )
    except Exception as exc:  # noqa: BLE001 -- must not leave status ambiguous either way
        _print(f"  LỖI KHÔNG MONG ĐỢI: {exc}")
        fill_outcome = AutomationOutcome(success=False, failure_reason=str(exc))
        return _finish_automation_attempt(
            invoice, purchase_invoice_repository, fill_outcome, dry_run
        )

    return _finish_automation_attempt(invoice, purchase_invoice_repository, fill_outcome, dry_run)


def _resolve_supplier_on_site(
    invoice: PurchaseInvoice,
    container: ServiceContainer,
    provider: BrowserAutomationProvider,
    supplier_name: str,
) -> AutomationOutcome:
    if invoice.supplier_id is None:
        return AutomationOutcome(
            success=False, failure_reason="Invoice has no resolved supplier_id."
        )

    # Bug fix (PO-confirmed 2026-08, a "forgot to wire it up" gap, not a
    # new decision): must run before search_supplier -- while the
    # invoice form's default "Hang nhap le" supplier tag is still
    # present, the "Nha cung cap" row does not match what a real
    # supplier search expects.
    tag_removal_outcome = provider.remove_default_supplier_tag()
    if not tag_removal_outcome.success:
        return tag_removal_outcome

    try:
        found = provider.search_supplier(supplier_name)
    except Exception as exc:  # noqa: BLE001
        return AutomationOutcome(success=False, failure_reason=f"search_supplier raised: {exc}")

    if found:
        return provider.select_supplier(supplier_name)

    supplier = container.resolve(SupplierRepository).get_by_id(invoice.supplier_id)
    if supplier is None:
        return AutomationOutcome(
            success=False,
            failure_reason=f"Supplier '{invoice.supplier_id}' referenced by this invoice was "
            "not found in the local database.",
        )
    return provider.create_supplier(supplier)


def _finish_automation_attempt(
    invoice: PurchaseInvoice,
    purchase_invoice_repository: PurchaseInvoiceRepository,
    outcome: AutomationOutcome,
    dry_run: bool,
) -> AutomationRunOutcome:
    """
    Apply the correct InvoiceStatus transition for ``outcome`` and
    persist it -- the one place this decision is made, so every early-
    return path in _automate_one_invoice goes through it identically.
    dry_run never transitions or persists anything: nothing was really
    attempted.
    """
    if dry_run:
        if outcome.success:
            _print(
                "  [DRY-RUN] Đã điền xong nhà cung cấp + dòng hàng, KHÔNG bấm 'Ghi Phiếu'. "
                "Xem lại trên trình duyệt thật để kiểm tra trước khi chạy thật."
            )
        else:
            _print(f"  [DRY-RUN] Dừng do lỗi: {outcome.failure_reason}")
        return AutomationRunOutcome(
            invoice_id=invoice.id,
            invoice_number=invoice.invoice_number,
            skipped=False,
            dry_run=True,
            outcome=outcome,
            final_status=invoice.status.value,
        )

    if outcome.success:
        invoice.transition_to(InvoiceStatus.IMPORTED)
        purchase_invoice_repository.update(invoice)
        _print("  -> ĐÃ NHẬP THÀNH CÔNG lên website.")
    else:
        invoice.transition_to(InvoiceStatus.IMPORT_FAILED)
        invoice.transition_to(InvoiceStatus.READY_FOR_IMPORT)
        purchase_invoice_repository.update(invoice)
        _print(f"  -> THẤT BẠI: {outcome.failure_reason}")
        _print("     Hóa đơn được giữ ở trạng thái READY_FOR_IMPORT để có thể chạy lại an toàn.")

    return AutomationRunOutcome(
        invoice_id=invoice.id,
        invoice_number=invoice.invoice_number,
        skipped=False,
        dry_run=False,
        outcome=outcome,
        final_status=invoice.status.value,
    )
