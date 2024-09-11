import itertools
import logging
import math
from operator import itemgetter
from typing import List, Dict, Tuple, Union

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QFont, QColor, QPixmap, QPainter
from PyQt6.QtSvgWidgets import QSvgWidget
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QMainWindow, QHBoxLayout, QFrame, QScrollArea, \
    QApplication, QLabel, QMessageBox, QDialog
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
from wannadb_ui.common import AccessibleColor, BUTTON_FONT_SMALL
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
DEFAULT_NUGGET_SIZE = 7

app = QApplication([])
screen = app.primaryScreen()
screen_geometry = screen.geometry()
WINDOW_WIDTH = int(screen_geometry.width() * 0.7)
WINDOW_HEIGHT = int(screen_geometry.height() * 0.7)


def get_colors(distances, color_start='red', color_end='blue'):
    cmap = LinearSegmentedColormap.from_list("CustomMap", [color_start, color_end])
    norm = plt.Normalize(min(distances), max(distances))
    colors = [cmap(norm(value)) for value in distances]
    return colors


def build_nuggets_annotation_text(nugget) -> str:
    return f"{nugget.text}: {round(nugget[CachedDistanceSignal], 3)}"


def create_sanitized_text(nugget):
    return nugget.text.replace("\n", " ")


class PointLegend(QLabel):
    def __init__(self, point_meaning: str, point_color: QColor):
        super().__init__()

        self._height = 30
        self._width = 300
        self._circle_diameter = 10

        self._point_meaning = point_meaning
        self._point_color = point_color

        self._pixmap = QPixmap(self._width, self._height)
        self._pixmap.fill(Qt.GlobalColor.transparent)

        self._painter = QPainter(self._pixmap)

        circle_center = QPoint(self._circle_diameter, round(self._height / 2))

        self._painter.setPen(Qt.PenStyle.NoPen)
        self._painter.setBrush(point_color)
        self._painter.drawEllipse(circle_center, self._circle_diameter, self._circle_diameter)
        self._painter.setFont(BUTTON_FONT_SMALL)
        self._painter.setPen(pg.mkColor('black'))
        text_height = self._painter.fontMetrics().height()
        self._painter.drawText(circle_center.x() + self._circle_diameter + 5,
                               circle_center.y() + round(text_height / 4),
                               f': {self._point_meaning}')

        self._painter.end()

        self.setPixmap(self._pixmap)


class EmbeddingVisualizerLegend(QWidget):
    def __init__(self):
        super().__init__()

        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        self._point_legends = []

    def reset(self):
        for widget in self._point_legends:
            self.layout.removeWidget(widget)
        self._point_legends = []

    def update_colors_and_meanings(self, colors_with_meanings: List[Tuple[QColor, str]]):
        self.reset()

        for color, meaning in colors_with_meanings:
            point_legend = PointLegend(meaning, color)
            self.layout.addWidget(point_legend)
            self._point_legends.append(point_legend)


class EmbeddingVisualizer:
    def __init__(self,
                 legend: EmbeddingVisualizerLegend,
                 colors_with_meanings: List[Tuple[AccessibleColor, str]],
                 attribute: Attribute = None,
                 nuggets: List[InformationNugget] = None,
                 currently_highlighted_nugget: InformationNugget = None,
                 best_guess: InformationNugget = None,
                 other_best_guesses: List[InformationNugget] = None,
                 accessible_color_palette: bool = False):
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
        self._update_legend()

    def enable_accessible_color_palette_(self):
        self._accessible_color_palette = True
        self._update_legend()

    def disable_accessible_color_palette_(self):
        self._accessible_color_palette = False
        self._update_legend()

    def update_and_display_params(self,
                                  attribute: Attribute,
                                  nuggets: List[InformationNugget],
                                  currently_highlighted_nugget: Union[InformationNugget, None],
                                  best_guess: Union[InformationNugget, None],
                                  other_best_guesses: List[InformationNugget]):
        self.reset()

        if attribute is not None:
            self.display_attribute_embedding(attribute)
        else:
            logger.warning("Given attribute is null, can not display.")

        if nuggets:
            self._nuggets = nuggets
            self.display_nugget_embeddings(nuggets)
        else:
            logger.warning("Given nugget list is null or empty, can not display.")

        if best_guess is not None:
            self.highlight_best_guess(best_guess)
        else:
            logger.info("Given best_guess is null, can not highlight.")

        self.highlight_confirmed_matches()

        if currently_highlighted_nugget is not None:
            self.highlight_selected_nugget(currently_highlighted_nugget)
        else:
            logger.info("Given nugget to highlight is null, can not highlight.")

        self._other_best_guesses = other_best_guesses

    def add_item_to_grid(self,
                         nugget_to_display_context: Tuple[Union[InformationNugget, Attribute], Color],
                         annotation_text: str,
                         size: int = DEFAULT_NUGGET_SIZE):
        item_to_display, color = nugget_to_display_context
        position = np.array([item_to_display[PCADimensionReducedTextEmbeddingSignal]]) if isinstance(item_to_display,
                                                                                                     InformationNugget) \
            else np.array([item_to_display[PCADimensionReducedLabelEmbeddingSignal]])

        scatter = GLScatterPlotItem(pos=position, color=color, size=size, pxMode=True)
        annotation = GLTextItem(pos=[position[0][0], position[0][1], position[0][2]],
                                color=WHITE,
                                text=annotation_text,
                                font=EMBEDDING_ANNOTATION_FONT)

        self._gl_widget.addItem(scatter)
        self._gl_widget.addItem(annotation)

        if isinstance(item_to_display, InformationNugget):
            self._nugget_to_displayed_items[item_to_display] = (scatter, annotation)

    def highlight_best_guess(self, best_guess: InformationNugget):
        self._best_guess = best_guess

        if self._best_guess == self._currently_highlighted_nugget:
            self._highlight_nugget(self._best_guess, ACC_BLUE if self._accessible_color_palette else BLUE, 15)
            return

        self._highlight_nugget(self._best_guess, WHITE, 15)

    def highlight_selected_nugget(self, newly_selected_nugget: InformationNugget):
        (highlight_color, highlight_size), (reset_color, reset_size) = self._determine_update_values(
            previously_selected_nugget=self._currently_highlighted_nugget,
            newly_selected_nugget=newly_selected_nugget)

        if self._currently_highlighted_nugget is not None:
            currently_highlighted_scatter, _ = self._nugget_to_displayed_items[self._currently_highlighted_nugget]
            currently_highlighted_scatter.setData(color=reset_color, size=reset_size)

        self._highlight_nugget(nugget_to_highlight=newly_selected_nugget,
                               new_color=highlight_color,
                               new_size=highlight_size)

        self._currently_highlighted_nugget = newly_selected_nugget

    def display_other_best_guesses(self, other_best_guesses: List[InformationNugget]):
        for other_best_guess in other_best_guesses:
            self._add_other_best_guess(other_best_guess)

    def remove_other_best_guesses(self, other_best_guesses: List[InformationNugget]):
        self.remove_nuggets_from_widget(other_best_guesses)

    def display_nugget_embeddings(self, nuggets):
        for nugget in nuggets:
            nugget_to_display_context = (nugget, self._determine_nuggets_color(nugget))

            self.add_item_to_grid(nugget_to_display_context=nugget_to_display_context,
                                  annotation_text=build_nuggets_annotation_text(nugget))

    def display_attribute_embedding(self, attribute):
        self.add_item_to_grid(nugget_to_display_context=(attribute, ACC_RED if self._accessible_color_palette else RED),
                              annotation_text=attribute.name)
        self._attribute = attribute  # save for later use

    def remove_nuggets_from_widget(self, nuggets_to_remove):
        for nugget in nuggets_to_remove:
            scatter, annotation = self._nugget_to_displayed_items.pop(nugget)

            self._gl_widget.removeItem(scatter)
            self._gl_widget.removeItem(annotation)

    def highlight_confirmed_matches(self):
        if self._attribute is None:
            logger.warning("Attribute has not been initialized yet, can not highlight confirmed matches.")
            return

        for confirmed_match in self._attribute.confirmed_matches:
            if confirmed_match in self._nugget_to_displayed_items:
                self._highlight_nugget(confirmed_match, ACC_GREEN if self._accessible_color_palette else GREEN,
                                       DEFAULT_NUGGET_SIZE)

    def reset(self):
        for nugget, (scatter, annotation) in self._nugget_to_displayed_items.items():
            self._gl_widget.removeItem(scatter)
            self._gl_widget.removeItem(annotation)

        self._nugget_to_displayed_items = {}
        self._currently_highlighted_nugget = None
        self._best_guess = None

    def _determine_update_values(self, previously_selected_nugget, newly_selected_nugget) -> (
            (int, Color), (int, Color)):

        highlight_color = ACC_BLUE if self._accessible_color_palette else BLUE
        highlight_size = 15 if newly_selected_nugget == self._best_guess else 10

        if previously_selected_nugget is None:
            reset_color = WHITE
            reset_size = DEFAULT_NUGGET_SIZE
        elif previously_selected_nugget in self._attribute.confirmed_matches:
            reset_color = ACC_GREEN if self._accessible_color_palette else GREEN
            reset_size = DEFAULT_NUGGET_SIZE
        elif previously_selected_nugget == self._best_guess:
            reset_color = WHITE
            reset_size = 15
        else:
            reset_color = self._determine_nuggets_color(previously_selected_nugget)
            reset_size = DEFAULT_NUGGET_SIZE

        return (highlight_color, highlight_size), (reset_color, reset_size)

    def _determine_nuggets_color(self, nugget: InformationNugget) -> Color:
        if (self._attribute is None or
                CurrentThresholdSignal.identifier not in self._attribute.signals):
            logger.warning(f"Could not determine nuggets color from given attribute: {self._attribute}. "
                           f"Will return purple as color highlighting nuggets with this issue.")
            return ACC_PURPLE if self._accessible_color_palette else PURPLE

        return WHITE if nugget[CachedDistanceSignal] < self._attribute[
            CurrentThresholdSignal] else ACC_RED if self._accessible_color_palette else RED

    def _add_grids(self):
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
        self.add_item_to_grid(
            nugget_to_display_context=(other_best_guess, ACC_YELLOW if self._accessible_color_palette else YELLOW),
            annotation_text=build_nuggets_annotation_text(other_best_guess),
            size=15)

    def _update_legend(self):
        def map_to_correct_color(accessible_color):
            return accessible_color.corresponding_accessible_color if self._accessible_color_palette \
                else accessible_color.color

        colors_with_meanings = list(map(lambda color_with_meaning: (map_to_correct_color(color_with_meaning[0]),
                                                                    color_with_meaning[1]),
                                        self._colors_with_meanings))
        self._legend.update_colors_and_meanings(colors_with_meanings)


class EmbeddingVisualizerWindow(EmbeddingVisualizer, QMainWindow):
    def __init__(self,
                 colors_with_meanings: List[Tuple[AccessibleColor, str]],
                 attribute: Attribute = None,
                 nuggets: List[InformationNugget] = None,
                 currently_highlighted_nugget: InformationNugget = None,
                 best_guess: InformationNugget = None,
                 other_best_guesses: List[InformationNugget] = None,
                 accessible_color_palette: bool = False):
        EmbeddingVisualizer.__init__(self,
                                     legend=EmbeddingVisualizerLegend(),
                                     colors_with_meanings=colors_with_meanings,
                                     attribute=attribute,
                                     nuggets=nuggets,
                                     currently_highlighted_nugget=currently_highlighted_nugget,
                                     best_guess=best_guess,
                                     accessible_color_palette=accessible_color_palette)
        QMainWindow.__init__(self)
        self.accessible_color_palette = accessible_color_palette

        self.setWindowTitle("3D Grid Visualizer")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.fullscreen_layout = QVBoxLayout()
        central_widget.setLayout(self.fullscreen_layout)

        self.fullscreen_layout.addWidget(self._gl_widget, stretch=7)
        self.fullscreen_layout.addWidget(self._legend, stretch=1)

        self._add_grids()

        if (attribute is not None and
                nuggets is not None and
                currently_highlighted_nugget is not None and
                best_guess is not None):
            self.update_and_display_params(attribute, nuggets, currently_highlighted_nugget, best_guess,
                                           other_best_guesses)
        else:
            self.setVisible(False)

    def showEvent(self, event):
        super().showEvent(event)
        Tracker().start_timer(str(self.__class__))

    def _enable_accessible_color_palette(self):
        self.accessible_color_palette = True
        self.enable_accessible_color_palette_()

    def _disable_accessible_color_palette(self):
        self.accessible_color_palette = False
        self.disable_accessible_color_palette_()

    def closeEvent(self, event):
        Tracker().stop_timer(str(self.__class__))
        event.accept()


class EmbeddingVisualizerWidget(EmbeddingVisualizer, QWidget):
    def __init__(self):
        colors_with_meanings = [
            (AccessibleColor(WHITE, WHITE), 'Below threshold'),
            (AccessibleColor(ACC_RED, RED), 'Above threshold'),
            (AccessibleColor(ACC_BLUE, BLUE), 'Documents best match'),
            (AccessibleColor(ACC_YELLOW, YELLOW), 'Other documents best matches'),
            (AccessibleColor(ACC_PURPLE, PURPLE), 'Could not determine correct color')
        ]
        EmbeddingVisualizer.__init__(self, EmbeddingVisualizerLegend(), colors_with_meanings)
        QWidget.__init__(self)

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        self._gl_widget.setMinimumHeight(300)  # Set the initial height of the grid to 200
        self.layout.addWidget(self._gl_widget)

        self.layout.addWidget(self._legend)

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
        self.accessible_color_palette = False

        self._add_grids()

        self._fullscreen_window = None
        self._other_best_guesses = None

    @track_button_click("fullscreen embedding visualizer")
    def _show_embedding_visualizer_window(self):
        if self._fullscreen_window is None:
            self._fullscreen_window = EmbeddingVisualizerWindow(colors_with_meanings=self._colors_with_meanings,
                                                                attribute=self._attribute,
                                                                nuggets=list(self._nugget_to_displayed_items.keys()),
                                                                currently_highlighted_nugget=self._currently_highlighted_nugget,
                                                                best_guess=self._best_guess)
        self._fullscreen_window.show()

    def enable_accessible_color_palette(self):
        self.accessible_color_palette = True
        if self._fullscreen_window is None:
            pass
        else:
            self._fullscreen_window.enable_accessible_color_palette_()

    def disable_accessible_color_palette(self):
        self.accessible_color_palette = False
        if self._fullscreen_window is None:
            pass
        else:
            self._fullscreen_window.disable_accessible_color_palette_()

    def return_from_embedding_visualizer_window(self):
        self._fullscreen_window.close()
        self._fullscreen_window = None

    def update_other_best_guesses(self, other_best_guesses):
        self._other_best_guesses = other_best_guesses

    def highlight_selected_nugget(self, nugget):
        super().highlight_selected_nugget(nugget)

        if self._fullscreen_window is not None:
            self._fullscreen_window.highlight_selected_nugget(nugget)

    def highlight_best_guess(self, best_guess: InformationNugget):
        super().highlight_best_guess(best_guess)

        if self._fullscreen_window is not None:
            self._fullscreen_window.highlight_best_guess(best_guess)

    def reset(self):
        super().reset()

        self._fullscreen_window = None
        self._other_best_guesses = None

        self.show_other_best_guesses_button.setEnabled(True)
        self.remove_other_best_guesses_button.setEnabled(False)

    def hide(self):
        super().hide()
        if self._fullscreen_window is not None:
            self._fullscreen_window.close()

    @track_button_click(button_name="show other best guesses from other documents")
    def _handle_show_other_best_guesses_clicked(self):
        if self._other_best_guesses is None:
            logger.warning("Can not display best guesses from other documents as these best guesses have not been "
                           "initialized yet.")
            return

        self.show_other_best_guesses_button.setEnabled(False)
        self.remove_other_best_guesses_button.setEnabled(True)

        self.display_other_best_guesses(self._other_best_guesses)
        if self._fullscreen_window is not None:
            self._fullscreen_window.display_other_best_guesses(self._other_best_guesses)

    @track_button_click(button_name="stop showing other best guesses from other documents")
    def _handle_remove_other_best_guesses_clicked(self):
        self.show_other_best_guesses_button.setEnabled(True)
        self.remove_other_best_guesses_button.setEnabled(False)

        self.remove_nuggets_from_widget(self._other_best_guesses)
        if self._fullscreen_window is not None:
            self._fullscreen_window.remove_nuggets_from_widget(self._other_best_guesses)


class BarChartVisualizerWidget(QWidget):
    def __init__(self, parent=None):
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
        self.reset()

        self.data = [(create_sanitized_text(nugget),
                      np.round(nugget[CachedDistanceSignal], 3))
                     for nugget in nuggets]

    @track_button_click("show bar chart")
    def show_bar_chart(self):
        if not self.data:
            return
        self.plot_bar_chart()

    def _unique_nuggets(self):
        min_dict = {}
        for item in self.data:
            key, value = item
            if key not in min_dict or value < min_dict[key]:
                min_dict[key] = value
        self.data = [(key, min_dict[key]) for key in min_dict]

    def plot_bar_chart(self):
        self._unique_nuggets()
        if self.window is not None:
            self.window.close()

        fig = Figure()
        ax = fig.add_subplot(111)
        texts, distances = zip(*self.data)

        rounded_distances = np.round(distances, 3)

        self.bar = ax.bar(texts, rounded_distances, alpha=0.75, picker=True, color=get_colors(distances))
        ax.set_xticks([])
        ax.set_ylabel('Cosine Distance', fontsize=15)
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
        self.distances = rounded_distances

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
            'wannadb_ui/resources/visualizations/cosine_similarity.png',  # Add the path to an SVG image
            'wannadb_ui/resources/visualizations/screenshot_grid.png',  # Regular PNG image
            'wannadb_ui/resources/visualizations/screenshot_bar_chart.png'
        ]

        dialog = InfoDialog(info_list, image_list)
        dialog.exec()

    def on_pick(self, event):
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
        self.data = []
        self.bar = None

    def showWindowEvent(self, event):
        super().showEvent(event)
        Tracker().start_timer(str(self.__class__))

    def closeWindowEvent(self, event):
        event.accept()
        Tracker().stop_timer(str(self.__class__))


class ScatterPlotVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super(ScatterPlotVisualizerWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("Show Scatter Plot with Cosine Distances")
        self.layout.addWidget(self.button)
        self.data = []  # Store data as a list of tuples
        self.button.clicked.connect(self.show_scatter_plot)
        self.scatter_plot_canvas = None
        self.scatter_plot_toolbar = None
        self.window = None
        self.annotation = None
        self.texts = None
        self.distances = None
        self.y = None
        self.scatter = None
        self.accessible_color_palette = False

    def enable_accessible_color_palette(self):
        self.accessible_color_palette = True

    def disable_accessible_color_palette(self):
        self.accessible_color_palette = False

    def append_data(self, data_tuple):
        self.data.append(data_tuple)

    def update_data(self, nuggets):
        self.reset()

        self.data = [(create_sanitized_text(nugget),
                      np.round(nugget[CachedDistanceSignal], 3))
                     for nugget in nuggets]

    def clear_data(self):
        self.data = []
        self.texts = None
        self.distances = None
        self.y = None
        self.scatter = None
        if self.window is not None:
            self.window.close()
        self.scatter_plot_canvas = None
        self.scatter_plot_toolbar = None
        self.window = None
        self.annotation = None

    @track_button_click("show scatter plot")
    def show_scatter_plot(self):
        if not self.data:
            return

        # Clear data to prevent duplication
        self.data = list(set(self.data))

        # Close existing scatter plot
        if self.window is not None:
            self.window.close()

        fig = Figure()
        ax = fig.add_subplot(111)
        texts, distances = zip(*self.data)

        # Round the distances to a fixed number of decimal places
        rounded_distances = np.round(distances, 3)

        # Ensure consistent x-values for the same rounded distance
        distance_map = {}
        for original, rounded in zip(distances, rounded_distances):
            if rounded not in distance_map:
                distance_map[rounded] = original

        consistent_distances = [distance_map[rd] for rd in rounded_distances]

        # Generate jittered y-values for points with the same x-value
        unique_distances = {}
        for i, distance in enumerate(consistent_distances):
            if distance not in unique_distances:
                unique_distances[distance] = []
            unique_distances[distance].append(i)

        y = np.zeros(len(distances))
        for distance, indices in unique_distances.items():
            jitter = np.linspace(-0.4, 0.4, len(indices))
            for j, index in enumerate(indices):
                y[index] = jitter[j]

        # Generating a list of colors for each point
        num_points = len(distances)
        colormap = plt.cm.jet
        norm = plt.Normalize(min(rounded_distances), max(rounded_distances))
        colors = colormap(norm(rounded_distances))

        # Plot the points
        scatter = ax.scatter(rounded_distances, y, c=colors, alpha=0.75, picker=True)  # Enable picking

        ax.set_xlabel("Cosine Distance")
        ax.set_xlim(min(rounded_distances) - 0.05,
                    max(rounded_distances) + 0.05)  # Adjust x-axis limits for better visibility
        ax.set_yticks([])  # Remove y-axis labels to avoid confusion
        fig.subplots_adjust(left=0.020, right=0.980, top=0.940, bottom=0.075)
        # fig.tight_layout()

        # Create canvas
        self.scatter_plot_canvas = FigureCanvas(fig)

        # Create a new window for the plot
        self.window = QMainWindow()
        self.window.closeEvent = self.closeWindowEvent
        self.window.showEvent = self.showWindowEvent
        self.window.setWindowTitle("Scatter Plot")

        self.window.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

        # Set the central widget of the window to the canvas
        self.window.setCentralWidget(self.scatter_plot_canvas)

        # Add NavigationToolbar to the window
        self.scatter_plot_toolbar = NavigationToolbar(self.scatter_plot_canvas, self.window)
        self.window.addToolBar(self.scatter_plot_toolbar)

        # Show the window
        self.window.show()
        self.scatter_plot_canvas.draw()

        # Create an annotation box
        self.annotation = ax.annotate(
            "", xy=(0, 0), xytext=(20, 20),
            textcoords="offset points", bbox=dict(boxstyle="round", fc="w"),
            arrowprops=dict(arrowstyle="->")
        )
        self.annotation.set_visible(False)

        # Connect the pick event
        self.scatter_plot_canvas.mpl_connect("pick_event", self.on_pick)

        # Store the data for use in the event handler
        self.texts = texts
        self.distances = rounded_distances
        self.y = y
        self.scatter = scatter

    def on_pick(self, event):
        if event.artist != self.scatter:
            return
        # Get index of the picked point
        ind = event.ind[0]

        # Update annotation text and position
        self.annotation.xy = (self.distances[ind], self.y[ind])
        text = f"Text: {self.texts[ind]}\nValue: {self.distances[ind]:.3f}"
        self.annotation.set_text(text)
        self.annotation.set_visible(True)
        self.scatter_plot_canvas.draw_idle()

    def reset(self):
        self.data = []
        self.bar = None

    def showWindowEvent(self, event):
        super().showEvent(event)
        Tracker().start_timer(str(self.__class__))

    def closeWindowEvent(self, event):
        event.accept()
        Tracker().stop_timer(str(self.__class__))


class InfoDialog(QDialog):
    def __init__(self, info_list, image_list):
        super().__init__()

        self.info_list = info_list
        self.image_list = image_list
        self.current_index = 0

        # Set up the dialog layout
        self.layout = QVBoxLayout()

        # Set a fixed width for the dialog
        self.setFixedWidth(400)  # Set the fixed width you prefer

        # Label to display the information text
        self.info_label = QLabel(self.info_list[self.current_index])
        self.info_label.setWordWrap(True)  # Enable word wrap for the label
        self.layout.addWidget(self.info_label)

        # Widget to display the PNG image
        self.image_widget = QLabel()
        self.layout.addWidget(self.image_widget)

        self.update_image()  # Update image on dialog creation

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

        # Disable the "Previous" button initially
        self.update_buttons()

        # Set the layout for the dialog
        self.setLayout(self.layout)

    # Method to update the displayed information
    def update_info(self):
        self.info_label.setText(self.info_list[self.current_index])
        self.update_image()

    # Method to update the displayed PNG image
    def update_image(self):
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
        self.prev_button.setEnabled(self.current_index > 0)
        self.next_button.setEnabled(self.current_index < len(self.info_list) - 1)

    # Method to show the previous piece of information
    def show_previous(self):
        if self.current_index > 0:
            self.current_index -= 1
            self.update_info()
        self.update_buttons()

    # Method to show the next piece of information
    def show_next(self):
        if self.current_index < len(self.info_list) - 1:
            self.current_index += 1
            self.update_info()
        self.update_buttons()

    # Method to skip and close the dialog
    def skip(self):
        self.accept()