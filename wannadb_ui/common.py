from abc import ABC, abstractmethod
from enum import Enum
from typing import Union, List, Optional, Tuple

import markdown
import pyqtgraph
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QFont, QPixmap, QPainter, QColor
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QHBoxLayout, QDialog, QPushButton, \
    QMainWindow, QTextEdit

from wannadb.data.data import InformationNugget

# fonts
HEADER_FONT = QFont("Segoe UI", pointSize=20, weight=QFont.Weight.Bold)
SUBHEADER_FONT = QFont("Segoe UI", pointSize=14, weight=QFont.Weight.DemiBold)
LABEL_FONT = QFont("Segoe UI", pointSize=11)
LABEL_FONT_BOLD = QFont("Segoe UI", pointSize=11, weight=QFont.Weight.Bold)
LABEL_FONT_ITALIC = QFont("Segoe UI", pointSize=11, italic=True)
CODE_FONT = QFont("Consolas", pointSize=12)
CODE_FONT_SMALLER = QFont("Consolas", pointSize=10)
CODE_FONT_BOLD = QFont("Consolas", pointSize=12, weight=QFont.Weight.Bold)
MENU_FONT = QFont("Segoe UI", pointSize=11)
STATUS_BAR_FONT = QFont("Segoe UI", pointSize=11)
STATUS_BAR_FONT_BOLD = QFont("Segoe UI", pointSize=11, weight=QFont.Weight.Bold)
BUTTON_FONT = QFont("Segoe UI", pointSize=11)
BUTTON_FONT_SMALL = QFont("Segoe UI", pointSize=9)

# colors
WHITE = "#FFFFFF"
BLACK = "#000000"

YELLOW = "#FEC306"
LIGHT_YELLOW = "#ffefca"
ORANGE = "#F69200"
LIGHT_ORANGE = "#ffe3c6"
RED = "#DF5327"
LIGHT_RED = "#ffd5c6"
BLUE = "#418AB3"
LIGHT_BLUE = "#d3e1ec"
GREEN = "#A6B727"
LIGHT_GREEN = "#ececcb"

INPUT_DOCS_COLUMN_NAME = "input_document"


class ThresholdPosition(Enum):
    ABOVE = 1
    BELOW = 2


class AvailableVisualizationsLevel(Enum):
    DISABLED = 0
    LEVEL_1 = 1
    LEVEL_2 = 2


class NuggetUpdateType(Enum):
    NEWLY_ADDED = 1
    THRESHOLD_POSITION_UPDATE = 2
    BEST_MATCH_UPDATE = 3


class AddedReason(Enum):
    MOST_UNCERTAIN = "The documents match belongs to the considered most uncertain matches."
    INTERESTING_ADDITIONAL_EXTRACTION = "The document recently got interesting additional extraction to the list."
    AT_THRESHOLD = "The distance of the guessed match is within the considered range around the threshold."

    def __init__(self, corresponding_tooltip_text: str):
        self._corresponding_tooltip_text = corresponding_tooltip_text

    @property
    def corresponding_tooltip_text(self):
        return self._corresponding_tooltip_text


class VisualizationProvidingItem:
    def __init__(self,  *args, **kwargs):
        super().__init__(*args, **kwargs)

    def update_shown_visualizations(self, visualization_level: AvailableVisualizationsLevel):
        self._adapt_to_visualizations_level(visualization_level)

    @abstractmethod
    def _adapt_to_visualizations_level(self, visualizations_level):
        pass


class MainWindowContent(QWidget):

    def __init__(self, main_window, header_text):
        super(MainWindowContent, self).__init__()
        self.main_window = main_window

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10, 5, 10, 5)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.layout.setSpacing(20)

        self.top_widget = QWidget()
        self.top_widget_layout = QHBoxLayout(self.top_widget)
        self.top_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.top_widget)

        self.header = QLabel(header_text)
        self.header.setFont(HEADER_FONT)
        self.top_widget_layout.addWidget(self.header, alignment=Qt.AlignmentFlag.AlignLeft)

        self.controls_widget = QWidget()
        self.controls_widget_layout = QHBoxLayout(self.controls_widget)
        self.controls_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.top_widget_layout.addWidget(self.controls_widget, alignment=Qt.AlignmentFlag.AlignRight)

    @abstractmethod
    def enable_input(self):
        raise NotImplementedError

    @abstractmethod
    def disable_input(self):
        raise NotImplementedError


class MainWindowContentSection(QWidget):

    def __init__(self, main_window_content, sub_header_text):
        super(MainWindowContentSection, self).__init__()
        self.main_window_content = main_window_content

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.layout.setSpacing(10)

        self.sub_header = QLabel(sub_header_text)
        self.sub_header.setFont(SUBHEADER_FONT)
        self.layout.addWidget(self.sub_header)


class CustomScrollableList(QWidget):

    def __init__(self, parent, item_type, floating_widget=None, orientation="vertical", above_widget=None):
        super(CustomScrollableList, self).__init__()
        self.parent = parent
        self.item_type = item_type
        self.floating_widget = floating_widget
        self.above_widget = above_widget

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.list_widget = QWidget()
        if orientation == "vertical":
            self.list_layout = QVBoxLayout(self.list_widget)
            self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        elif orientation == "horizontal":
            self.list_layout = QHBoxLayout(self.list_widget)
            self.list_layout.setAlignment(Qt.AlignmentFlag.AlignLeft)
        else:
            assert False, f"Unknown mode '{orientation}'!"
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(10)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameStyle(0)
        self.scroll_area.setWidget(self.list_widget)
        self.layout.addWidget(self.scroll_area)

        if self.above_widget is not None:
            self.list_layout.addWidget(self.above_widget)

        if self.floating_widget is not None:
            self.list_layout.addWidget(self.floating_widget)

        self.item_widgets = []
        self.num_visible_item_widgets = 0

    def last_item_widget(self):
        return self.item_widgets[self.num_visible_item_widgets - 1]

    def update_item_list(self, item_list, params=None):

        if self.floating_widget is not None:
            self.list_layout.removeWidget(self.floating_widget)

        # make sure that there are enough item widgets
        while len(item_list) > len(self.item_widgets):
            self.item_widgets.append(self._create_new_widget())

        # make sure that the correct number of item widgets is shown
        while len(item_list) > self.num_visible_item_widgets:
            widget = self.item_widgets[self.num_visible_item_widgets]
            self.list_layout.addWidget(widget)
            widget.show()
            self.num_visible_item_widgets += 1

        while len(item_list) < self.num_visible_item_widgets:
            widget = self.item_widgets[self.num_visible_item_widgets - 1]
            widget.hide()
            self.list_layout.removeWidget(widget)
            self.num_visible_item_widgets -= 1

        if self.floating_widget is not None:
            self.list_layout.addWidget(self.floating_widget)

        # update item widgets
        for item, item_widget in zip(item_list, self.item_widgets[:len(item_list)]):
            item_widget.update_item(item, params)

    def enable_input(self):
        for item_widget in self.item_widgets:
            item_widget.enable_input()

    def disable_input(self):
        for item_widget in self.item_widgets:
            item_widget.disable_input()

    def _create_new_widget(self):
        return self.item_type(self.parent)


class VisualizationProvidingCustomScrollableList(CustomScrollableList, VisualizationProvidingItem):
    def __init__(self, parent, item_type, visualizations_level, attach_visualization_level_observer,
                 floating_widget=None, orientation="vertical", above_widget=None):
        super().__init__(parent, item_type, floating_widget, orientation, above_widget)

        self.visualizations_level = visualizations_level
        self.attach_visualization_level_observer = attach_visualization_level_observer

    def _create_new_widget(self):
        new_widget = self.item_type(self.parent, self.visualizations_level)
        self.attach_visualization_level_observer(new_widget)
        return new_widget

    def _adapt_to_visualizations_level(self, visualizations_level):
        self.visualizations_level = visualizations_level


class CustomScrollableListItem(QFrame):

    def __init__(self, parent):
        super(CustomScrollableListItem, self).__init__()
        self.parent = parent

    @abstractmethod
    def update_item(self, item, params=None):
        raise NotImplementedError

    @abstractmethod
    def enable_input(self):
        raise NotImplementedError

    @abstractmethod
    def disable_input(self):
        raise NotImplementedError


def show_confirmation_dialog(parent, title_text, explanation_text, accept_text, reject_text):
    dialog = QDialog(parent)
    dialog.setWindowTitle(title_text)
    dialog_layout = QVBoxLayout(dialog)

    explanation = QLabel(explanation_text)
    explanation.setFont(LABEL_FONT)
    dialog_layout.addWidget(explanation)

    buttons_widget = QWidget(dialog)
    buttons_layout = QHBoxLayout(buttons_widget)
    buttons_layout.setContentsMargins(0, 10, 0, 0)
    dialog_layout.addWidget(buttons_widget)
    yes_button = QPushButton(accept_text)
    yes_button.setFont(BUTTON_FONT)
    yes_button.clicked.connect(dialog.accept)
    buttons_layout.addWidget(yes_button)
    no_button = QPushButton(reject_text)
    no_button.setFont(BUTTON_FONT)
    no_button.clicked.connect(dialog.reject)
    buttons_layout.addWidget(no_button)

    no_button.setFocus()

    return dialog.exec()


class InformationPopup(QMainWindow):
    def __init__(self, title: str, content_file_to_display: str):
        super().__init__()

        self._text_widget = QTextEdit()

        with open(content_file_to_display, "r") as file:
            formatted_text = file.read()
            markdown_result = markdown.markdown(formatted_text)

        self._text_widget.setHtml(markdown_result)

        self.setCentralWidget(self._text_widget)

        self.setWindowTitle(title)
        self.resize(1000, 700)


class InfoDialog(QDialog):
    def __init__(self):
        super().__init__()

        self.dialog_shown: bool = False

        self.info_list = None
        self.image_list = None
        self.current_index = 0

        # Set up the dialog layout
        self.layout = QVBoxLayout()

        # Set a fixed width for the dialog
        self.setFixedWidth(400)  # Set the fixed width you prefer

        # Label to display the information text
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)  # Enable word wrap for the label
        self.layout.addWidget(self.info_label)

        # Widget to display the PNG image
        self.image_widget = QLabel()
        self.layout.addWidget(self.image_widget)

        # Buttons for navigation (Previous, Next, Skip)
        self.button_layout = QHBoxLayout()

        self.prev_button = QPushButton("Previous")
        self.prev_button.clicked.connect(self.show_previous)
        self.button_layout.addWidget(self.prev_button)

        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(self.show_next)
        self.button_layout.addWidget(self.next_button)

        self.skip_button = QPushButton("Skip")
        self.skip_button.clicked.connect(self.skip)
        self.button_layout.addWidget(self.skip_button)

        # Add button layout to the main layout
        self.layout.addLayout(self.button_layout)

        # Set the layout for the dialog
        self.setLayout(self.layout)

    # Setter method to set the info_list
    def set_info_list(self, info_list):
        self.info_list = info_list
        self.update_info()

    # Setter method to set the image_list
    def set_image_list(self, image_list):
        self.image_list = image_list
        self.update_image()

    # Method to update the displayed information
    def update_info(self):
        if self.info_list is not None:
            self.info_label.setText(self.info_list[self.current_index])
            self.update_image()
        self.update_buttons()

    # Method to update the displayed PNG image
    def update_image(self):
        if self.image_list is not None:
            image_path = self.image_list[self.current_index]
            if image_path and image_path.endswith(".png"):
                pixmap = QPixmap(image_path)
                self.image_widget.setPixmap(pixmap)
                self.image_widget.setVisible(True)
            else:
                self.image_widget.clear()
                self.image_widget.setVisible(False)

    # Method to update the state of the buttons
    def update_buttons(self):
        if self.info_list is not None:
            self.prev_button.setEnabled(self.current_index > 0)
            self.next_button.setEnabled(self.current_index < len(self.info_list) - 1)

    # Method to show the previous piece of information
    def show_previous(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.update_info()

    # Method to show the next piece of information
    def show_next(self):
        if self.current_index < len(self.info_list) - 1:
            self.current_index += 1
            self.update_info()

    # Method to skip and close the dialog
    def skip(self):
        self.accept()

    # Override exec to prevent multiple executions
    def exec(self):
        if not self.dialog_shown:
            super().exec()
            self.dialog_shown = True
