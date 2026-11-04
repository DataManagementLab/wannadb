import logging
import os
import sys

# The macOS PyTorch, scikit-learn and FAISS wheels bundle separate OpenMP
# runtimes that can crash when used together with multiple worker threads.
# Set this before importing them, while allowing an explicit user override.
if sys.platform == "darwin":
    os.environ.setdefault("OMP_NUM_THREADS", "1")

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger()


def main():
    logger.info("Starting wannadb_ui.")

    # UI imports currently create widgets, so initialize the application first.
    app = QApplication.instance()
    if app is None:
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
        app = QApplication(sys.argv)

    from wannadb.resources import ResourceManager
    from wannadb_ui.main_window import MainWindow

    with ResourceManager() as resource_manager:
        window = MainWindow()
        return app.exec()


if __name__ == "__main__":
    sys.exit(main())
