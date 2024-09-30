"""
Module providing logic to realize Data Insights section visible in the document overview screen.
"""

import abc
import random
from typing import Generic, TypeVar, List, Tuple

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel, QVBoxLayout, QSpacerItem, QSizePolicy, QPushButton

from wannadb.change_captor import BestMatchUpdate, ThresholdPositionUpdate
from wannadb.utils import AccessibleColor
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
        updates: List[UPDATE_TYPE]
            Items which should be added to the list.
        """

        # Remove existing items from list
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
    Realizes a `ChangesList` displaying changed best matches after each user feedback which can be found within the
    Data Insights section by inheriting from `ChangesList`.
    """

    def __init__(self):
        """
        Determines its tooltip text and name and initializes itself by calling super constructor.
        """

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
    the latest user feedback which can be found in the Data Insights section by inheriting from `ChangesList`.

    Methods
    -------
    update_list(updates: List[ThresholdPositionUpdate])
        Extracts the relevant updates out of the given list matching and updates the list with the extracted, relevant
        updates.
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
            Determines the change type addressed by this list, either from above to below or below to above.
            The given position refers to the end position of the relevant updates (E.g. If it's 'below', then this list
            only cares about 'above' -> 'below' updates).
        """

        self._addressed_change = addressed_change

        super(ChangedThresholdPositionList, self).__init__(info_label_text, tooltip_text)

    def update_list(self, threshold_updates: List[ThresholdPositionUpdate]):
        """
        Extracts the relevant updates out of the given list matching and updates the list with the extracted, relevant
        updates.

        The given list contains all updates covering changes from above to below as well as below to above the
        threshold while this list should only display one of these type of changes.
        Therefore, the mentioned extraction is required.

        Parameters
        ----------
        threshold_updates: List[ThresholdPositionUpdate]
            List of items in which the items to be added can be found. To extract the items to be added from the whole
            list, filter it according to the change type addressed by the list.
        """

        # Extract relevant updates
        relevant_updates = self._extract_relevant_updates(threshold_updates)

        # Add extracted updates to list
        super().update_list(relevant_updates)

    def _create_label_and_tooltip_text(self, update: ThresholdPositionUpdate) -> Tuple[str, str]:
        # Computes the label representing one change in the list and the corresponding tooltip

        moving_direction = update.new_position.name.lower()

        label_text = f"{update.nugget_text} {'(' + str(update.count) + ')' if update.count > 1 else ''}"
        distance_change_text = f"Old distance: {round(update.old_distance, 4)} -> New distance: {round(update.new_distance, 4)}\n" if update.old_distance \
            else f"Initial distance: {round(update.new_distance, 4)}\n"

        tooltip_text = (f"Due to your last feedback {update.nugget_text} moved {moving_direction} the threshold.\n"
                        f"{distance_change_text}" if not update.count > 1 else ""  # If update covers multiple nuggets, don't show distance text as the tooltip refers to multiple nuggets in this case
                        f"This happened for {update.count - 1} similar nuggets as well.")

        return label_text, tooltip_text

    def _extract_relevant_updates(self, threshold_updates: List[ThresholdPositionUpdate]) -> List[ThresholdPositionUpdate]:
        # Extracts the updates relevant to this list from a list containing all updates by filtering according to the
        # value of `_addressed_change`.

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
    Data Insights area.
    It only handles the 3D-Grid as it's the only component present in both Data Insight area types.

    Methods
    -------
    enable_accessible_color_palette()
        Enables the accessible color palette in the grid.
    disable_accessible_color_palette()
        Disables the accessible color palette in the grid.
    """

    def __init__(self):
        """
        Initializes the Data Insight section by initializing the 3D Grid and setting up the corresponding buttons
        responsible for opening the grid.
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

    def enable_accessible_color_palette(self):
        """
        Enables the accessible color palette in the grid.

        For further details, check the related method in `EmbeddingVisualizer`.
        """

        self.suggestion_visualizer.enable_accessible_color_palette()
    
    def disable_accessible_color_palette(self):
        """
        Disables the accessible color palette in the grid.

        For further details, check the related method in `EmbeddingVisualizer`.
        """

        self.suggestion_visualizer.disable_accessible_color_palette()

    @track_button_click("Show Suggestions In 3D-Grid")
    def _show_suggestion_visualizer(self):
        # Opens the 3D-Grid and tracks the click on the corresponding button

        self.suggestion_visualizer.setVisible(True)


class SimpleDataInsightsArea(QWidget, DataInsightsArea):
    """
    Class realizing the simple version of the Data Insights Area which only contains the 3D-Grid with the best guesses
    of all best guesses.

    It can be found in the document overview screen if only Level 1 visualization are enabled via the menu.

    Inherits from `QWidget` and `DataInsightsArea`.
    """

    def __init__(self):

        # Call super constructors
        QWidget.__init__(self)
        DataInsightsArea.__init__(self)

        # Set up layout
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)

        # Add button to widget
        self.layout.addWidget(self.suggestion_visualizer_button, 0, Qt.AlignmentFlag.AlignRight)

        # Make itself invisible initially
        self.setVisible(False)


class ExtendedDataInsightsArea(QWidget, DataInsightsArea):
    """
    Class realizing the extended Data Insights section providing
    information about the effects of the user's latest feedback as well as a 3D grid displaying all best guesses of all
    documents.

    It contains a label indicating the current threshold, lists providing nugget related changes due to the user's last
    feedback and 3D-Grid displaying the embeddings of all best guesses of all documents.
    The lists providing information about nugget related changes cover two lists displaying nugget whose position
    relative to the threshold changed. One list for all "above -> below" changes and one list for all "below -> above"
    changes. The lists are realized by utilizing instances of `ChangedThresholdPositionList`.
    Furthermore, there's a list displaying all nuggets who newly became the best guess due to the user's latest
    feedback.

    It can be found in the document overview screen if Level 2 visualization are enabled via the menu.

    Methods
    -------
    update_threshold_value_label(new_threshold_value, threshold_value_change)
        Updates the label indicating the current threshold with the given, new value and adds a label indicating the
        change of the threshold by considering the given value change.
    update_threshold_position_lists(threshold_position_updates: List[ThresholdPositionUpdate])
        Updates the lists displaying nuggets whose position relative to the threshold changed due to the user's latest
        feedback by the given list of changes.
    update_best_match_list(new_best_matches: List[BestMatchUpdate])
        Updates the list displaying changed best guesses by the given list of changes.
    hide()
        Hides itself as well as the possibly opened 3D-Grid.
    """

    def __init__(self):
        """
        Initializes an instance of this class by calling the related super constructors and setting up the required UI
        components.
        Setting up the required UI components covers the title displayed above the area, the label indicating the
        current threshold and the lists showing changes due to the user's latest feedback.
        """

        # Call super constructors
        QWidget.__init__(self)
        DataInsightsArea.__init__(self)

        # Set up layout
        self.layout = QVBoxLayout(self)
        self.layout.setSpacing(0)
        self.layout.setContentsMargins(0, 0, 0, 0)

        # Set up title
        self.title_label = QLabel("Data Insights")
        self.title_label.setFont(SUBHEADER_FONT)
        self.title_label.setContentsMargins(0, 5, 0, 5)
        self.layout.addWidget(self.title_label)

        # Set up label indicating the current threshold and a possible change of the threshold's value
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

        # Set up list displaying nuggets whose position relative to the threshold changed from above to below
        self.changes_list1_hbox = QHBoxLayout()
        self.changes_list1_hbox.setContentsMargins(0, 0, 0, 0)
        self.changes_list1_hbox.setSpacing(0)
        self.threshold_position_changes_below_list = ChangedThresholdPositionToBelowList()
        self.changes_list1_hbox.addWidget(self.threshold_position_changes_below_list)
        self.changes_list1_hbox.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # Set up list displaying nuggets whose position relative to the threshold changed from below to above
        self.changes_list2_hbox = QHBoxLayout()
        self.changes_list2_hbox.setContentsMargins(0, 0, 0, 0)
        self.changes_list2_hbox.setSpacing(0)
        self.threshold_position_changes_above_list = ChangedThresholdPositionToAboveList()
        self.changes_list2_hbox.addWidget(self.threshold_position_changes_above_list)
        self.changes_list2_hbox.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))

        # Set up list displaying changed best guesses
        self.changes_list3_hbox = QHBoxLayout()
        self.changes_list3_hbox.setContentsMargins(0, 0, 0, 0)
        self.changes_list3_hbox.setSpacing(0)
        self.accessible_color_palette = False
        self.changes_best_matches_list = ChangedBestMatchDocumentsList()
        self.changes_list3_hbox.addWidget(self.changes_best_matches_list)
        self.changes_list3_hbox.addItem(QSpacerItem(40, 20, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum))
        self.changes_list3_hbox.addWidget(self.suggestion_visualizer_button)

        # Add lists to layout
        self.layout.addLayout(self.changes_list1_hbox)
        self.layout.addLayout(self.changes_list2_hbox)
        self.layout.addLayout(self.changes_list3_hbox)

        # Make invisible initially
        self.setVisible(False)

    def update_threshold_value_label(self, new_threshold_value: float, threshold_value_change: float):
        """
        Updates the label indicating the current threshold with the given, new value and adds a label indicating the
        change of the threshold by considering the given value change.

        The text of the label indicates the current threshold is set to the given new value.
        If the given value change is non-zero, a label indicating this value change is added next to the label
        displaying the actual threshold value.

        Parameters
        ----------
        new_threshold_value: float
            New threshold value used to update the label indicating the current threshold value.
        threshold_value_change: float
            Value that indicates how much the threshold has changed compared to the previous one. If non-zero, a label
            containing this change is added.
        """

        # Add label indicating the value change if necessary
        if round(threshold_value_change, 4) != 0:
            self.threshold_value_label.setStyleSheet("color: orange;")
            change_text = f'(+{round(threshold_value_change, 4)})' if threshold_value_change > 0 else f'{round(threshold_value_change, 4)})'
            self.threshold_change_label.setText(change_text)
        else:
            self.threshold_value_label.setStyleSheet("")
            self.threshold_change_label.setText("")

        # Update the label displaying the current threshold
        self.threshold_value_label.setText(f"{round(new_threshold_value, 4)} ")
        self.threshold_label.setVisible(True)

    def update_threshold_position_lists(self, threshold_position_updates: List[ThresholdPositionUpdate]):
        """
        Updates the lists displaying nuggets whose position relative to the threshold changed due to the user's latest
        feedback by the given list of changes.

        Each list will extract the relevant changes out of the given list and update itself according to extracted
        changes.

        Realized by calling `update_list(updates: List[ThresholdPositionUpdate])` method of
        `ChangedThresholdPositionList` for both instances of the lists displaying the threshold position updates.
        Further details can be found in the documentation of this method in the `ChangedThresholdPositionList` class.

        Parameters
        ----------
        threshold_position_updates: List[ThresholdPositionUpdate]
            List containing all nuggets whose position relative to the threshold changed due to the user's latest
            feedback.
            The list contains both types of changes 'above -> below' and 'below -> above'.
        """

        self.threshold_position_changes_below_list.update_list(threshold_position_updates)
        self.threshold_position_changes_above_list.update_list(threshold_position_updates)

    def update_best_match_list(self, new_best_matches: List[BestMatchUpdate]):
        """
        Updates the list displaying changed best guesses by the given list of changes.

        Realized by calling `update_list(updates: List[BestMatchUpdate])` method of `ChangedBestMatchList` for the
        instance representing the list.
        Further details can be found in the documentation of this method in the `ChangedBestMatchList` class.

        Parameters
        ----------
        new_best_matches: List[BestMatchUpdate]
            List containing changed best guesses by the given list of changes. The `ChangedBestMatchList` instance will
            update itself by this list.
        """

        self.changes_best_matches_list.update_list(new_best_matches)

    def hide(self):
        """
        Hides itself as well as the possibly opened 3D-Grid.
        """

        super().hide()
        self.suggestion_visualizer.hide()
