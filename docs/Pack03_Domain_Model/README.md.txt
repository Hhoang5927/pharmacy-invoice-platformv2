# PACK 03 - DOMAIN MODEL

> Version: 1.0.0

---

# Purpose

This pack defines the complete domain model of the Pharmacy Invoice Automation Platform.

The objective is to establish a single source of truth for all business entities exchanged between OCR, AI Extraction, Validation, Human Review, Excel Export and Browser Automation.

Every module in the system shall use the domain model defined in this pack.

---

# Scope

This pack specifies:

- Business Entities
- Relationships
- Value Objects
- Enumerations
- DTOs
- Repository Contracts
- JSON Schemas
- Excel Mapping

Implementation details are intentionally excluded.

---

# Design Principles

The domain model follows these principles:

- Business-oriented
- Technology-independent
- Immutable where appropriate
- Strong typing
- Explicit relationships
- Consistent naming

---

# Domain Overview

Core entities include:

Invoice

Supplier

Medicine

Purchase Item

Batch

Approved Dataset

Supporting objects include:

Money

Quantity

Date

Invoice Status

Validation Status

Review Decision

DTOs

Repositories

---

# Dependencies

Depends On

Pack 01 — Business

Pack 02 — Architecture

Referenced By

Pack 04 — Technical Specification

Pack 05 — Development Guide

Pack 06 — Testing & Deployment

---

# Naming Convention

Entity documents:

DM-001

DM-002

...

Supporting documents:

DM-007+

---

# Completion Criteria

This pack is complete when:

- Every business entity is defined.
- Relationships are documented.
- JSON schema is specified.
- Repository contracts are defined.
- Excel mapping is finalized.

---

# End of Document