"""Offline application icon from the user-requested Aurora site artwork."""
from importlib import resources
import sys

from PySide6.QtGui import QIcon, QPixmap


def application_icon():
    icon = QIcon()
    try:
        data = resources.files("glass_workbench").joinpath("assets", "aurora-touch.png").read_bytes()
    except (OSError, ModuleNotFoundError):
        return icon
    pixmap = QPixmap()
    if pixmap.loadFromData(data, "PNG"):
        icon.addPixmap(pixmap)
    return icon


def configure_application_icon(app):
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("GlassWorkbench.Desktop")
        except (AttributeError, OSError):
            pass
    app.setWindowIcon(application_icon())
