# Invoice Extraction Prompt (v1)

**Status:** placeholder — this file is a scaffold only.

The actual Gemini Vision prompt text is authored in Prompt 05
(Infrastructure) per Implementation Specification Section 6
(`infrastructure/ocr` module contract) and Technical Design Document
Section 7.3 (Gemini Request & Prompt Design).

This file exists now so that `gemini_adapter.py` has a versioned,
external file to load from day one, per the rule that prompts are never
inlined as string literals in code.
