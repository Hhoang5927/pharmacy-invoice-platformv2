"""
Developer convenience script: runs the application the same way
`main.py` / the `pharmacy-invoice-automation` console script does, but
runnable directly from a repo checkout without an editable install.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from pharmacy_invoice_automation.composition_root.bootstrap import main  # noqa: E402

if __name__ == "__main__":
    main()
