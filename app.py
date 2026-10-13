"""OmniStore AI Manager desktop entry point."""

from omnistore.ui import run
from premium_ui_stage import install_premium_ui

install_premium_ui()

if __name__ == "__main__":
    raise SystemExit(run())
