"""
Application entry point. Delegates to composition_root.bootstrap.main(),
the same function the 'pharmacy-invoice-automation' console script
(pyproject.toml) resolves to -- so `python -m pharmacy_invoice_automation`
and the installed console script behave identically.
"""

from __future__ import annotations

from pharmacy_invoice_automation.composition_root.bootstrap import main

if __name__ == "__main__":
    main()
