# Pharmacy Invoice Automation System
## Documentation Repository

> Version: 1.0.0
>
> Status: Draft
>
> Author: Project Documentation Team
>
> Last Updated: YYYY-MM-DD

---

# Purpose

This repository contains the complete functional and technical specification of the Pharmacy Invoice Automation System.

It is the **single source of truth** for the entire project.

All implementation decisions, architectural decisions, business rules, AI prompts, OCR logic, validation logic and automation workflows must follow the specifications defined in this documentation.

If implementation conflicts with documentation, **documentation always takes precedence**.

---

# Project Overview

The Pharmacy Invoice Automation System is an internal business application designed to automate the processing of pharmaceutical purchase invoices.

The primary goal is to minimize manual data entry while maintaining a very high level of accuracy.

The system processes supplier invoices through multiple stages:

1. OCR
2. AI Data Extraction
3. Business Validation
4. Human Review
5. Excel Generation
6. Web Automation
7. Verification
8. Reporting

The final objective is to automatically create purchase invoices inside the pharmacy management website with minimal human intervention.

---

# Business Objective

The business objective is **not** to build an OCR application.

The business objective is **not** to build an AI chatbot.

The business objective is:

> Process hundreds of supplier invoices accurately, consistently, and significantly faster than manual entry.

Success is measured by:

- Accuracy
- Reliability
- Recoverability
- Auditability
- Processing Speed

---

# Documentation Philosophy

This documentation follows a Specification-Driven Development approach.

Business requirements are defined first.

Architecture is designed second.

Implementation is performed last.

Code must never redefine business requirements.

---

# Intended Audience

This documentation is written for:

- Product Owner
- Business Analyst
- Solution Architect
- Software Engineer
- QA Engineer
- AI Coding Assistant (Claude, ChatGPT, Gemini, Cursor, etc.)
- Future Maintainers

---

# Documentation Structure

```
docs/
│
├── README.md
├── PROJECT_RULES.md
├── 00_PROJECT_OVERVIEW.md
├── 01_PROJECT_VISION.md
├── 02_BUSINESS_WORKFLOW.md
├── 03_BUSINESS_RULES.md
├── 04_SYSTEM_ARCHITECTURE.md
├── 05_DATA_MODEL.md
├── 06_OCR_SPECIFICATION.md
├── 07_AI_EXTRACTION_SPEC.md
├── 08_WEB_AUTOMATION_SPEC.md
├── 09_EXCEL_SPECIFICATION.md
├── 10_ERROR_HANDLING.md
├── 11_PERFORMANCE_TARGET.md
├── 12_UI_SPECIFICATION.md
├── 13_CONFIGURATION.md
├── 14_TESTING_STRATEGY.md
├── 15_DEPLOYMENT.md
├── 16_GLOSSARY.md
│
├── adr/
│
└── diagrams/
```

---

# Reading Order

Every developer and every AI assistant must read the documentation in the following order.

1. README.md
2. PROJECT_RULES.md
3. PROJECT_OVERVIEW.md
4. PROJECT_VISION.md
5. BUSINESS_WORKFLOW.md
6. BUSINESS_RULES.md
7. SYSTEM_ARCHITECTURE.md
8. Remaining technical documents

Reading documents out of order is discouraged.

---

# Documentation Categories

The documentation is divided into four logical groups.

## Business

Describes why the system exists.

Examples:

- Vision
- Workflow
- Business Rules

---

## Architecture

Describes how the system is organized.

Examples:

- Clean Architecture
- Domain Model
- Dependency Rules

---

## Technical Specifications

Defines implementation requirements.

Examples:

- OCR
- AI Extraction
- Web Automation
- Excel

---

## Quality

Defines non-functional requirements.

Examples:

- Error Handling
- Performance
- Testing
- Deployment

---

# Naming Convention

Business Rules

```
BR-XXX
```

Functional Requirements

```
FR-XXX
```

Non-Functional Requirements

```
NFR-XXX
```

Architecture Decision Records

```
ADR-XXX
```

Error Codes

```
ERR-XXX
```

Workflow Steps

```
WF-XXX
```

---

# Documentation Priority

If two documents appear to conflict, the following priority applies.

1. PROJECT_RULES.md
2. BUSINESS_RULES.md
3. BUSINESS_WORKFLOW.md
4. PROJECT_VISION.md
5. Remaining documents

Higher priority documents override lower priority documents.

---

# Change Management

Documentation is version-controlled.

Every significant modification must:

- explain the reason
- update the changelog
- preserve backward understanding where possible

Business documents must not be modified without explicit approval from the Project Owner.

---

# AI Assistant Instructions

Any AI assistant working on this repository must follow these principles.

- Read the documentation before writing code.
- Never invent business requirements.
- Never redesign the workflow without approval.
- Never modify business rules without approval.
- Ask questions when requirements are ambiguous.
- Prefer correctness over assumptions.

---

# Out of Scope

This documentation does not describe:

- Python syntax
- Framework tutorials
- Library documentation
- Generic OCR theory
- Generic AI concepts

Only project-specific decisions belong here.

---

# Repository Status

Current Phase:

Specification

Current Package:

Pack 01 – Business Foundation

Implementation Status:

Not Started

---

# Long-Term Goal

Create a maintainable, extensible and production-ready pharmacy invoice automation platform capable of processing large volumes of supplier invoices with high accuracy, strong auditability and minimal manual effort.

---

# License

Internal Use Only.

This repository is intended for the development and maintenance of the Pharmacy Invoice Automation System.

Unauthorized redistribution is not recommended.
