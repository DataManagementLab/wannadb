"""
This class provides several classes related to visualization widgets.
    1. PointLegend
        Label serving as a legend for a dyed point.
    2. EmbeddingVisualizerLegend
        Widget serving as a legend for the EmbeddingVisualizer.
    3. EmbeddingVisualizer
       Provides logic for handling a grid displaying dimension reduced nuggets.
    4. EmbeddingVisualizerWindow
        Realizes an EmbeddingVisualizer in a separate window.
    5. EmbeddingVisualizerWidget
        Realizes an EmbeddingVisualizer in a widget.
    6. BarChartVisualizerWidget
        Widget realizing a bar chart displaying nuggets with their certainty with which they match an attribute.
"""

import logging
from typing import List, Dict, Tuple, Union

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QFont, QColor, QPixmap, QPainter
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QMainWindow, QHBoxLayout, QFrame, QScrollArea, \
    QApplication, QLabel
from matplotlib import pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from pyqtgraph import Color
from pyqtgraph.opengl import GLViewWidget, GLScatterPlotItem, GLTextItem

from wannadb.data.data import InformationNugget, Attribute
from wannadb.data.signals import PCADimensionReducedTextEmbeddingSignal, PCADimensionReducedLabelEmbeddingSignal, \
    CachedDistanceSignal, CurrentThresholdSignal
from wannadb.utils import AccessibleColor
from wannadb_ui.common import BUTTON_FONT_SMALL, InfoDialog
from wannadb_ui.study import Tracker, track_button_click

logger: logging.Logger = logging.getLogger(__name__)

RED = pg.mkColor('red')
ACC_RED = pg.mkColor(220, 38, 127)
BLUE = pg.mkColor('blue')
ACC_BLUE = pg.mkColor(100, 143, 255)
GREEN = pg.mkColor('green')
ACC_GREEN = pg.mkColor(255, 176, 0)
WHITE = pg.mkColor('white')
YELLOW = pg.mkColor('yellow')
ACC_YELLOW = pg.mkColor(254, 97, 0)
PURPLE = pg.mkColor('purple')
ACC_PURPLE = pg.mkColor(120, 94, 240)
EMBEDDING_ANNOTATION_FONT = QFont('Helvetica', 10)
DEFAULT_NUGGET_SIZE = 10
HIGHLIGHT_SIZE = 17

app = QApplication([])
screen = app.primaryScreen()
screen_geometry = screen.geometry()
WINDOW_WIDTH = int(screen_geometry.width() * 0.7)
WINDOW_HEIGHT = int(screen_geometry.height() * 0.7)


def _get_colors(distances, color_start='green', color_end='red'):
    cmap = LinearSegmentedColormap.from_list("CustomMap", [color_start, color_end])
    norm = plt.Normalize(min(distances), max(distances))
    colors = [cmap(norm(value)) for value in distances]
    return colors


def _build_nuggets_annotation_text(nugget) -> str:
    return f"{nugget.text}: {round(nugget[CachedDistanceSignal], 3)}"


def _create_sanitized_text(nugget):
    return nugget.text.replace("\n", " ")


class PointLegend(QLabel):
    """
    Class realizing a legend for a dyed point by displaying a dyed point next to the meaning of this point within a label.

    In the application, this class is employed to create a legend for the 3D-Grids.
    The 3D-Grid contains points with different colors. Each color is explained using a label created by this class.
    """
    def __init__(self, point_meaning: str, point_color: QColor):
        """
        Parameters
        ----------
        point_meaning : str
            the meaning of points with the given color
        point_color: QColor
            the color of the points whose meaning is explained by this label
        """

        super().__init__()

        # Set fixed sizes
        self._height = 30
        self._width = 300
        self._circle_diameter = 10

        # Init pixmap on which all contents will be painted
        self._pixmap = QPixmap(self._width, self._height)
        self._pixmap.fill(Qt.GlobalColor.transparent)

        # Init painter used to paint on pixmap
        self._painter = QPainter(self._pixmap)

        # Init point displayed on pixmap serving as a reference to which points the meaning refers to
        circle_center = QPoint(self._circle_diameter, round(self._height / 2))

        # Paint point and text on pixmap
        self._painter.setPen(Qt.PenStyle.NoPen)
        self._painter.setBrush(point_color)
        self._painter.drawEllipse(circle_center, self._circle_diameter, self._circle_diameter)
        self._painter.setFont(BUTTON_FONT_SMALL)
        self._painter.setPen(pg.mkColor('black'))
        text_height = self._painter.fontMetrics().height()
        self._painter.drawText(circle_center.x() + self._circle_diameter + 5,
                               circle_center.y() + round(text_height / 4),
                               f': {point_meaning}')

        self._painter.end()

        # Add pixmap to label represented by this instance
        self.setPixmap(self._pixmap)


class EmbeddingVisualizerLegend(QWidget):
    """
    Class realizing a legend for a 3D-Grid realized by the EmbeddingVisualizer class which explains the meaning of all
    point colors occurring within the grid.
    Utilizes instances of `PointLegend` to explain the meaning of a specific color.

    Methods
    -------
    reset():
        Removes all widgets - realized as instances of `PointLegend` - contained within this widget.
    update_colors_and_meanings(colors_with_meanings: List[Tuple[QColor, str]]):
        Fills this instance with an actual legend explaining the given colors with the given meanings.
    """

    def __init__(self):
        """
        Initializes an instance of this class by creating and setting up the corresponding layout.
        Initially the widget represented by this instance is empty and doesn't contain anything except an empty layout.
        """

        super().__init__()

        # Set up the layout
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        # Init the list of PointLegends contained by this instance
        self._point_legends = []

    def reset(self):
        """
        Removes all widgets - realized as instances of `PointLegend`.

        After calling this method, the widget represented by this instance is empty and doesn't contain anything except
        an empty layout.
        """

        for widget in self._point_legends:
            self.layout.removeWidget(widget)
        self._point_legends = []

    def update_colors_and_meanings(self, colors_with_meanings: List[Tuple[QColor, str]]):
        """
        Fills this instance with an actual legend explaining the given colors with the given meanings.

        First, this instance is cleared by calling the `reset()` method.
        Then an explanation for each of the given colors is created by creating `PointLegend` instances for each color
        with its associated meaning and added to the widget represented by this instance.
        """

        # Clear this widget
        self.reset()

        # Add new explanations
        for color, meaning in colors_with_meanings:
            point_legend = PointLegend(meaning, color)
            self.layout.addWidget(point_legend)
            self._point_legends.append(point_legend)


class EmbeddingVisualizer:
    """
    Class providing the required logic to handle a 3D-Grid displaying dimension-reduced embedding vectors.

    Methods
    -------
    enable_accessible_color_palette_():
        Replaces the colors of points displayed within the grid by accessible colors allowing people with color
        blindness to better differentiate the colors.
    disable_accessible_color_palette_():
        Replaces the colors of points displayed within the grid by the originally used colors and therefore disables the
        usage of accessible colors.
    update_and_display_params(attribute: Attribute,
                              nuggets: List[InformationNugget],
                              currently_highlighted_nugget: Union[InformationNugget, None],
                              best_guess: Union[InformationNugget, None],
                              other_best_guesses: List[InformationNugget]):
        Removes all currently displayed nuggets and adds the given attribute as well as the nuggets to the grid.
    highlight_best_guess(best_guess: InformationNugget):
        Highlights the point representing the given nugget by increasing its size and dying it white.
    highlight_selected_nugget(newly_selected_nugget: InformationNugget):
        Highlights the point representing the given nugget by increasing its size and dying it blue.
    display_other_best_guesses(other_best_guesses: List[InformationNugget]):
        Adds the given nuggets - corresponding to the best guesses of other documents -  to the grid and highlight them
        by dying them yellow.
    remove_other_best_guesses(other_best_guesses: List[InformationNugget]):
        Removes the nuggets corresponding to the best guesses of other documents from the grid.
    reset():
        Removes all points and their corresponding annotation text from the grid.
    """

    def __init__(self,
                 legend: EmbeddingVisualizerLegend,
                 colors_with_meanings: List[Tuple[AccessibleColor, str]],
                 attribute: Attribute = None,
                 nuggets: List[InformationNugget] = None,
                 currently_highlighted_nugget: InformationNugget = None,
                 best_guess: InformationNugget = None,
                 other_best_guesses: List[InformationNugget] = None,
                 accessible_color_palette: bool = False):
        """
        Parameters:
        -----------
        legend: EmbeddingVisualizerLegend
            Instance of the legend displayed below the grid and explaining the meaning of the colors occurring in the
            grid.
        colors_with_meanings: List[Tuple[QColor, str]]
            List of colors occurring in the grid associated with their meaning used to fill the given legend.
        attribute: Attribute = None
            `Attribute` instance representing the attribute to which the nuggets displayed within the grid belong to as
            its embedding is displayed in the grid as well.
        nuggets: List[InformationNugget] = None
            Nuggets whose dimension-reduced embedding vectors should be displayed within the grid.
        currently_highlighted_nugget: InformationNugget = None
            Refers to the nugget which is currently selected and therefore should be highlighted. If none, nothing is
            highlighted.
        best_guess: InformationNugget = None
            Refers to the best guess of the document represented by this grid and therefore should be highlighted. If
            none, nothing is highlighted. Applicable only in case the grid belongs to the document view and not to the
            document overview screen.
        other_best_guesses: List[InformationNugget] = None
            Nuggets representing best guesses from other documents which should be displayed in this grid as well
            initially. Applicable only in case the grid belongs to the document view and not to the document overview
            screen.
        accessible_color_palette: bool
            Specifies whether the colors used by the points displayed in the grid are accessible - usable for people
            with color blindness - or not.
        """

        self._attribute: Attribute = attribute
        self._nuggets: List[InformationNugget] = nuggets
        self._currently_highlighted_nugget: InformationNugget = currently_highlighted_nugget
        self._best_guess: InformationNugget = best_guess
        self._other_best_guesses: List[InformationNugget] = other_best_guesses
        self._nugget_to_displayed_items: Dict[InformationNugget, Tuple[GLScatterPlotItem, GLTextItem]] = dict()
        self._gl_widget = GLViewWidget()
        self._accessible_color_palette = accessible_color_palette
        self._legend = legend
        self._colors_with_meanings = colors_with_meanings

        # Add the given colors with their meanings to the given legend
        self._update_legend()

    def enable_accessible_color_palette_(self):
        """
        Replaces the colors of points displayed within the grid by accessible colors allowing people with color
        blindness to better differentiate the colors.
        """

        self._accessible_color_palette = True
        self._update_legend()

    def disable_accessible_color_palette_(self):
        """
        Replaces the colors of points displayed within the grid by the originally used colors and therefore disables the
        usage of accessible colors.
        """

        self._accessible_color_palette = False
        self._update_legend()

    def update_and_display_params(self,
                                  attribute: Attribute,
                                  nuggets: List[InformationNugget],
                                  currently_highlighted_nugget: Union[InformationNugget, None],
                                  best_guess: Union[InformationNugget, None],
                                  other_best_guesses: List[InformationNugget]):
        """
        Removes all currently displayed nuggets and adds the given attribute as well as the nuggets to the grid.

        First, removes all currently displayed points.
        Then adds the dimension-reduced embedding vector of the given attribute and the given nuggets to the grid.
        Next, the given best guess and `currently_highlighted_nugget` and - if this grid belongs to the document
        overview - already confirmed matches are highlighted.

        Parameters:
        -----------
        attribute: Attribute
            `Attribute` instance representing the attribute to which the nuggets displayed within the grid as its
            embedding is displayed in the grid as well.
        nuggets: List[InformationNugget]
            Nuggets whose dimension-reduced embedding vectors should be displayed within the grid.
        currently_highlighted_nugget: InformationNugget
            Special nugget which should be highlighted. If none, nothing is highlighted.
        best_guess: InformationNugget
            Best guess of the document corresponding to the grid which is highlighted. If none, nothing is highlighted.
            Applicable only in case the grid belongs to the document view and not to the document overview screen.
        other_best_guesses: List[InformationNugget]
            Best guesses of other documents which should be displayed in the grid as well. Applicable only in case the
            grid belongs to the document view and not to the document overview screen.
        """

        self.reset()

        # Add attribute to grid
        if attribute is not None:
            self._display_attribute_embedding(attribute)
        else:
            logger.warning("Given attribute is null, can not display.")

        # Add nuggets to the grid
        if nuggets:
            self._nuggets = nuggets
            self._display_nugget_embeddings(nuggets)
        else:
            logger.warning("Given nugget list is null or empty, can not display.")

        # Highlight best guess if present
        if best_guess is not None:
            self.highlight_best_guess(best_guess)
        else:
            logger.info("Given best_guess is null, can not highlight.")

        # Highlight confirmed matches if possible
        self._highlight_confirmed_matches()

        # Highlight currently selected nugget if possible
        if currently_highlighted_nugget is not None:
            self.highlight_selected_nugget(currently_highlighted_nugget)
        else:
            logger.info("Given nugget to highlight is null, can not highlight.")

        self._other_best_guesses = other_best_guesses

    def highlight_best_guess(self, best_guess: InformationNugget):
        """
        Highlights the point representing the given nugget by increasing its size and dying it white.

        If the best guess is equal to the currently selected nugget, it's highlighted in blue.
        """

        # Update internal attribute
        self._best_guess = best_guess

        # Highlight in blue if equal to currently selected nugget
        if self._best_guess == self._currently_highlighted_nugget:
            self._highlight_nugget(self._best_guess, ACC_BLUE if self._accessible_color_palette else BLUE, 15)
            return

        # Highlight given nugget in white and increase size
        self._highlight_nugget(self._best_guess, WHITE, 15)

    def highlight_selected_nugget(self, newly_selected_nugget: InformationNugget):
        """
        Highlights the point representing the given nugget by increasing its size and dying it blue.

        If present, the previously selected nugget is reset to original color and size. Exact reset color and size
        depend on type of previously selected nugget (best guess, confirmed match, normal nugget)
        """

        # Determine highlight color and size as well as reset color and size. Highlight values are always blue and 15
        # while reset values depend on type of previously selected nugget (see above).
        (highlight_color, highlight_size), (reset_color, reset_size) = self._determine_update_values(
            previously_selected_nugget=self._currently_highlighted_nugget)

        # Reset currently highlighted nugget to determined color and size
        if self._currently_highlighted_nugget is not None:
            currently_highlighted_scatter, _ = self._nugget_to_displayed_items[self._currently_highlighted_nugget]
            currently_highlighted_scatter.setData(color=reset_color, size=reset_size)

        # Highlight newly selected nugget
        self._highlight_nugget(nugget_to_highlight=newly_selected_nugget,
                               new_color=highlight_color,
                               new_size=highlight_size)

        # Update internal variable
        self._currently_highlighted_nugget = newly_selected_nugget

    def display_other_best_guesses(self, other_best_guesses: List[InformationNugget]):
        """
        Adds the given nuggets - corresponding to the best guesses of other documents -  to the grid and highlight them
        by dying them yellow.
        """

        for other_best_guess in other_best_guesses:
            self._add_other_best_guess(other_best_guess)

    def remove_other_best_guesses(self, other_best_guesses: List[InformationNugget]):
        """
        Removes the nuggets corresponding to the best guesses of other documents from the grid.
        """

        self._remove_nuggets_from_widget(other_best_guesses)

    def reset(self):
        """
        Removes all points and their corresponding annotation text from the grid.
        """

        # Remove widgets
        for nugget, (scatter, annotation) in self._nugget_to_displayed_items.items():
            self._gl_widget.removeItem(scatter)
            self._gl_widget.removeItem(annotation)

        # Reset internal state variables
        self._nugget_to_displayed_items = {}
        self._currently_highlighted_nugget = None
        self._best_guess = None

    def _add_item_to_grid(self,
                          nugget_to_display_context: Tuple[Union[InformationNugget, Attribute], Color],
                          annotation_text: str,
                          size: int = DEFAULT_NUGGET_SIZE):
        # Determine position of point to display and its color
        item_to_display, color = nugget_to_display_context
        position = np.array([item_to_display[PCADimensionReducedTextEmbeddingSignal]]) if isinstance(item_to_display,
                                                                                                     InformationNugget) \
            else np.array([item_to_display[PCADimensionReducedLabelEmbeddingSignal]])

        # Create grid items representing the given nugget and annotation text at the computed position
        scatter = GLScatterPlotItem(pos=position, color=color, size=size, pxMode=True)
        annotation = GLTextItem(pos=[position[0][0], position[0][1], position[0][2]],
                                color=WHITE,
                                text=annotation_text,
                                font=EMBEDDING_ANNOTATION_FONT)

        # Add created items to grid
        self._gl_widget.addItem(scatter)
        self._gl_widget.addItem(annotation)

        # Add created items to internal variable to keep track about the added items
        if isinstance(item_to_display, InformationNugget):
            self._nugget_to_displayed_items[item_to_display] = (scatter, annotation)

    def _display_nugget_embeddings(self, nuggets):
        for nugget in nuggets:
            nugget_to_display_context = (nugget, self._determine_nuggets_color(nugget))

            self._add_item_to_grid(nugget_to_display_context=nugget_to_display_context,
                                   annotation_text=_build_nuggets_annotation_text(nugget))

    def _display_attribute_embedding(self, attribute):
        self._add_item_to_grid(nugget_to_display_context=(attribute, ACC_RED if self._accessible_color_palette else RED),
                               annotation_text=attribute.name)
        self._attribute = attribute

    def _remove_nuggets_from_widget(self, nuggets_to_remove):
        # Removes all items associated with the given nuggets from the grid
        for nugget in nuggets_to_remove:
            scatter, annotation = self._nugget_to_displayed_items.pop(nugget)

            self._gl_widget.removeItem(scatter)
            self._gl_widget.removeItem(annotation)

    def _highlight_confirmed_matches(self):
        # Only relevant if the grid belongs to the document overview view as it highlights the nuggets which are already
        # confirmed by the user in the feedback process.
        if self._attribute is None:
            logger.warning("Attribute has not been initialized yet, can not highlight confirmed matches.")
            return

        for confirmed_match in self._attribute.confirmed_matches:
            if confirmed_match in self._nugget_to_displayed_items:
                self._highlight_nugget(confirmed_match, ACC_GREEN if self._accessible_color_palette else GREEN,
                                       DEFAULT_NUGGET_SIZE)

    def _determine_update_values(self, previously_selected_nugget) -> ((int, Color), (int, Color)):
        # Computes the size and color of a newly selected nugget as well as the size and color of the nugget
        # which was selected previously

        # Highlight values are always same
        highlight_color = ACC_BLUE if self._accessible_color_palette else BLUE
        highlight_size = 15

        # Reset values depend on the type of the nugget whose size and color should be reset
        if previously_selected_nugget is None:
            reset_color = WHITE
            reset_size = DEFAULT_NUGGET_SIZE
        elif previously_selected_nugget in self._attribute.confirmed_matches:
            reset_color = ACC_GREEN if self._accessible_color_palette else GREEN
            reset_size = DEFAULT_NUGGET_SIZE
        elif previously_selected_nugget == self._best_guess:
            reset_color = WHITE
            reset_size = HIGHLIGHT_SIZE
        else:
            reset_color = self._determine_nuggets_color(previously_selected_nugget)
            reset_size = DEFAULT_NUGGET_SIZE

        return (highlight_color, highlight_size), (reset_color, reset_size)

    def _determine_nuggets_color(self, nugget: InformationNugget) -> Color:
        # Computes the nuggets color based on its type:
        # Purple -> Failure during computation
        # White -> Below threshold
        # Red -> Above Threshold

        if (self._attribute is None or
                CurrentThresholdSignal.identifier not in self._attribute.signals):
            logger.warning(f"Could not determine nuggets color from given attribute: {self._attribute}. "
                           f"Will return purple as color highlighting nuggets with this issue.")
            return ACC_PURPLE if self._accessible_color_palette else PURPLE

        return WHITE if nugget[CachedDistanceSignal] < self._attribute[
            CurrentThresholdSignal] else ACC_RED if self._accessible_color_palette else RED

    def _add_grids(self):
        # Adds the UI items realizing the grid

        grid_xy = gl.GLGridItem()
        self._gl_widget.addItem(grid_xy)

        grid_xz = gl.GLGridItem()
        grid_xz.rotate(90, 1, 0, 0)
        self._gl_widget.addItem(grid_xz)

        grid_yz = gl.GLGridItem()
        grid_yz.rotate(90, 0, 1, 0)
        self._gl_widget.addItem(grid_yz)

    def _highlight_nugget(self, nugget_to_highlight, new_color, new_size):
        scatter_to_highlight, _ = self._nugget_to_displayed_items[nugget_to_highlight]

        if scatter_to_highlight is None:
            logger.warning("Couldn't find nugget to highlight.")
            return

        scatter_to_highlight.setData(color=new_color, size=new_size)

    def _add_other_best_guess(self, other_best_guess):
        self._add_item_to_grid(
            nugget_to_display_context=(other_best_guess, ACC_YELLOW if self._accessible_color_palette else YELLOW),
            annotation_text=_build_nuggets_annotation_text(other_best_guess),
            size=HIGHLIGHT_SIZE)

    def _update_legend(self):
        # Updates the legend associated with this grid according to the current value of the internal variables
        # `_color_with_meanings` and `_accessible_color_palette`

        def map_to_correct_color(accessible_color):
            # Maps each color to its standard or accessible version depending on the value of
            # `_accessible_color_palette`
            return accessible_color.corresponding_accessible_color if self._accessible_color_palette \
                else accessible_color.color

        colors_with_meanings = list(map(lambda color_with_meaning: (map_to_correct_color(color_with_meaning[0]),
                                                                    color_with_meaning[1]),
                                        self._colors_with_meanings))
        self._legend.update_colors_and_meanings(colors_with_meanings)


class EmbeddingVisualizerWindow(EmbeddingVisualizer, QMainWindow):
    """
    Class realizing an `EmbeddingVisualizer` in a separate window by inheriting from `EmbeddingVisualizer` and
    `QMainWindow`.

    Methods
    -------
    showEvent():
        Shows the associated window.
    closeEvent():
        Closes the associated window.
    """

    def __init__(self,
                 colors_with_meanings: List[Tuple[AccessibleColor, str]],
                 attribute: Attribute = None,
                 nuggets: List[InformationNugget] = None,
                 currently_highlighted_nugget: InformationNugget = None,
                 best_guess: InformationNugget = None,
                 other_best_guesses: List[InformationNugget] = None,
                 accessible_color_palette: bool = False):
        """
        Initializes an instance of this class by calling constructor of `EmbeddingVisualizer` and `QMainWindow` and sets
        up the required UI components.
        The parameters are propagated to the `EmbeddingVisualizer` constructor in order to add content to the grid
        initially.

        Parameters
        ----------
        colors_with_meanings: List[Tuple[QColor, str]]
            List of colors occurring in the grid associated with their meaning used to fill the given legend.
        attribute: Attribute = None
            `Attribute` instance representing the attribute to which the nuggets displayed within the grid belong to as
            its embedding is displayed in the grid as well.
        nuggets: List[InformationNugget] = None
            Nuggets whose dimension-reduced embedding vectors should be displayed within the grid.
        currently_highlighted_nugget: InformationNugget = None
            Refers to the nugget which is currently selected and therefore should be highlighted. If none, nothing is
            highlighted.
        best_guess: InformationNugget = None
            Refers to the best guess of the document represented by this grid and therefore should be highlighted. If
            none, nothing is highlighted. Applicable only in case the grid belongs to the document view and not to the
            document overview screen.
        other_best_guesses: List[InformationNugget] = None
            Nuggets representing best guesses from other documents which should be displayed in this grid as well
            initially. Applicable only in case the grid belongs to the document view and not to the document overview
            screen.
        accessible_color_palette: bool
            Specifies whether the colors used by the points displayed in the grid are accessible - usable for people
            with color blindness - or not.
        """

        # Call super constructors
        EmbeddingVisualizer.__init__(self,
                                     legend=EmbeddingVisualizerLegend(),
                                     colors_with_meanings=colors_with_meanings,
                                     attribute=attribute,
                                     nuggets=nuggets,
                                     currently_highlighted_nugget=currently_highlighted_nugget,
                                     best_guess=best_guess,
                                     accessible_color_palette=accessible_color_palette)
        QMainWindow.__init__(self)

        # Set up window
        self.setWindowTitle("3D Grid Visualizer")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

        # Set up layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.fullscreen_layout = QVBoxLayout()
        central_widget.setLayout(self.fullscreen_layout)

        # Add grid and legend item to the UI
        self.fullscreen_layout.addWidget(self._gl_widget, stretch=7)
        self.fullscreen_layout.addWidget(self._legend, stretch=1)

        self._add_grids()

        # If values which should be displayed in the grid are present, add them the grid, else make itself invisible
        if (attribute is not None and
                nuggets is not None and
                currently_highlighted_nugget is not None and
                best_guess is not None):
            self.update_and_display_params(attribute, nuggets, currently_highlighted_nugget, best_guess,
                                           other_best_guesses)
        else:
            self.setVisible(False)

    def showEvent(self, event):
        """
        Shows the associated window and start timer tracking the time, the window is opened.
        """

        super().showEvent(event)
        Tracker().start_timer(str(self.__class__))

    def closeEvent(self, event):
        """
        Closes the associated window and stop timer tracking the time, the window is opened.
        """

        Tracker().stop_timer(str(self.__class__))
        event.accept()


class EmbeddingVisualizerWidget(EmbeddingVisualizer, QWidget):
    """
    Class realizing an `EmbeddingVisualizer` within a widget by inheriting from `EmbeddingVisualizer` and `QWidget`.

    Each instance of this visualizer is associated with a fullscreen version which displays the same content and can
    be opened and closed with buttons.

    Methods
    -------
    enable_accessible_color_palette():
        Enables accessible color palette in this visualizer as well as in fullscreen version if opened.
    disable_accessible_color_palette():
        Disables accessible color palette in this visualizer as well as in fullscreen version if opened.
    return_from_embedding_visualizer_window(self):
        Close fullscreen version of this visualizer.
    update_other_best_guesses():
        Update variable holding best guesses from other documents.
    highlight_selected_nugget(nugget):
        Highlights selected nugget in this visualizer as well in fullscreen version if opened.
    highlight_best_guess(best_guess: InformationNugget):
        Highlights the best guess of the corresponding document in this visualizer as well in fullscreen version if
        opened.
    reset():
        Resets this widget by calling superclass implementation and resetting internal variables.
    """

    def __init__(self):
        """
        Initializes an instance of this class by determining the colors with their associated meanings used by the
        corresponding grid, calling the super constructors and setting up the required UI components.

        Required UI components cover the 3D grid, as well as buttons to show grid in separate window as well as adding /
        removing best guesses from other documents to / from the grid.

        The `EmbeddingVisualizer` is initialized without any nuggets leading to an initially empty grid.
        """

        # Determine colors with their associated meanings used by the corresponding grid
        colors_with_meanings = [
            (AccessibleColor(WHITE, WHITE), 'Below threshold'),
            (AccessibleColor(RED, ACC_RED), 'Above threshold'),
            (AccessibleColor(BLUE, ACC_BLUE), 'Documents best match'),
            (AccessibleColor(YELLOW, ACC_YELLOW), 'Other documents best matches'),
            (AccessibleColor(PURPLE, ACC_PURPLE), 'Could not determine correct color')
        ]

        # Call super constructors
        EmbeddingVisualizer.__init__(self, EmbeddingVisualizerLegend(), colors_with_meanings)
        QWidget.__init__(self)

        # Set up layout
        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        # Set up grid widget and add to layout
        self._gl_widget.setMinimumHeight(300)  # Set the initial height of the grid to 200
        self.layout.addWidget(self._gl_widget)

        self.layout.addWidget(self._legend)

        # Set up buttons and add to layout
        self.best_guesses_widget = QWidget()
        self.best_guesses_widget_layout = QHBoxLayout(self.best_guesses_widget)
        self.best_guesses_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.best_guesses_widget_layout.setSpacing(0)
        self.fullscreen_button = QPushButton("Show 3D Grid in windowed fullscreen mode")
        self.fullscreen_button.clicked.connect(self._show_embedding_visualizer_window)
        self.best_guesses_widget_layout.addWidget(self.fullscreen_button)
        self.show_other_best_guesses_button = QPushButton("Show best guesses from other documents")
        self.show_other_best_guesses_button.clicked.connect(self._handle_show_other_best_guesses_clicked)
        self.best_guesses_widget_layout.addWidget(self.show_other_best_guesses_button)
        self.remove_other_best_guesses_button = QPushButton("Stop showing best guesses from other documents")
        self.remove_other_best_guesses_button.setEnabled(False)
        self.remove_other_best_guesses_button.clicked.connect(self._handle_remove_other_best_guesses_clicked)
        self.best_guesses_widget_layout.addWidget(self.remove_other_best_guesses_button)
        self.layout.addWidget(self.best_guesses_widget)

        # Add items representing the grid itself to the grid widget
        self._add_grids()

        # Init internal variables
        self._fullscreen_window = None
        self._other_best_guesses = None

    def enable_accessible_color_palette(self):
        """
        Invokes `enable_accessible_color_palette()` method of the `EmbeddingVisualizer` superclass for this instance. If
        present, invokes the same method on the `EmbeddingVisualizer` instance realizing the fullscreen version of
        this visualizer to enable accessible color palette there as well.

        More detailed information about the `enable_accessible_color_palette()` method are elaborated in implementation
        of superclass.
        """

        # Call superclass implementation to enable accessible color palette on this grid
        super().enable_accessible_color_palette_()

        # Enable accessible color palette in fullscreen window if present
        if self._fullscreen_window is not None:
            self._fullscreen_window.enable_accessible_color_palette_()

    def disable_accessible_color_palette(self):
        """
        Invokes `disable_accessible_color_palette()` method of the `EmbeddingVisualizer` superclass for this instance.
        If present, invokes the same method on the `EmbeddingVisualizer` instance realizing the fullscreen version of
        this visualizer to disable accessible color palette there as well.

        More detailed information about the `disable_accessible_color_palette()` method are elaborated in implementation
        of superclass.
        """

        # Call superclass implementation to disable accessible color palette on this grid
        super().disable_accessible_color_palette_()

        # Disable accessible color palette in fullscreen window if present
        if self._fullscreen_window is not None:
            self._fullscreen_window.disable_accessible_color_palette_()

    def return_from_embedding_visualizer_window(self):
        """
        Close fullscreen version of this visualizer.
        """

        self._fullscreen_window.close()
        self._fullscreen_window = None

    def update_other_best_guesses(self, other_best_guesses: List[InformationNugget]):
        """
        Update variable holding best guesses from other documents.

        Parameters
        ----------
        other_best_guesses: List[InformationNugget]
            List of other best guesses from other documents to which the internal variable should be updated.
        """

        self._other_best_guesses = other_best_guesses

    def highlight_selected_nugget(self, selected_nugget: InformationNugget):
        """
        Highlights selected nugget in this visualizer as well in fullscreen version if present.
        More details are provided in documentation of implementation in `EmbeddingVisualizer`.

        Realized by calling implementation in `EmbeddingVisualizer` of this method and same method on fullscreen version
        of this visualizer.

        Parameters
        ----------
        selected_nugget: InformationNugget
            Nugget whose representation in the grid should be highlighted.
        """

        # Highlight selected nugget in this visualizer
        super().highlight_selected_nugget(selected_nugget)

        # Highlight selected nugget in fullscreen version
        if self._fullscreen_window is not None:
            self._fullscreen_window.highlight_selected_nugget(selected_nugget)

    def highlight_best_guess(self, best_guess: InformationNugget):
        """
        Highlights the best guess of the corresponding document in this visualizer as well in fullscreen version if
        present.
        More details are provided in documentation of implementation in `EmbeddingVisualizer`.

        Realized by calling implementation in `EmbeddingVisualizer` of this method and same method on fullscreen
        version of this visualizer.

        Applicable only if this visualizer belongs to the document view as only in this case the visualizer covers one
        document providing only one best guess.

        Parameters
        ----------
        best_guess: InformationNugget
            Nugget whose representation in the grid should be highlighted.
        """

        # Highlight selected nugget in this visualizer
        super().highlight_best_guess(best_guess)

        # Highlight selected nugget in fullscreen version
        if self._fullscreen_window is not None:
            self._fullscreen_window.highlight_best_guess(best_guess)

    def reset(self):
        """
        Resets this widget by calling superclass implementation and resetting internal variables.
        More details are provided in documentation of superclass implementation.
        """

        # Call superclass implementation
        super().reset()

        # Reset internal variables
        self._fullscreen_window = None
        self._other_best_guesses = None

        self.show_other_best_guesses_button.setEnabled(True)
        self.remove_other_best_guesses_button.setEnabled(False)

    def hide(self):
        """
        Hide this widget and close fullscreen version if present.
        """

        super().hide()
        if self._fullscreen_window is not None:
            self._fullscreen_window.close()

    @track_button_click("fullscreen embedding visualizer")
    def _show_embedding_visualizer_window(self):
        # Opens the fullscreen version of this visualizer and track that the corresponding has been clicked.

        if self._fullscreen_window is None:
            self._fullscreen_window = EmbeddingVisualizerWindow(colors_with_meanings=self._colors_with_meanings,
                                                                attribute=self._attribute,
                                                                nuggets=list(self._nugget_to_displayed_items.keys()),
                                                                currently_highlighted_nugget=self._currently_highlighted_nugget,
                                                                best_guess=self._best_guess)
        self._fullscreen_window.show()

    @track_button_click(button_name="show other best guesses from other documents")
    def _handle_show_other_best_guesses_clicked(self):
        # Adds the best guesses from other documents - contained in the internal variable `_other_best_guesses` - to
        # this visualizer and the fullscreen version if opened
        # Track that the corresponding button has been clicked.

        # Log warning if no other best guesses are available
        if self._other_best_guesses is None:
            logger.warning("Can not display best guesses from other documents as these best guesses have not been "
                           "initialized yet.")
            return

        # Only the currently applicable button of the buttons to add and remove other best guesses should be enabled
        self.show_other_best_guesses_button.setEnabled(False)
        self.remove_other_best_guesses_button.setEnabled(True)

        # Add other best guesses to this visualizer and fullscreen version if opened
        self.display_other_best_guesses(self._other_best_guesses)
        if self._fullscreen_window is not None:
            self._fullscreen_window.display_other_best_guesses(self._other_best_guesses)

    @track_button_click(button_name="stop showing other best guesses from other documents")
    def _handle_remove_other_best_guesses_clicked(self):
        # Removes the best guesses from other documents - contained in the internal variable `_other_best_guesses` -
        # from this visualizer and the fullscreen version if opened.
        # Track that the corresponding button has been clicked.

        self.show_other_best_guesses_button.setEnabled(True)
        self.remove_other_best_guesses_button.setEnabled(False)

        self._remove_nuggets_from_widget(self._other_best_guesses)
        if self._fullscreen_window is not None:
            self._fullscreen_window._remove_nuggets_from_widget(self._other_best_guesses)


dialog = InfoDialog()


class BarChartVisualizerWidget(QWidget):
    """
    A QWidget-based class that provides a UI widget for visualizing cosine values in a bar chart.
    It allows users to update the data, display a bar chart with certainty values, and interact with
    the chart (e.g., displaying annotations on click).
    """
    def __init__(self, parent=None):
        """
        Initializes the BarChartVisualizerWidget, sets up the layout and button,
        and prepares attributes to store data, the chart window, and interactive state.
        """
        super(BarChartVisualizerWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("Show Bar Chart with cosine values")
        self.layout.addWidget(self.button)
        self.data = []
        self.button.clicked.connect(self.show_bar_chart)
        self.window: QMainWindow = None
        self.current_annotation_index = None
        self.bar = None

    def update_data(self, nuggets):
        """
        Updates the widget's data based on the provided nuggets. Resets any previous state
        and processes the nuggets to extract text and cosine values.

        :param nuggets: List of information nuggets with cosine similarity values.
        """
        self.reset()

        self.data = [(_create_sanitized_text(nugget),
                      np.round(nugget[CachedDistanceSignal], 3))
                     for nugget in nuggets]

    @track_button_click("show bar chart")
    def show_bar_chart(self):
        """
        Displays the bar chart using the current data. If no data is available, the method returns early. Represents a button
        """
        if not self.data:
            return
        self.plot_bar_chart()

    def _unique_nuggets(self):
        """
        Ensures that only the most relevant (i.e., minimal cosine distance) nuggets are included in the data.
        Filters out duplicates based on text, keeping only the lowest cosine distance for each unique nugget.
        """
        min_dict = {}
        for item in self.data:
            key, value = item
            if key not in min_dict or value < min_dict[key]:
                min_dict[key] = value
        self.data = [(key, min_dict[key]) for key in min_dict]

    def plot_bar_chart(self):
        """
        Generates and displays the bar chart with cosine-based certainty values.
        Includes interactive functionality for annotations and customizable axes.
        """
        self._unique_nuggets()
        if self.window is not None:
            self.window.close()

        fig = Figure()
        ax = fig.add_subplot(111)
        texts, distances = zip(*self.data)

        rounded_certainties = np.round(np.ones(len(distances)) - distances, 3)
        x_positions = [0]
        for i, y_val in enumerate(rounded_certainties):
            if i == 0:
                continue
            if rounded_certainties[i - 1] != y_val:
                x_positions.append(x_positions[i - 1] + 2)
            else:
                x_positions.append(x_positions[i - 1] + 1)

        self.bar = ax.bar(x_positions, rounded_certainties, alpha=0.75, picker=True, color=_get_colors(distances))
        ax.set_xticks([])
        ax.set_ylabel('Certainty', fontsize=15)
        ax.set_xlabel('Information Nuggets', fontsize=15)
        fig.subplots_adjust(left=0.115, right=0.920, top=0.945, bottom=0.065)
        for idx, rect in enumerate(self.bar):
            height = rect.get_height()
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                height / 2,
                f'{texts[idx]}',
                ha='center',
                va='center',
                rotation=90,  # Rotate text by 90 degrees
                fontsize=12,
                color='white'  # fontcolors[idx]# Optional: Adjust font size
            )

        self.bar_chart_canvas = FigureCanvas(fig)
        self.bar_chart_canvas.setMinimumWidth(
            max(0.9 * WINDOW_WIDTH, len(texts) * 50))  # Set a minimum width based on number of bars

        scroll_area = QScrollArea()
        scroll_area.setWidget(self.bar_chart_canvas)
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll_area.setFrameShape(QFrame.Shape.NoFrame)

        self.window = QMainWindow()
        self.window.closeEvent = self.closeWindowEvent
        self.window.showEvent = self.showWindowEvent

        self.window.setWindowTitle("Bar Chart")
        self.window.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)
        self.window.setCentralWidget(scroll_area)

        self.bar_chart_toolbar = NavigationToolbar(self.bar_chart_canvas, self.window)
        self.window.addToolBar(self.bar_chart_toolbar)

        self.window.show()
        self.bar_chart_canvas.draw()

        self.annotation = ax.annotate(
            "", xy=(0, 0), xytext=(20, 20),
            textcoords="offset points", bbox=dict(boxstyle="round", fc="w"),
            arrowprops=dict(arrowstyle="->")
        )
        self.annotation.set_visible(False)
        self.bar_chart_canvas.mpl_connect('pick_event', self.on_pick)

        self.texts = texts
        self.distances = rounded_certainties

        info_list = [
            """ 
                <b>Hey there!</b><br>
                Before you access the cosine-distance scale, take a moment to read the following tips. 
                If you are familiar with the metrics used in WANNADB or have gone through this tutorial before,
                feel free to exit using the <b>skip</b> button.
            """,
            """<b>Cosine Similarity in 2D Plane:</b><br>
                Imagine that you and a friend are standing in the middle of a field, and both of you
                point in different directions. Each direction you point is like a piece of information.
                The closer your two arms are to pointing in the same direction, the more similar your
                thoughts or ideas are.<br><br>

                Same direction: If you both point in exactly the same direction, it means your ideas
                (or pieces of information) are exactly alike. This is like saying:
                "We’re thinking the same thing!" <br><br>

                Opposite direction: If you point in completely opposite directions, your ideas are as
                different as they can be. You’re thinking about completely different things.<br><br>

                Right angle: If your arms are at a 90-degree angle, you're pointing in different directions,
                but not as different as pointing in opposite directions. You’re thinking about different things,
                but there might still be a tiny bit of connection.<br><br>
                
                Before skipping over to the next tip, try to reason which vector is the most similar to vector A
                in the image below!
            """,
            """<b>Multi Dimensionality of Vectors and Cosine Distance</b><br>
                Vectors may have more than 2 dimensions, as was the case of you and your friend on the field. The
                mathematical formula guarantees a value between -1 and 1 for each pair of vectors, for any number
                of dimensions.<br><br>
                
                The cosine similarity is equal to 1 when the vectors point at the same direction, -1 when the vectors
                point in opposite directions, and 0 when the vectors are perpendicular to each other.<br><br> 
                
                As cosine similarity expresses how similar two vectors are, a higher value (in the range from -1 to 1)
                expresses a higher similarity. In wanna-db we use the dual concept of cosine distance. Contrary to 
                cosine similarity, a higher value in the cosine distance metric, means a higher degree of dissimilarity. 
                <br><span>cos-dist(<b>a</b>, <b>b</b>) = 1 - cos-sim(<b>a</b>, <b>b</b>)</span><br><br>
                
                Take a look at the image below. The yellow dots are closer to a fixed vector(not shown here), whereas the scattered
                red dots are further away. Think about what the varying cosine distances imply for the spatial configuration.  
                
            """,
            """<b>Cosine-Driven Choices: Ranking Database Values</b>: 
                The bar chart shows all nuggets found inside the documents, lined after each other along the x-axis.
                The y axis shows the normalized cosine distance. As we mentioned, the lower the cosine distance is,
                the more certain we are that the corresponding word belongs to what we are looking for: a value in the database. <br><br>
                
                
                <b>QUESTION</b>: After you explore the bar chart, ask yourself - do the answers on the left tend to be more plausible? <br><br>
                <b>PRO TIP</b>: Click on each bar to show the exact value, as well as the full information nugget.
                """
        ]
        image_list = [
            None,
            'wannadb_ui/resources/info_popups/cosine_similarity.png',  # Add the path to an SVG image
            'wannadb_ui/resources/info_popups/screenshot_grid.png',  # Regular PNG image
            'wannadb_ui/resources/info_popups/screenshot_bar_chart.png'
        ]

        global dialog
        assert len(info_list) == len(image_list)
        dialog.set_info_list(info_list)
        dialog.set_image_list(image_list)
        dialog.exec()

    def on_pick(self, event):
        """
        Handles click events on the bar chart. When a bar is clicked, displays an annotation
        with detailed information about the clicked nugget.

        :param event: The pick event triggered by clicking a bar.
        """
        if isinstance(event.artist, Rectangle):
            patch = event.artist
            index = self.bar.get_children().index(patch)
            if self.current_annotation_index == index and self.annotation.get_visible():
                # If the same bar is clicked again, hide the annotation
                self.annotation.set_visible(False)
                self.current_annotation_index = None
            else:
                # Show annotation for the clicked bar
                text = f"Information Nugget: \n{self.texts[index]} \n\n Value: {self.distances[index]}"
                self.annotation.set_text(text)
                annotation_x = patch.get_x() + patch.get_width() / 2
                annotation_y = patch.get_height() / 2
                self.annotation.xy = (annotation_x, annotation_y)
                self.annotation.set_visible(True)
                self.current_annotation_index = index
            self.bar_chart_canvas.draw_idle()

    def reset(self):
        """
        Resets the state of the bar chart widget, clearing any previously stored data and bars.
        """
        self.data = []
        self.bar = None

    def showWindowEvent(self, event):
        """
        These and method below needed for tracking how much time user spent on the bar chart
        """
        super().showEvent(event)
        Tracker().start_timer(str(self.__class__))

    def closeWindowEvent(self, event):
        event.accept()
        Tracker().stop_timer(str(self.__class__))
