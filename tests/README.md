# Test Suite

Structure mirrors Implementation Specification Section 3 (Folder
Specification) and Section 9 (Testing Strategy in the Implementation
Blueprint):

- `unit/` — fully-isolated domain and application tests, run against fakes.
- `integration/` — tests against a real (test) SQLite file, and the full
  end-to-end pipeline once Package 05 exists.
- `e2e/` — Playwright automation tests against staging or fixture HTML.
- `golden/` — OCR golden-file regression tests and automation fixtures.
- `mocks/` — fake implementations of every `domain.ports` interface.
- `fixtures/` — shared sample data (sample invoices, etc.).
- `helpers/` — shared test utility code.

Run with: `pytest` (see `pytest.ini` for markers: `unit`, `integration`,
`golden`, `e2e`, `ui`, `load`).
