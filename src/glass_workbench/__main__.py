from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Optical glass workbench with CDGM, SCHOTT, HPFS 7980 and silicon")
    parser.add_argument("--no-autoload", action="store_true", help="Start without scanning the working directory")
    parser.add_argument("--catalog", action="append", type=Path, default=[], help="Load an external official workbook (repeat for both suppliers)")
    parser.add_argument("--agf", action="append", type=Path, default=[], help="Load an explicit AGF catalog (repeat for multiple sources)")
    parser.add_argument("--smoke-test", action="store_true", help="Open offscreen-compatible window and exit after initialization")
    parser.add_argument("--smoke-help", action="store_true", help="Open the Help dialog during --smoke-test; --screenshot captures Help")
    parser.add_argument("--screenshot", type=Path, help="Save a GUI screenshot after initialization (used with --smoke-test)")
    args = parser.parse_args()
    if args.smoke_help and not args.smoke_test:
        parser.error("--smoke-help requires --smoke-test")
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication
    from glass_workbench.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("GlassWorkbench")
    app.setOrganizationName("OpticalTools")
    from glass_workbench.ui.app_icon import configure_application_icon
    configure_application_icon(app)
    window = MainWindow(auto_load=not args.no_autoload and not args.catalog)
    window.show()
    if args.catalog:
        QTimer.singleShot(0, lambda: window.load_paths(args.catalog))
    if args.agf:
        window.tabs.setCurrentWidget(window.agf)
        QTimer.singleShot(0, lambda: window.agf.load_paths(args.agf))
    if args.smoke_test:
        def capture_and_close():
            target = window.help_dialog if args.smoke_help else window
            if args.screenshot:
                target.grab().save(str(args.screenshot))
            if args.smoke_help:
                window.help_dialog.close()
            window.close()

        def finish():
            if window.import_job.busy or window.agf.job.busy:
                QTimer.singleShot(200, finish)
                return
            if args.smoke_help:
                window.show_help()
                # Allow the dialog's show/layout/paint events before capturing it.
                QTimer.singleShot(200, capture_and_close)
            else:
                capture_and_close()
        QTimer.singleShot(1200, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
