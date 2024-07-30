import abc
from enum import Enum
from typing import Union

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame, QHBoxLayout, QDialog, QPushButton

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

    @abc.abstractmethod
    def enable_input(self):
        raise NotImplementedError

    @abc.abstractmethod
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
            self.item_widgets.append(self.item_type(self.parent))

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


class CustomScrollableListItem(QFrame):

    def __init__(self, parent):
        super(CustomScrollableListItem, self).__init__()
        self.parent = parent

    @abc.abstractmethod
    def update_item(self, item, params=None):
        raise NotImplementedError

    @abc.abstractmethod
    def enable_input(self):
        raise NotImplementedError

    @abc.abstractmethod
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


class AddedReason(Enum):
    MOST_UNCERTAIN = "The documents match belongs to the considered most uncertain matches."
    INTERESTING_ADDITIONAL_EXTRACTION = "The document recently got interesting additional extraction to the list."
    AT_THRESHOLD = "The distance of the guessed match is within the considered range around the threshold."

    def __init__(self, corresponding_tooltip_text: str):
        self._corresponding_tooltip_text = corresponding_tooltip_text

    @property
    def corresponding_tooltip_text(self):
        return self._corresponding_tooltip_text


class BestMatchUpdate:
    def __init__(self, old_best_match, new_best_match, count):
        self._old_best_match = old_best_match
        self._new_best_match = new_best_match
        self._count = count

    @property
    def old_best_match(self):
        return self._old_best_match

    @property
    def new_best_match(self):
        return self._new_best_match

    @property
    def count(self):
        return self._count


class NewlyAddedNuggetContext:
    def __init__(self, nugget: InformationNugget,
                 old_distance: Union[float, None],
                 new_distance: float,
                 added_reason: AddedReason):
        self._nugget = nugget
        self._old_distance = old_distance
        self._new_distance = new_distance
        self._added_reason = added_reason

    @property
    def nugget(self):
        return self._nugget

    @property
    def old_distance(self):
        return self._old_distance

    @property
    def new_distance(self):
        return self._new_distance

    @property
    def added_reason(self):
        return self._added_reason

