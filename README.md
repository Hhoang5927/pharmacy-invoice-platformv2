# Pharmacy Purchase Invoice Automation

Desktop Windows application that automates importing hundreds of
pharmacy purchase invoices — from photographed images, through Gemini
Vision OCR, human review, and Playwright-driven website automation —
into `webnhathuoc.com`.

> **Status:** project skeleton only (Prompt 03). No business logic has
> been implemented yet. See [`docs/architecture/`](docs/architecture/)
> for the full, approved design.

## Documentation

| Document | Contents |
|---|---|
| [`docs/architecture/Technical_Design_Document.md`](docs/architecture/Technical_Design_Document.md) | System architecture, technology stack, data flow, OCR/automation design, storage, security, testing strategy |
| [`docs/architecture/Implementation_Blueprint.md`](docs/architecture/Implementation_Blueprint.md) | Phase-by-phase build order, dependency graph, module/service/repository/UI ordering, milestones |
| [`docs/architecture/Implementation_Specification.md`](docs/architecture/Implementation_Specification.md) | File-level folder specification, import rules, module contracts, parallel (multi-agent) development plan |
| [`docs/Architecture.md`](docs/Architecture.md) | Short pointer/summary — start here, then go to the full documents above |
| [`docs/Development.md`](docs/Development.md) | Local dev environment setup |
| [`docs/Testing.md`](docs/Testing.md) | How to run the test suite |
| [`docs/Deployment.md`](docs/Deployment.md) | Packaging/deployment notes |
| [`docs/Contributing.md`](docs/Contributing.md) | Coding standards and contribution process |

## Quick Start

```bash
# 1. Create and activate a virtual environment (Python 3.12+)
python -m venv .venv
.venv\Scripts\activate            # Windows
# source .venv/bin/activate       # macOS/Linux, for development only —
#                                 # the shipped app targets Windows

# 2. Install dependencies
pip install -r requirements-dev.txt
playwright install                # downloads browser binaries

# 3. Configure local environment
copy .env.example .env            # Windows
# cp .env.example .env            # macOS/Linux
# then edit .env with a real (dev/test) Gemini API key and credentials

# 4. Set up pre-commit hooks
pre-commit install

# 5. Run the (currently skeleton-only) test suite
pytest -m unit
```

## Project Structure

```
src/pharmacy_invoice_automation/   # the application package (src layout)
├── domain/            # Package 01 — entities, value objects, enums, rules, ports
├── shared/             #             framework-agnostic utilities
├── application/        # Package 02 — use case orchestration services
├── infrastructure/      # Package 03 — Gemini, Playwright, SQLite, logging, config
├── presentation/        # Package 04 — PySide6 UI
└── composition_root/    # Package 05 — dependency injection wiring, entry point

tests/                  # Package 06 — unit, integration, golden, e2e, mocks, fixtures
config/                 # non-secret application/logging/selector-registry config
resources/              # OCR samples, templates, icons, translations, static assets
scripts/                # developer convenience scripts
docs/                   # this documentation, including the full architecture set
```

See `docs/architecture/Implementation_Specification.md` Section 3 for
the complete, file-by-file folder specification.

## Build / Implementation Order

This project is implemented prompt-by-prompt, each one scoped to a
specific package, per `docs/architecture/Implementation_Specification.md`
Section 13 (Prompt Mapping):

1. **Prompt 03** *(this one)* — Project Bootstrap & Skeleton Generation
2. **Prompt 04** — Domain Layer
3. **Prompt 05** — Infrastructure
4. **Prompt 06** — Application Layer
5. **Prompt 07** — UI Layer
6. **Prompt 08** — Integration, Testing & Production Audit

No architectural decisions remain open for any of these — see the three
documents in `docs/architecture/` for the full, resolved design.
