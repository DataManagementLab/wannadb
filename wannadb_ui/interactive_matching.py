import logging

from typing import List

import numpy as np
from PyQt6 import QtGui
from PyQt6.QtCore import Qt, QEvent
from PyQt6.QtGui import QIcon, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget, QGridLayout, QSizePolicy

from wannadb.data.signals import CachedContextSentenceSignal, CachedDistanceSignal, \
    PCADimensionReducedLabelEmbeddingSignal, PCADimensionReducedTextEmbeddingSignal, \
    TSNEDimensionReducedLabelEmbeddingSignal
from wannadb_ui.common import BUTTON_FONT, CODE_FONT, CODE_FONT_BOLD, LABEL_FONT, MainWindowContent, \
    CustomScrollableList, CustomScrollableListItem, WHITE, LIGHT_YELLOW, YELLOW, NewlyAddedNuggetContext, \
    VisualizationProvidingItem, AvailableVisualizationsLevel, VisualizationProvidingCustomScrollableList
from wannadb_ui.data_insights import DataInsightsArea, SimpleDataInsightsArea, ExtendedDataInsightsArea
from wannadb_ui.visualizations import EmbeddingVisualizerWidget, BarChartVisualizerWidget, ScatterPlotVisualizerWidget
from wannadb_ui.study import Tracker, track_button_click

logger = logging.getLogger(__name__)

ICON_HIGH_CONFIDENCE = QIcon("wannadb_ui/resources/confidence_high.svg")
ICON_LOW_CONFIDENCE = QIcon("wannadb_ui/resources/confidence_low.svg")


class InteractiveMatchingWidget(MainWindowContent):
    def __init__(self, main_window):
        super(InteractiveMatchingWidget, self).__init__(main_window, "Preparing Table Population")

        self.stop_button = QPushButton("Continue With Next Attribute")
        self.stop_button.setFont(BUTTON_FONT)
        self.stop_button.setIcon(QIcon("wannadb_ui/resources/run.svg"))
        self.stop_button.clicked.connect(self._stop_button_clicked)
        self.stop_button.setMaximumWidth(240)
        self.controls_widget_layout.addWidget(self.stop_button)

        self.nugget_list_widget = NuggetListWidget(self, main_window)
        self.document_widget = DocumentWidget(self, main_window)

        main_window.attach_visualization_level_observer(self.nugget_list_widget)

        self.show_nugget_list_widget()

    def enable_input(self):
        self.stop_button.setEnabled(True)
        self.nugget_list_widget.enable_input()
        self.document_widget.enable_input()

    def disable_input(self):
        self.stop_button.setDisabled(True)
        self.nugget_list_widget.disable_input()
        self.document_widget.disable_input()

    def handle_feedback_request(self, feedback_request):
        attribute = feedback_request['attribute']
        self.header.setText(f"Attribute: {attribute.name}")
        self.nugget_list_widget.update_nuggets(feedback_request)
        self.document_widget.update_attribute(attribute)
        self.enable_input()
        self.show_nugget_list_widget()

    def get_document_feedback(self, nugget, other_best_guesses):
        self.document_widget.update_document(nugget, other_best_guesses)
        self.show_document_widget()

    def show_nugget_list_widget(self):
        self.document_widget.hide()
        self.nugget_list_widget.show()
        self.layout.removeWidget(self.document_widget)
        self.layout.addWidget(self.nugget_list_widget)
        self.stop_button.show()

    def show_document_widget(self):
        self.nugget_list_widget.hide()
        self.document_widget.show()
        self.layout.removeWidget(self.nugget_list_widget)
        self.layout.addWidget(self.document_widget)
        self.stop_button.hide()

    def _stop_button_clicked(self):
        self.show_nugget_list_widget()
        self.main_window.give_feedback_task({"message": "stop-interactive-matching"})


class NuggetListWidget(QWidget, VisualizationProvidingItem):
    def __init__(self, interactive_matching_widget, main_window):
        super(NuggetListWidget, self).__init__(interactive_matching_widget)
        self.interactive_matching_widget = interactive_matching_widget

        self.visualization_level = main_window.visualizations_level

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)

        self.description = QLabel("Please wait while WannaDB prepares the interactive table population.")
        self.description.setFont(LABEL_FONT)
        self.layout.addWidget(self.description)

        self.simple_visualize_area = SimpleDataInsightsArea()
        self.extended_visualize_area = ExtendedDataInsightsArea()
        self.layout.addWidget(self.simple_visualize_area)
        self.layout.addWidget(self.extended_visualize_area)

        # nugget list
        self.num_nuggets_above_label = QLabel("")
        self.num_nuggets_above_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.num_nuggets_above_label.setFont(CODE_FONT_BOLD)
        # self.num_nuggets_above_label.setStyleSheet(f"color: {LIGHT_YELLOW}")

        self.num_nuggets_below_label = QLabel("")
        self.num_nuggets_below_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.num_nuggets_below_label.setFont(CODE_FONT_BOLD)
        # self.num_nuggets_below_label.setStyleSheet(f"color: {YELLOW}")

        self.nugget_list = VisualizationProvidingCustomScrollableList(self, NuggetListItemWidget,
                                                                      visualizations_level=main_window.visualizations_level,
                                                                      attach_visualization_level_observer=main_window.attach_visualization_level_observer,
                                                                      floating_widget=self.num_nuggets_below_label,
                                                                      above_widget=self.num_nuggets_above_label)
        self.layout.addWidget(self.nugget_list)

    def update_nuggets(self, feedback_request):
        feedback_nuggets = feedback_request["nuggets"]
        all_guessed_nugget_matches = feedback_request["all-guessed-nugget-matches"]
        attribute = feedback_request["attribute"]
        current_threshold = feedback_request["max-distance"]
        threshold_change = feedback_request["max-distance-change"]
        nugget_updates_context = feedback_request["nugget-updates-context"]

        self.description.setText(
            "Please confirm or edit the cell value guesses displayed below until you are satisfied with the guessed values, at which point you may continue with the next attribute."
            "\nWannaDB will use your feedback to continuously update its guesses. Note that the cells with low confidence (low confidence bar, light yellow highlights) will be left empty.")
        self.extended_visualize_area.update_threshold_value_label(current_threshold, threshold_change)
        self.extended_visualize_area.update_best_match_list(nugget_updates_context.best_match_updates)
        self.extended_visualize_area.update_threshold_position_lists(nugget_updates_context.threshold_position_updates)

        params = {
            "max_start_chars": max([nugget[CachedContextSentenceSignal]["start_char"] for nugget in feedback_nuggets]),
            "max_distance": current_threshold,
            "other_best_guesses": feedback_nuggets,
            "new-nuggets": nugget_updates_context.newly_added_nugget_contexts,
            "num-feedback": feedback_request["num-feedback"]
        }

        if self.visualization_level == AvailableVisualizationsLevel.LEVEL_1:
            self.simple_visualize_area.setVisible(True)
            self.extended_visualize_area.setVisible(False)
        elif self.visualization_level == AvailableVisualizationsLevel.LEVEL_2:
            self.extended_visualize_area.setVisible(True)
            self.simple_visualize_area.setVisible(False)

        self.nugget_list.update_item_list(feedback_nuggets, params)
        if len(feedback_nuggets) > 0:
            self.extended_visualize_area.suggestion_visualizer.update_and_display_params(attribute=attribute,
                                                                                         nuggets=all_guessed_nugget_matches,
                                                                                         currently_highlighted_nugget=None,
                                                                                         best_guess=None,
                                                                                         other_best_guesses=[])
            self.simple_visualize_area.suggestion_visualizer.update_and_display_params(attribute=attribute,
                                                                                       nuggets=all_guessed_nugget_matches,
                                                                                       currently_highlighted_nugget=None,
                                                                                       best_guess=None,
                                                                                       other_best_guesses=[])

        if feedback_request["num-nuggets-above"] > 0:
            self.num_nuggets_above_label.setText(
                f"... and {feedback_request['num-nuggets-above']} more cells that will be left empty ...")
        else:
            self.num_nuggets_above_label.setText("")
        if feedback_request["num-nuggets-below"] > 0:
            self.num_nuggets_below_label.setText(
                f"... and {feedback_request['num-nuggets-below']} more cells that will be populated ...")
        else:
            self.num_nuggets_below_label.setText("")

    def enable_input(self):
        self.nugget_list.enable_input()

    def disable_input(self):
        self.nugget_list.disable_input()

    def _adapt_to_visualizations_level(self, visualizations_level):
        self.visualization_level = visualizations_level

        if visualizations_level == AvailableVisualizationsLevel.LEVEL_1:
            self.simple_visualize_area.setVisible(True)
            self.extended_visualize_area.setVisible(False)
        elif visualizations_level == AvailableVisualizationsLevel.LEVEL_2:
            self.extended_visualize_area.setVisible(True)
            self.simple_visualize_area.setVisible(False)
        elif visualizations_level == AvailableVisualizationsLevel.DISABLED:
            self.extended_visualize_area.setVisible(False)
            self.simple_visualize_area.setVisible(False)


class NuggetListItemWidget(CustomScrollableListItem, VisualizationProvidingItem):
    def __init__(self, nugget_list_widget, visualizations_level):
        super(NuggetListItemWidget, self).__init__(nugget_list_widget)
        self.nugget_list_widget = nugget_list_widget
        self.nugget = None
        self.other_best_guesses = None
        self._default_stylesheet = "QWidget#nuggetListItemWidget { background-color: white}"
        self._tooltip_text = ""
        self._visualizations = visualizations_level == AvailableVisualizationsLevel.LEVEL_2

        self.setFixedHeight(45)
        self.setObjectName("nuggetListItemWidget")
        self.setStyleSheet(self._default_stylesheet)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(20, 0, 20, 0)
        self.layout.setSpacing(10)

        self.confidence_button = QPushButton()
        self.confidence_button.event = lambda e: self.handle_tooltip_event(self.confidence_button, e, "NuggetListItemWidget.confidence_button")
        self.confidence_button.setFlat(True)
        self.confidence_button.setIcon(ICON_LOW_CONFIDENCE)
        self.confidence_button.setToolTip("Confidence in this match.")
        self.layout.addWidget(self.confidence_button)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFrameStyle(0)
        self.text_edit.setFont(CODE_FONT)
        self.text_edit.setLineWrapMode(QTextEdit.LineWrapMode.FixedPixelWidth)
        self.text_edit.setLineWrapColumnOrWidth(10000)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setFixedHeight(27)
        self.text_edit.setText("")
        self.layout.addWidget(self.text_edit)

        self.match_button = QPushButton()
        self.match_button.event = lambda e: self.handle_tooltip_event(self.match_button, e, "NuggetListItemWidget.match_button")
        self.match_button.setIcon(QIcon("wannadb_ui/resources/correct.svg"))
        self.match_button.setToolTip("Confirm this value.")
        self.match_button.clicked.connect(self._match_button_clicked)
        self.layout.addWidget(self.match_button)

        self.fix_button = QPushButton()
        self.fix_button.event = lambda e: self.handle_tooltip_event(self.fix_button, e, "NuggetListItemWidget.fix_button")
        self.fix_button.setIcon(QIcon("wannadb_ui/resources/pencil.svg"))
        self.fix_button.setToolTip("Edit this value.")
        self.fix_button.clicked.connect(self._fix_button_clicked)
        self.layout.addWidget(self.fix_button)

        self.last_tooltip_text_passed = None

    def update_item(self, item, params=None):
        self.nugget = item

        max_start_chars = params["max_start_chars"]
        max_distance = params["max_distance"]
        self.other_best_guesses = [other_best_guess for other_best_guess in params["other_best_guesses"]
                                   if other_best_guess != self.nugget]

        sentence = self.nugget[CachedContextSentenceSignal]["text"]
        start_char = self.nugget[CachedContextSentenceSignal]["start_char"]
        end_char = self.nugget[CachedContextSentenceSignal]["end_char"]

        if max_distance < self.nugget[CachedDistanceSignal]:
            color = LIGHT_YELLOW
            self.confidence_button.setIcon(ICON_LOW_CONFIDENCE)

            self.confidence_button.setToolTip(
                f"Low confidence in this match {self._build_distance_text() if self._visualizations else ''}, "
                f"will not be included in result.")
        else:
            color = YELLOW
            self.confidence_button.setIcon(ICON_HIGH_CONFIDENCE)
            self.confidence_button.setToolTip(
                f"High confidence in this match {self._build_distance_text() if self._visualizations else ''}, "
                f"will be included in result.")

        new_nugget_contexts: List = params["new-nuggets"]

        if self.nugget in map(lambda context: context.nugget, new_nugget_contexts):
            self._handle_item_is_new(self._extract_matching_context(new_nugget_contexts))
        else:
            self._update_stylesheets(False)
            self._tooltip_text = ""
            self.setToolTip(self._tooltip_text)

        self.text_edit.setText("")
        formatted_text = (
            f"{'&#160;' * (max_start_chars - start_char)}{sentence[:start_char]}"
            f"<span style='background-color: {color}'><b>{sentence[start_char:end_char]}</b></span>"
            f"{sentence[end_char:]}{'&#160;' * 70}"
        )
        self.text_edit.textCursor().insertHtml(formatted_text)

        scroll_cursor = QTextCursor(self.text_edit.document())
        scroll_cursor.setPosition(max_start_chars + 70)
        self.text_edit.setTextCursor(scroll_cursor)
        self.text_edit.ensureCursorVisible()
        self.text_edit.setDisabled(True)

        # self.info_button.setText(f"{str(round(self.nugget[CachedDistanceSignal], 2)).ljust(4)}")

    @track_button_click(button_name="nugget_list_match_button")
    def _match_button_clicked(self):
        self.nugget_list_widget.interactive_matching_widget.main_window.give_feedback_task({
            "message": "is-match",
            "nugget": self.nugget,
            "not-a-match": None
        })

    def _fix_button_clicked(self):
        self.nugget_list_widget.interactive_matching_widget.get_document_feedback(self.nugget, self.other_best_guesses)

    # def _info_button_clicked(self):
    #     lines = []
    #     lines.append("Signal values:")
    #     lines.append("")
    #     for key, value in self.nugget.signals.items():
    #         lines.append(f"- {key}: '{str(value)[:40]}'")
    #
    #     lines.append("")
    #     lines.append("All nuggets in document:")
    #     lines.append("")
    #     nuggets = self.nugget.document.nuggets
    #     nuggets = list(sorted(nuggets, key=lambda x: x[CachedDistanceSignal]))
    #     for nugget in nuggets:
    #         lines.append(f"- '{nugget.text}' ({nugget[CachedDistanceSignal]})")
    #
    #     QMessageBox.information(self, "Nugget Information", "\n".join(lines))

    def enable_input(self):
        self.match_button.setEnabled(True)
        self.fix_button.setEnabled(True)

    def disable_input(self):
        self.match_button.setDisabled(True)
        self.fix_button.setDisabled(True)

    def _adapt_to_visualizations_level(self, visualizations_level):
        if visualizations_level == AvailableVisualizationsLevel.LEVEL_2:
            self._show_visualizations()
        else:
            self._hide_visualizations()

    def _show_visualizations(self):
        self._visualizations = True

        if self._tooltip_text != "":
            self.setToolTip(self._tooltip_text)
        self.confidence_button.setToolTip(
            f"Low confidence in this match {self._build_distance_text()}, will not be included in result.")
        self._update_stylesheets(item_is_new=self._tooltip_text != "")

    def _hide_visualizations(self):
        self._visualizations = False

        self.setToolTip("")
        self.confidence_button.setToolTip(
            f"Low confidence in this match, will not be included in result.")
        self._update_stylesheets(False)

    def _handle_item_is_new(self, newly_added_nugget_context):
        distance_change_text = (f"Old distance: {round(newly_added_nugget_context.old_distance, 4)} -> "
                                f"New distance: {round(newly_added_nugget_context.new_distance, 4)}") \
            if newly_added_nugget_context.old_distance is not None \
            else f"Initial distance: {round(newly_added_nugget_context.new_distance, 4)}"
        self._tooltip_text = (
            f'Reason for the item to be newly added:\n'
            f'{newly_added_nugget_context.added_reason.corresponding_tooltip_text}\n\n'
            f'{distance_change_text}')

        if not self._visualizations:
            return

        self.setToolTip(self._tooltip_text)
        self._update_stylesheets(True)

    def _extract_matching_context(self, contexts: List[NewlyAddedNuggetContext]):
        for context in contexts:
            if context.nugget == self.nugget:
                return context

        raise ValueError(f"Own nugget ({self.nugget}) not in given list: {contexts}")

    def _build_distance_text(self):
        return f"(Distance: {round(self.nugget[CachedDistanceSignal], 4)})" if self._visualizations else ""

    def _update_stylesheets(self, item_is_new):
        if item_is_new:
            self.setStyleSheet((f"QFrame {{ background-color: {'#e7ffe6'}; }}\n"
                                f"QToolTip {{ background-color: {WHITE}; }}"))
            self.text_edit.setStyleSheet(f"color: black; background-color: {'#e7ffe6'}")
        else:
            self.setStyleSheet(self._default_stylesheet)
            self.text_edit.setStyleSheet(f"color: black; background-color: {WHITE}")

    def event(self, e):
        return self.handle_tooltip_event(self, e, "NuggetListItemWidget")

    def handle_tooltip_event(self, widget, e, identifier_name):
        if e.type() == QEvent.Type.ToolTip:
            tooltip_text = widget.toolTip()  # Extract the tooltip text
            if self.last_tooltip_text_passed != tooltip_text:
                Tracker().track_tooltip_activation(identifier_name)
                self.last_tooltip_text_passed = tooltip_text
        return super(widget.__class__, widget).event(e)

class DocumentWidget(QWidget, VisualizationProvidingItem):
    def __init__(self, interactive_matching_widget, main_window):
        super(DocumentWidget, self).__init__(parent=interactive_matching_widget)
        self.interactive_matching_widget = interactive_matching_widget

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(10)
        self.setLayout(self.layout)

        self.document = None
        self.original_nugget = None
        self.current_nugget = None
        self.current_attribute = None
        self.current_other_best_guesses = None
        self.base_formatted_text = ""
        self.idx_mapper = {}
        self.nuggets_in_order = []
        self.nuggets_sorted_by_distance = []

        main_window.attach_visualization_level_observer(self)

        self.description = QLabel(
            "Please select the correct value by clicking on one of the highlighted snippets. You may also "
            "highlight a different span of text in case the required value is not highlighted already.")
        self.description.setFont(LABEL_FONT)
        self.layout.addWidget(self.description)

        self.text_edit = QTextEdit()
        self.layout.addWidget(self.text_edit)
        self.text_edit.setReadOnly(True)
        self.text_edit.setFrameStyle(0)
        self.text_edit.setFont(CODE_FONT)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.selectionChanged.connect(self._handle_selection_changed)
        self.text_edit.setText("")

        # last custom selection values
        self.custom_start = 0
        self.custom_end = 0

        # last values from the cursor to prevent unnecessary execution
        self.old_start = 0
        self.old_end = 0

        self.custom_selection_item_widget = CustomSelectionItemWidget(self)
        self.custom_selection_item_widget.hide()
        self.suggestion_list = VisualizationProvidingCustomScrollableList(self, SuggestionListItemWidget,
                                                                          main_window.visualizations_level,
                                                                          main_window.attach_visualization_level_observer,
                                                                          orientation="horizontal",
                                                                          above_widget=self.custom_selection_item_widget)

        self.suggestion_list.setFixedHeight(60)
        self.layout.addWidget(self.suggestion_list)

        self.upper_buttons_widget = QWidget()
        self.upper_buttons_widget_layout = QHBoxLayout(self.upper_buttons_widget)
        self.upper_buttons_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.upper_buttons_widget)
        self.cosine_barchart = BarChartVisualizerWidget()
        self.cosine_barchart.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.upper_buttons_widget_layout.addWidget(self.cosine_barchart)
        self.scatter_plot_widget = ScatterPlotVisualizerWidget()
        self.scatter_plot_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.upper_buttons_widget_layout.addWidget(self.scatter_plot_widget)

        self.visualizer = EmbeddingVisualizerWidget()
        self.visualizer.setFixedHeight(300)
        self.layout.addWidget(self.visualizer)

        self.buttons_widget = QWidget()
        self.buttons_widget_layout = QHBoxLayout(self.buttons_widget)
        self.buttons_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.layout.addWidget(self.buttons_widget)

        self.no_match_button = QPushButton("Value Not In Document")
        self.no_match_button.setFont(BUTTON_FONT)
        self.no_match_button.clicked.connect(self._no_match_button_clicked)
        self.buttons_widget_layout.addWidget(self.no_match_button)

        self.match_button = QPushButton("Confirm Value")
        self.match_button.setFont(BUTTON_FONT)
        self.match_button.clicked.connect(self._match_button_clicked)
        self.buttons_widget_layout.addWidget(self.match_button)

    @track_button_click(button_name="document_match_button")
    def _match_button_clicked(self):
        if self.current_nugget is None:
            logger.info("Confirm custom nugget!")
            self.interactive_matching_widget.main_window.give_feedback_task({
                "message": "custom-match",
                "document": self.document,
                "start": self.custom_start,
                "end": self.custom_end
            })
        else:
            logger.info("Confirm existing nugget!")
            self.interactive_matching_widget.main_window.give_feedback_task({
                "message": "is-match",
                "nugget": self.current_nugget,
                "not-a-match": None if self.current_nugget is self.original_nugget else self.original_nugget
            })

    @track_button_click(button_name="document_no_match_button")
    def _no_match_button_clicked(self):
        self.interactive_matching_widget.main_window.give_feedback_task({
            "message": "no-match-in-document",
            "nugget": self.original_nugget,
            "not-a-match": self.original_nugget
        })

    def _handle_selection_changed(self):
        cursor = self.text_edit.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()

        if start == self.old_start and end == self.old_end:
            # the values did not change, so skip any updates
            return

        self.old_start = start
        self.old_end = end

        if start == 0 and end == 0 or start == len(self.document.text) and end == len(self.document.text):
            # this happens due to updated text, so we ignore it (it may lead to infinite recursion)
            return

        if end == start:  # clicked somewhere on the document (maybe on a nugget) OR text has been updated

            # clicked on a nugget --> set as current nugget
            for nugget in self.document.nuggets:
                if nugget.start_char <= start and start <= nugget.end_char:
                    logger.info("Select current nugget!")
                    self.current_nugget = nugget
                    self._highlight_current_nugget()
                    self.custom_selection_item_widget.hide()
                    break

        elif end > start:  # selected a span from the document
            self.custom_start = start
            self.custom_end = end

            # nugget was selected before --> remove highlight for this nugget
            if self.current_nugget:
                logger.info("Unselect current nugget!")
                self.current_nugget = None
                self._highlight_current_nugget()

            # update custom selection widget with span
            sanitized_text = self.document.text[start: end]
            sanitized_text = sanitized_text.replace("\n", " ")
            self.custom_selection_item_widget.text_label.setText(sanitized_text)
            self.custom_selection_item_widget.show()
            self.suggestion_list.scroll_area.horizontalScrollBar().setValue(
                self.suggestion_list.scroll_area.horizontalScrollBar().minimum()
            )

    def _highlight_current_nugget(self):
        if self.current_nugget:
            mapped_start_char = self.idx_mapper[self.current_nugget.start_char]
            mapped_end_char = self.idx_mapper[self.current_nugget.end_char] if self.current_nugget.end_char < len(
                self.document.text) else len(self.base_formatted_text)

            formatted_text = (
                f"{self.base_formatted_text[:mapped_start_char]}"
                f"<span style='background-color: {YELLOW}'><b>"
                f"{self.base_formatted_text[mapped_start_char:mapped_end_char]}</span></b>"
                f"{self.base_formatted_text[mapped_end_char:]}"
            )
            self.text_edit.setText("")
            self.text_edit.textCursor().insertHtml(formatted_text)

            self.visualizer.highlight_selected_nugget(self.current_nugget)
        else:
            self.text_edit.setText("")
            self.text_edit.textCursor().insertHtml(self.base_formatted_text)

        self.suggestion_list.update_item_list(self.nuggets_sorted_by_distance, self.current_nugget)

    def update_document(self, nugget, other_best_guesses):
        self.document = nugget.document
        self.original_nugget = nugget
        self.current_nugget = nugget
        self.current_other_best_guesses = other_best_guesses
        self.nuggets_sorted_by_distance = list(sorted(self.document.nuggets, key=lambda x: x[CachedDistanceSignal]))
        self.nuggets_in_order = list(sorted(self.document.nuggets, key=lambda x: x.start_char))
        self.custom_selection_item_widget.hide()

        self.old_start = -1
        self.old_end = -1
        self.custom_start = -1
        self.custom_end = -1

        if len(self.nuggets_in_order) > 0:
            self.idx_mapper = {}
            self.base_formatted_text = ""

            next_unseen_nugget_idx = 0
            inside = False
            current_inside_nuggets = []

            # For every char in the original document
            for idx, char in enumerate(list(self.document.text)):
                if char == "\n":
                    char = "<br>"
                # Get all nuggets starting here (unseen and start char is not greater than current index)
                # and store them to make sure they are closed afterwards
                while next_unseen_nugget_idx < len(self.nuggets_in_order):
                    if self.nuggets_in_order[next_unseen_nugget_idx].start_char > idx:
                        break
                    current_inside_nuggets.append(self.nuggets_in_order[next_unseen_nugget_idx])
                    next_unseen_nugget_idx += 1

                # Are we outside?
                if len(current_inside_nuggets) == 0:
                    # Just write out the char and map index to len - 1
                    self.base_formatted_text += char
                    self.idx_mapper[idx] = len(self.base_formatted_text) - 1
                # Are we inside?
                else:
                    # Determine if there are any nuggets ending here and remove them from the list of active nuggets
                    for i in range(len(current_inside_nuggets) - 1, -1, -1):
                        n = current_inside_nuggets[i]
                        if n.end_char == idx:
                            del current_inside_nuggets[i]

                    # Did we switch from outside to inside?
                    if not inside:
                        inside = True
                        self.base_formatted_text += f"<span style='background-color: {LIGHT_YELLOW}'><b>"
                        self.base_formatted_text += char
                        self.idx_mapper[idx] = len(self.base_formatted_text) - 1
                    # Inside
                    else:
                        # But now the questions: really inside or at the end?
                        if len(current_inside_nuggets) == 0:
                            self.base_formatted_text += "</span></b>"
                            inside = False
                        self.base_formatted_text += char
                        self.idx_mapper[idx] = len(self.base_formatted_text) - 1

            self.visualizer.update_and_display_params(attribute=self.current_attribute,
                                                      nuggets=self.document.nuggets,
                                                      currently_highlighted_nugget=nugget,
                                                      best_guess=self.nuggets_sorted_by_distance[0],
                                                      other_best_guesses=other_best_guesses)
            self.cosine_barchart.update_data(self.nuggets_sorted_by_distance)
            self.scatter_plot_widget.update_data(self.nuggets_sorted_by_distance)

        else:
            self.idx_mapper = {}
            for idx in range(len(self.document.text)):
                self.idx_mapper[idx] = idx
            self.base_formatted_text = ""

        self._highlight_current_nugget()
        self._highlight_best_guess(
            self.nuggets_sorted_by_distance[0] if len(self.nuggets_sorted_by_distance) > 0 else None)

        scroll_cursor = QTextCursor(self.text_edit.document())
        scroll_cursor.setPosition(nugget.start_char)
        self.text_edit.setTextCursor(scroll_cursor)
        self.text_edit.ensureCursorVisible()

    def clear_scatter_plot_data(self):
        self.scatter_plot_widget.clear_data()

    def enable_input(self):
        self.match_button.setEnabled(True)
        self.no_match_button.setEnabled(True)
        self.suggestion_list.enable_input()

    def disable_input(self):
        self.match_button.setDisabled(True)
        self.no_match_button.setDisabled(True)
        self.suggestion_list.disable_input()

    def update_attribute(self, attribute):
        self.current_attribute = attribute

    def _show_visualizations(self):
        self.upper_buttons_widget.show()
        self.visualizer.show()

    def _hide_visualizations(self):
        self.upper_buttons_widget.hide()
        self.visualizer.hide()

    def _highlight_best_guess(self, best_guess):
        if best_guess is None:
            return

        self.visualizer.highlight_best_guess(best_guess)

    def _adapt_to_visualizations_level(self, visualizations_level):
        if (visualizations_level == AvailableVisualizationsLevel.LEVEL_2 or
                visualizations_level == AvailableVisualizationsLevel.LEVEL_1):
            self._show_visualizations()
        elif visualizations_level == AvailableVisualizationsLevel.DISABLED:
            self._hide_visualizations()


class SuggestionListItemWidget(CustomScrollableListItem, VisualizationProvidingItem):

    def __init__(self, suggestion_list_widget, visualizations_level):
        super(SuggestionListItemWidget, self).__init__(suggestion_list_widget)
        self.suggestion_list_widget = suggestion_list_widget
        self.nugget = None
        self.visualizations = visualizations_level == AvailableVisualizationsLevel.LEVEL_2

        self.setFixedHeight(45)
        self.setStyleSheet(f"background-color: {WHITE}")

        self.layout = QGridLayout(self)
        self.layout.setContentsMargins(10, 0, 10, 0)

        self.text_label = QLabel()
        self.text_label.setFont(CODE_FONT_BOLD)
        self.layout.addWidget(self.text_label, 0, 0)

        self.distance_label = QLabel()
        self.distance_label.setFont(CODE_FONT)
        self.layout.addWidget(self.distance_label), 0, 1
        if not self.visualizations:
            self.distance_label.hide()

    def mousePressEvent(self, a0: QtGui.QMouseEvent) -> None:
        self.suggestion_list_widget.interactive_matching_widget.document_widget.current_nugget = self.nugget
        self.suggestion_list_widget.interactive_matching_widget.document_widget._highlight_current_nugget()
        self.suggestion_list_widget.interactive_matching_widget.document_widget.custom_selection_item_widget.hide()

    def update_item(self, item, params=None):
        self.nugget = item
        sanitized_text = self.nugget.text.replace("\n", " ")
        distance = np.round(self.nugget[CachedDistanceSignal], 3)
        self.text_label.setText(sanitized_text)
        self.distance_label.setText(str(distance))

        if self.nugget == params:
            self.setStyleSheet(f"background-color: {YELLOW}")
            self.suggestion_list_widget.interactive_matching_widget.document_widget.suggestion_list.scroll_area.horizontalScrollBar().setValue(
                self.pos().x() - 400
            )
        else:
            self.setStyleSheet(f"background-color: {LIGHT_YELLOW}")

    def enable_input(self):
        pass

    def disable_input(self):
        pass

    def _adapt_to_visualizations_level(self, visualizations_level):
        if visualizations_level != AvailableVisualizationsLevel.LEVEL_2:
            self.distance_label.hide()
        else:
            self.distance_label.show()


class CustomSelectionItemWidget(QWidget):

    def __init__(self, suggestion_list_widget):
        super(CustomSelectionItemWidget, self).__init__()
        self.suggestion_list_widget = suggestion_list_widget
        self.setFixedHeight(30)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 10, 0)

        self.inner_widget = QWidget()
        self.inner_widget.setStyleSheet(f"background-color: {YELLOW}")
        self.inner_widget_layout = QHBoxLayout(self.inner_widget)
        self.inner_widget_layout.setContentsMargins(10, 0, 10, 0)
        self.layout.addWidget(self.inner_widget)

        self.text_label = QLabel()
        self.text_label.setFont(CODE_FONT_BOLD)
        self.inner_widget_layout.addWidget(self.text_label)

    def enable_input(self):
        pass

    def disable_input(self):
        pass
