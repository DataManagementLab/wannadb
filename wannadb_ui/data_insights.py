"""
Module providing logic to realize Data Insights section visible in the document overview screen.
"""

import abc
import random
from typing import Generic, TypeVar, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout, QSpacerItem, QSizePolicy, QPushButton

from wannadb.models import BestMatchUpdate, ThresholdPositionUpdate, AccessibleColor
from wannadb_ui import visualizations
from wannadb_ui.common import ThresholdPosition, SUBHEADER_FONT, LABEL_FONT, \
    BUTTON_FONT
from wannadb_ui.study import track_button_click
from wannadb_ui.visualizations import EmbeddingVisualizerWindow

# Refers to the type of items displayed in a ChangesList
UPDATE_TYPE = TypeVar("UPDATE_TYPE")


class ChangesList(QWidget, Generic[UPDATE_TYPE]):
    """
    This class realizes a QWidget representing a list of updates.
    These updates refer to changes induced by the latest user feedback.

    Methods
    -------
        update_list(self, updates: List[UPDATE_TYPE]):
            Updates the list with the given list of items.
    """

    def __init__(self, info_label_text, tooltip_text):
        """
        Initializes an empty UI ChangesList with the given name and tooltip.

        Parameters
        ----------
        info_label_text : str
            Name of this list displayed next to the list itself.
        tooltip_text: QColor
            Text further explaining the list's intention displayed if hovering over list's name
        """

        super(ChangesList, self).__init__()

        # Setup layout
        self._layout: QHBoxLayout = QHBoxLayout(self)
        self._layout.setSpacing(0)
        self._layout.setContentsMargins(0, 0, 0, 0)

        # Init and add name label and tooltip
        self._info_label: QLabel = QLabel(info_label_text)
        self._info_label.setContentsMargins(0, 0, 8, 0)
        self._list_labels: List[QWidget] = list()
        self._layout.addWidget(self._info_label)
        self._info_label.setToolTip(tooltip_text)

    def update_list(self, updates: List[UPDATE_TYPE]):
        """
        Updates the list by the given list of items.

        First it removes all items from the current list and then adds the new items represented by the given list.
        In order to keep the UI clear, we only add the seven randomly sampled items of the given list to the UI list.
        The existence of further - not displayed - items are indicated by a label displaying "... and
        [NUMBER_OF_MISSING_ITEMS] more.".

        Parameters
        ----------
        """

        self._reset_list()

        if len(updates) == 0:
            # We don't want to have a list containing nothing but at least some symbol indicating that the list is empty
            no_changes_label = QLabel("-")
            no_changes_label.setContentsMargins(0, 0, 0, 0)
            self._layout.addWidget(no_changes_label)
            self._list_labels.append(no_changes_label)
            return

        # Select the 7 items to be displayed and add them to the UI
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
        # Computes the label text and tooltip corresponding to an update depending on the actual type of the update
        pass

    def _reset_list(self):
        # Removes all items from the UI list
        for list_label in self._list_labels:
            self._layout.removeWidget(list_label)

        self._list_labels = []


class ChangedBestMatchDocumentsList(ChangesList[BestMatchUpdate]):
    """
    Realizes a ChangesList displaying changed best matches after each user feedback which can be found within the
    Data Insights section.

    Methods
    ------
    update_list(self, updates: List[UPDATE_TYPE]):
        see `update_list` of `ChangesList`
    """

    def __init__(self, addressed_change: ThresholdPosition):
        """
        Determines its tooltip text and name and initializes itself by calling super constructor.
        """

        self._addressed_change = addressed_change
        tooltip_text = ("The distance associated with each nugget is recomputed after every feedback round.\n"
                        "Therefore the best guess of an document (nugget with lowest distance) might change "
                        "after a feedback round. Such best guesses are listed here.")

        super(ChangedBestMatchDocumentsList, self).__init__("Changed best guesses:", tooltip_text)

    def _create_label_and_tooltip_text(self, update: BestMatchUpdate) -> Tuple[str, str]:
        # Computes the text and tooltip which should represent the given item in the UI list.
        label_text = f"{update.new_best_match} {'(' + str(update.count) + ')' if update.count > 1 else ''}"
        tooltip_text = (f"Previous best match was: {update.old_best_match}\n"
                        f"Changes to token \"{update.new_best_match}\": {update.count}")

        return label_text, tooltip_text


class ChangedThresholdPositionList(ChangesList[ThresholdPositionUpdate]):
    """
    Realizes an abstract ChangesList displaying nuggets whose threshold position changed (either above or below) due to
    the latest user feedback which can be found in the Data Insights section.
    """

    def __init__(self, info_label_text: str, tooltip_text: str, addressed_change: ThresholdPosition):
        """
        Initializes itself by calling super constructor.

        Parameters:
        -----------
         info_label_text : str
            Name of this list displayed next to the list itself.
        tooltip_text: QColor
            Text further explaining the list's intention displayed if hovering over list's name
        addressed_change
            Determines about which threshold position updates this list cares, either from above to below or below to
            above.
            The given position refers to the end position of the relevant updates (E.g. If it's 'below', then this list
            only cares about 'above' -> 'below' updates).
        """

        self._addressed_change = addressed_change

        super(ChangedThresholdPositionList, self).__init__(info_label_text, tooltip_text)

    def update_list(self, threshold_updates: List[ThresholdPositionUpdate]):
        """
        Extracts the relevant updates out of the given list matching
        """
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

    def _extract_relevant_updates(self, threshold_updates: List[ThresholdPositionUpdate]) -> List[ThresholdPositionUpdate]:
        return list(filter(lambda update: (update.old_position != update.new_position and
                                           update.new_position == self._addressed_change),
                    threshold_updates))


class ChangedThresholdPositionToAboveList(ChangedThresholdPositionList):
    """
    Realizes a concrete `ChangedThresholdPositionList` displaying threshold updates where the position changed from
    below to above.
    """

    def __init__(self):
        """
        Initializes itself by determining tooltip, name and calling super constructor
        """

        tooltip_text = ("The distance associated with each nugget as well as the threshold is recomputed after every "
                        "feedback round.\n"
                        "Therefore the best guess of an document might not be below the threshold anymore. Such best "
                        "guesses are listed here.")
        super(ChangedThresholdPositionToAboveList, self).__init__("Moved above threshold:",
                                                                  tooltip_text,
                                                                  ThresholdPosition.ABOVE)


class ChangedThresholdPositionToBelowList(ChangedThresholdPositionList):
    """
    Realizes a concrete `ChangedThresholdPositionList` displaying threshold updates where the position changed from
    above to below.
    """

    def __init__(self):
        """
        Initializes itself by determining tooltip, name and calling super constructor
        """

        tooltip_text = ("The distance associated with each nugget as well as the threshold is recomputed after every "
                        "feedback round.\n"
                        "Therefore the best guess of an document might not be above the threshold anymore. Such best "
                        "guesses are listed here.")
        super(ChangedThresholdPositionToBelowList, self).__init__("Moved below threshold:",
                                                                  tooltip_text,
                                                                  ThresholdPosition.BELOW)


class DataInsightsArea:
    """
    Abstract superclass responsible for the common logic required for both, the simple and the extended version of the
    Data Insights section.
    It only handles the 3D-Grid which is present in both Data Insight section types.
    """

    def __init__(self):
        """
        Initializes the Data Insight section by initializing the 3D Grid.
        """

        # Init 3D-Grid
        self.suggestion_visualizer = EmbeddingVisualizerWindow([
            (AccessibleColor(visualizations.WHITE, visualizations.WHITE), 'Below threshold'),
            (AccessibleColor(visualizations.RED, visualizations.ACC_RED), 'Above threshold'),
            (AccessibleColor(visualizations.GREEN, visualizations.ACC_GREEN), 'Confirmed match')
        ])

        # Init and setup button responsible for opening the 3D Grid
        self.suggestion_visualizer_button = QPushButton("Show Suggestions In 3D-Grid")
        self.suggestion_visualizer_button.setContentsMargins(0, 0, 0, 0)
        self.suggestion_visualizer_button.setFont(BUTTON_FONT)
        self.suggestion_visualizer_button.setMaximumWidth(240)
        self.suggestion_visualizer_button.clicked.connect(self._show_suggestion_visualizer)

    @track_button_click("Show Suggestions In 3D-Grid")
    def _show_suggestion_visualizer(self):
        self.suggestion_visualizer.setVisible(True)

    def _enable_accessible_color_palette(self):
        self.accessible_color_palette = True
        self.suggestion_visualizer.enable_accessible_color_palette_()
    
    def _disable_accessible_color_palette(self):
        self.accessible_color_palette = False
        self.suggestion_visualizer.disable_accessible_color_palette_()


class SimpleDataInsightsArea(QWidget, DataInsightsArea):
    def __init__(self):
        QWidget.__init__(self)
        DataInsightsArea.__init__(self)

        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        self.layout.addWidget(self.suggestion_visualizer_button, 0, Qt.AlignmentFlag.AlignRight)

        self.setVisible(False)

    def enable_accessible_color_palette(self):
        self.accessible_color_palette = True
        self._enable_accessible_color_palette()
    
    def disable_accessible_color_palette(self):
        self.accessible_color_palette = False
        self._disable_accessible_color_palette()


class ExtendedDataInsightsArea(QWidget, DataInsightsArea):
    """
    Class realizing the extended Data Insights section displayed in the document overview screen and providing
    information about the effects of the user's latest feedback.

    It contains a label indicating the current threshold, lists providing nugget related changes due to the user's last
    feedback and 3D-Grid displaying the embeddings of all best guesses of all documetns.
    """

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
        self.accessible_color_palette = False
        self.changes_best_matches_list = ChangedBestMatchDocumentsList()

        self.changes_list3_hbox.addWidget(self.changes_best_matches_list)
        self.changes_list3_hbox.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.changes_list3_hbox.addWidget(self.suggestion_visualizer_button)

        self.layout.addLayout(self.changes_list1_hbox)
        self.layout.addLayout(self.changes_list2_hbox)
        self.layout.addLayout(self.changes_list3_hbox)

        self.setVisible(False)

    def enable_accessible_color_palette(self):
        self.accessible_color_palette = True
        self._enable_accessible_color_palette()
    
    def disable_accessible_color_palette(self):
        self.accessible_color_palette = False
        self._disable_accessible_color_palette()
    

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
