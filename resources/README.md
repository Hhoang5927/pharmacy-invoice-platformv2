# Resources

| Folder | Purpose |
|---|---|
| `ocr_samples/` | Representative invoice photos used during OCR development and manual QA (distinct from `tests/golden/ocr_golden_files/`, which holds the *curated, expected-output-paired* golden set). |
| `golden_images/` | Reference/expected preprocessed images for visually verifying the OpenCV preprocessing pipeline (Technical Design Document Section 7.2). |
| `templates/` | Any document/export templates (e.g. Excel export layout, FR-13). |
| `icons/` | Application icons (window icon, tray icon, toolbar icons). |
| `translations/` | Vietnamese/English UI translation files, should localization be added. |
| `static_assets/` | Any other static asset not covered above. |

All currently empty except for a `.gitkeep` placeholder; populated as
each relevant prompt (05, 07) needs them.
