import logging

from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from wannadb_ui.common import LABEL_FONT, MainWindowContent, \
    SUBHEADER_FONT

logger = logging.getLogger(__name__)


class StartMenuWidget(MainWindowContent):
    def __init__(self, main_window):
        super(StartMenuWidget, self).__init__(main_window, "Welcome to WannaDB!")

        self.setMaximumWidth(400)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(30)

        self.create_new_document_base_widget = QWidget()
        self.create_new_document_base_layout = QVBoxLayout(self.create_new_document_base_widget)
        self.create_new_document_base_layout.setContentsMargins(0, 0, 0, 0)
        self.create_new_document_base_layout.setSpacing(10)
        self.layout.addWidget(self.create_new_document_base_widget)

        self.create_new_document_base_subheader = QLabel("Create a new document base.")
        self.create_new_document_base_subheader.setFont(SUBHEADER_FONT)
        self.create_new_document_base_layout.addWidget(self.create_new_document_base_subheader)

        self.create_new_document_base_wrapper_widget = QWidget()
        self.create_new_document_base_wrapper_layout = QHBoxLayout(self.create_new_document_base_wrapper_widget)
        self.create_new_document_base_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        self.create_new_document_base_wrapper_layout.setSpacing(20)
        self.create_new_document_base_wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.create_new_document_base_layout.addWidget(self.create_new_document_base_wrapper_widget)

        self.create_document_base_button = QPushButton()
        self.create_document_base_button.setFixedHeight(45)
        self.create_document_base_button.setFixedWidth(45)
        self.create_document_base_button.setIcon(QIcon("wannadb_ui/resources/two_documents.svg"))
        self.create_document_base_button.setIconSize(QSize(25, 25))
        self.create_document_base_button.clicked.connect(self.main_window.show_document_base_creator_widget_task)
        self.create_new_document_base_wrapper_layout.addWidget(self.create_document_base_button)

        self.create_document_base_label = QLabel(
            "Create a new document base from a directory\nof .txt files and a list of attribute names.")
        self.create_document_base_label.setFont(LABEL_FONT)
        self.create_new_document_base_wrapper_layout.addWidget(self.create_document_base_label)

        self.load_document_base_widget = QWidget()
        self.load_document_base_layout = QVBoxLayout(self.load_document_base_widget)
        self.load_document_base_layout.setContentsMargins(0, 0, 0, 0)
        self.load_document_base_layout.setSpacing(10)
        self.layout.addWidget(self.load_document_base_widget)

        self.load_document_base_subheader = QLabel("Load an existing document base.")
        self.load_document_base_subheader.setFont(SUBHEADER_FONT)
        self.load_document_base_layout.addWidget(self.load_document_base_subheader)

        self.load_document_base_wrapper_widget = QWidget()
        self.load_document_base_wrapper_layout = QHBoxLayout(self.load_document_base_wrapper_widget)
        self.load_document_base_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        self.load_document_base_wrapper_layout.setSpacing(20)
        self.load_document_base_wrapper_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.load_document_base_layout.addWidget(self.load_document_base_wrapper_widget)

        self.load_document_base_button = QPushButton()
        self.load_document_base_button.setFixedHeight(45)
        self.load_document_base_button.setFixedWidth(45)
        self.load_document_base_button.setIcon(QIcon("wannadb_ui/resources/folder.svg"))
        self.load_document_base_button.setIconSize(QSize(25, 25))
        self.load_document_base_button.clicked.connect(self.main_window.load_document_base_from_bson_task)
        self.load_document_base_wrapper_layout.addWidget(self.load_document_base_button)

        self.load_document_base_label = QLabel("Load an existing document base\nfrom a .bson file.")
        self.load_document_base_label.setFont(LABEL_FONT)
        self.load_document_base_wrapper_layout.addWidget(self.load_document_base_label)

    def enable_input(self):
        self.create_document_base_button.setEnabled(True)
        self.load_document_base_button.setEnabled(True)

    def disable_input(self):
        self.create_document_base_button.setDisabled(True)
        self.load_document_base_button.setDisabled(True)
