import abc
import random
from typing import Generic, TypeVar, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout, QSpacerItem, QSizePolicy, QPushButton

from wannadb_ui.common import BestMatchUpdate, ThresholdPositionUpdate, ThresholdPosition, SUBHEADER_FONT, LABEL_FONT, \
    BUTTON_FONT, VisualizationProvidingItem, AvailableVisualizationsLevel
from wannadb_ui.study import track_button_click
from wannadb_ui.visualizations import EmbeddingVisualizerWindow

UPDATE_TYPE = TypeVar("UPDATE_TYPE")


class ChangesList(QWidget, Generic[UPDATE_TYPE]):
    def __init__(self, info_label_text, tooltip_text):
        super(ChangesList, self).__init__()

        self._layout: QHBoxLayout = QHBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)

        self._add_info_label(info_label_text, tooltip_text)

    def update_list(self, updates: List[UPDATE_TYPE]):
        self._reset_list()

        if len(updates) == 0:
            no_changes_label = QLabel("-")
            no_changes_label.setContentsMargins(0, 0, 0, 0)
            self._layout.addWidget(no_changes_label)
            self._list_labels.append(no_changes_label)
            return

        updates_to_add = random.sample(updates, k=min(7, len(updates)))
        for update in updates_to_add:
            label_text, tooltip_text = self._create_label_and_tooltip_text(update)
            label = QLabel(label_text)
            label.setContentsMargins(0, 0, 8, 0)
            label.setToolTip(tooltip_text)
            self._layout.addWidget(label)
            self._list_labels.append(label)

        if len(updates) > 7:
            last_label = QLabel(f"... and {len(updates) - 7} more.")
            last_label.setContentsMargins(0, 0, 0, 0)
            self._layout.addWidget(last_label)
            self._list_labels.append(last_label)

    @abc.abstractmethod
    def _create_label_and_tooltip_text(self, update: UPDATE_TYPE) -> Tuple[str, str]:
        pass

    def _reset_list(self):
        for list_label in self._list_labels:
            self._layout.removeWidget(list_label)

        self._list_labels = []

    def _add_info_label(self, info_label_text: str, tooltip_text: str):
        self._info_label: QLabel = QLabel(info_label_text)
        self._info_label.setContentsMargins(0, 0, 8, 0)
        self._list_labels: List[QWidget] = list()
        self._layout.addWidget(self._info_label)

        self._info_label.setToolTip(tooltip_text)


class ChangedBestMatchDocumentsList(ChangesList[BestMatchUpdate]):
    def __init__(self):
        tooltip_text = ("The distance associated with each nugget is recomputed after every feedback round.\n"
                        "Therefore the best guess of an document (nugget with lowest distance) might change "
                        "after a feedback round. Such best guesses are listed here.")
        super(ChangedBestMatchDocumentsList, self).__init__("Changed best guesses:", tooltip_text)

    def _create_label_and_tooltip_text(self, update: BestMatchUpdate) -> Tuple[str, str]:
        label_text = f"{update.new_best_match} {'(' + str(update.count) + ')' if update.count > 1 else ''}"
        tooltip_text = (f"Previous best match was: {update.old_best_match}\n"
                        f"Changes to token \"{update.new_best_match}\": {update.count}")

        return label_text, tooltip_text


class ChangedThresholdPositionList(ChangesList[ThresholdPositionUpdate]):
    def __init__(self, info_label_text, tooltip_text):
        super(ChangedThresholdPositionList, self).__init__(info_label_text, tooltip_text)

    def update_list(self, threshold_updates: List[ThresholdPositionUpdate]):
        relevant_updates = self._extract_relevant_updates(threshold_updates)

        super().update_list(relevant_updates)

    def _create_label_and_tooltip_text(self, update: ThresholdPositionUpdate) -> Tuple[str, str]:
        moving_direction = update.new_position.name.lower()

        label_text = f"{update.best_guess} {'(' + str(update.count) + ')' if update.count > 1 else ''}"
        distance_change_text = f"Old distance: {round(update.old_distance, 4)} -> New distance: {round(update.new_distance, 4)}\n" if update.old_distance is not None \
            else f"Initial distance: {round(update.new_distance, 4)}\n"
        tooltip_text = (f"Due to your last feedback {update.best_guess} moved {moving_direction} the threshold.\n"
                        f"{distance_change_text}"
                        f"This happened for {update.count - 1} similar nuggets as well.")

        return label_text, tooltip_text

    @abc.abstractmethod
    def _extract_relevant_updates(self, threshold_updates: List[ThresholdPositionUpdate]) -> List[ThresholdPositionUpdate]:
        pass


class ChangedThresholdPositionToAboveList(ChangedThresholdPositionList):
    def __init__(self):
        tooltip_text = ("The distance associated with each nugget as well as the threshold is recomputed after every "
                        "feedback round.\n"
                        "Therefore the best guess of an document might not be below the threshold anymore. Such best "
                        "guesses are listed here.")
        super(ChangedThresholdPositionToAboveList, self).__init__("Moved above threshold:", tooltip_text)

    def _extract_relevant_updates(self, threshold_updates: List[ThresholdPositionUpdate]):
        return list(filter(lambda update: (update.old_position != update.new_position and
                                           update.new_position == ThresholdPosition.ABOVE),
                           threshold_updates))


class ChangedThresholdPositionToBelowList(ChangedThresholdPositionList):
    def __init__(self):
        tooltip_text = ("The distance associated with each nugget as well as the threshold is recomputed after every "
                        "feedback round.\n"
                        "Therefore the best guess of an document might not be above the threshold anymore. Such best "
                        "guesses are listed here.")
        super(ChangedThresholdPositionToBelowList, self).__init__("Moved below threshold:", tooltip_text)

    def _extract_relevant_updates(self, threshold_updates: List[ThresholdPositionUpdate]):
        return list(filter(lambda update: (update.old_position != update.new_position and
                                           update.new_position == ThresholdPosition.BELOW),
                           threshold_updates))


class DataInsightsArea:
    def __init__(self):
        self.suggestion_visualizer = EmbeddingVisualizerWindow()

        self.suggestion_visualizer_button = QPushButton("Show Suggestions In 3D-Grid")
        self.suggestion_visualizer_button.setContentsMargins(0, 0, 0, 0)
        self.suggestion_visualizer_button.setFont(BUTTON_FONT)
        self.suggestion_visualizer_button.setMaximumWidth(240)
        self.suggestion_visualizer_button.clicked.connect(self._show_suggestion_visualizer)

    @track_button_click("Show Suggestions In 3D-Grid")
    def _show_suggestion_visualizer(self):
        self.suggestion_visualizer.setVisible(True)


class SimpleDataInsightsArea(QWidget, DataInsightsArea):
    def __init__(self):
        QWidget.__init__(self)
        DataInsightsArea.__init__(self)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.layout.addWidget(self.suggestion_visualizer_button, 0, Qt.AlignmentFlag.AlignRight)

        self.setVisible(False)


class ExtendedDataInsightsArea(QWidget, DataInsightsArea):
    def __init__(self):
        QWidget.__init__(self)
        DataInsightsArea.__init__(self)

        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel("Data Insights")
        self.title_label.setFont(SUBHEADER_FONT)
        self.title_label.setContentsMargins(0, 5, 0, 5)
        self.layout.addWidget(self.title_label)

        self.threshold_label = QLabel()
        self.threshold_label.setFont(LABEL_FONT)
        self.threshold_label.setText("Current Threshold: ")
        self.threshold_value_label = QLabel()
        self.threshold_value_label.setFont(LABEL_FONT)
        self.threshold_change_label = QLabel()
        self.threshold_change_label.setFont(LABEL_FONT)
        self.threshold_hbox = QHBoxLayout()
        self.threshold_hbox.setContentsMargins(0, 0, 0, 0)
        self.threshold_hbox.setSpacing(0)
        self.threshold_hbox.addWidget(self.threshold_label)
        self.threshold_hbox.addWidget(self.threshold_value_label)
        self.threshold_hbox.addWidget(self.threshold_change_label)
        self.threshold_hbox.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.layout.addLayout(self.threshold_hbox)

        self.changes_list1_hbox = QHBoxLayout()
        self.changes_list1_hbox.setContentsMargins(0, 0, 0, 0)
        self.changes_list1_hbox.setSpacing(0)
        self.threshold_position_changes_below_list = ChangedThresholdPositionToBelowList()
        self.changes_list1_hbox.addWidget(self.threshold_position_changes_below_list)
        self.changes_list1_hbox.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.changes_list2_hbox = QHBoxLayout()
        self.changes_list2_hbox.setContentsMargins(0, 0, 0, 0)
        self.changes_list2_hbox.setSpacing(0)
        self.threshold_position_changes_above_list = ChangedThresholdPositionToAboveList()
        self.changes_list2_hbox.addWidget(self.threshold_position_changes_above_list)
        self.changes_list2_hbox.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        self.changes_list3_hbox = QHBoxLayout()
        self.changes_list3_hbox.setContentsMargins(0, 0, 0, 0)
        self.changes_list3_hbox.setSpacing(0)

        self.changes_best_matches_list = ChangedBestMatchDocumentsList()

        self.changes_list3_hbox.addWidget(self.changes_best_matches_list)
        self.changes_list3_hbox.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.changes_list3_hbox.addWidget(self.suggestion_visualizer_button)

        self.layout.addLayout(self.changes_list1_hbox)
        self.layout.addLayout(self.changes_list2_hbox)
        self.layout.addLayout(self.changes_list3_hbox)

        self.setVisible(False)

    def update_threshold_value_label(self, new_threshold_value, threshold_value_change):
        if round(threshold_value_change, 4) != 0:
            self.threshold_value_label.setStyleSheet("color: yellow;")
            change_text = f'(+{round(threshold_value_change, 4)})' if threshold_value_change > 0 else f'{round(threshold_value_change, 4)})'
            self.threshold_change_label.setText(change_text)
        else:
            self.threshold_value_label.setStyleSheet("")
            self.threshold_change_label.setText("")

        self.threshold_value_label.setText(f"{round(new_threshold_value, 4)} ")
        self.threshold_label.setVisible(True)

    def update_best_match_list(self, new_best_matches: List[BestMatchUpdate]):
        self.changes_best_matches_list.update_list(new_best_matches)

    def update_threshold_position_lists(self, threshold_position_updates: List[ThresholdPositionUpdate]):
        self.threshold_position_changes_below_list.update_list(threshold_position_updates)
        self.threshold_position_changes_above_list.update_list(threshold_position_updates)

    def hide(self):
        super().hide()
        self.suggestion_visualizer.hide()
