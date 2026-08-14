from pathlib import Path
import sys


def app_root() -> Path:
    """Return the runtime resource root in both source and PyInstaller builds."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def resource_path(*parts: str) -> Path:
    return app_root().joinpath(*parts)
