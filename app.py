"""DM40-Host-computer – dev entry (console shows errors). For daily use: app.pyw or DM40-Host-computer.bat."""

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.single_instance import acquire, focus_existing
from gui.app_window import run_app

if __name__ == "__main__":
    if not acquire():
        focus_existing("DM40-Host-computer")
        sys.exit(0)
    run_app()
