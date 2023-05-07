import logging
import sys

from PyQt6.QtWidgets import QApplication

from wannadb.resources import ResourceManager
from wannadb_ui.main_window import MainWindow

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger()

if __name__ == "__main__":
    logger.info("Starting wannadb_ui.")

    with ResourceManager() as resource_manager:
        # set up PyQt application
        app = QApplication(sys.argv)

        window = MainWindow()

        sys.exit(app.exec())
