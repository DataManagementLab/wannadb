import logging

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QMainWindow, QHBoxLayout, QFrame, QScrollArea, \
    QApplication
from matplotlib import pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.figure import Figure
from matplotlib.patches import Rectangle
from pyqtgraph import Color
from pyqtgraph.opengl import GLViewWidget, GLScatterPlotItem, GLTextItem

from wannadb.data.signals import PCADimensionReducedTextEmbeddingSignal, PCADimensionReducedLabelEmbeddingSignal, \
    CachedDistanceSignal

logger: logging.Logger = logging.getLogger(__name__)

RED = pg.mkColor('red')
BLUE = pg.mkColor('blue')
GREEN = pg.mkColor('green')
WHITE = pg.mkColor('white')
YELLOW = pg.mkColor('yellow')
EMBEDDING_ANNOTATION_FONT = QFont('Helvetica', 10)

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


def add_grids(widget):
    grid_xy = gl.GLGridItem()
    widget.addItem(grid_xy)

    grid_xz = gl.GLGridItem()
    grid_xz.rotate(90, 1, 0, 0)
    widget.addItem(grid_xz)

    grid_yz = gl.GLGridItem()
    grid_yz.rotate(90, 0, 1, 0)
    widget.addItem(grid_yz)


def update_grid(gl_widget, points_to_display, color, annotation_text, size=3) -> (GLScatterPlotItem, GLTextItem):
    scatter = GLScatterPlotItem(pos=points_to_display, color=color, size=size, pxMode=True)
    annotation = GLTextItem(pos=[points_to_display[0][0], points_to_display[0][1], points_to_display[0][2]],
                            color=WHITE,
                            text=annotation_text,
                            font=EMBEDDING_ANNOTATION_FONT)
    gl_widget.addItem(scatter)
    gl_widget.addItem(annotation)
    return scatter, annotation


def build_annotation_text(nugget) -> str:
    return f"{nugget.text}: {round(nugget[CachedDistanceSignal], 3)}"


def add_other_best_guess(gl_widget, other_best_guess, nugget_to_displayed_items):
    nugget_embedding: np.ndarray = np.array([other_best_guess[PCADimensionReducedTextEmbeddingSignal]])
    scatter, annotation = update_grid(gl_widget, nugget_embedding, YELLOW,
                                      build_annotation_text(other_best_guess), 15)
    nugget_to_displayed_items[other_best_guess] = (scatter, annotation)


def remove_nuggets_from_widget(nuggets_to_remove, nugget_to_displayed_items, gl_widget):
    for nugget in nuggets_to_remove:
        scatter, annotation = nugget_to_displayed_items.pop(nugget)

        gl_widget.removeItem(scatter)
        gl_widget.removeItem(annotation)


def highlight_best_guess(best_guess, currently_highlighted_nugget, nugget_to_displayed_items):
    if best_guess == currently_highlighted_nugget:
        highlight_nugget(best_guess, nugget_to_displayed_items, BLUE, 15)
        return

    highlight_nugget(best_guess, nugget_to_displayed_items, WHITE, 15)


def highlight_selected_nugget(nugget, currently_highlighted_nugget, best_guess, nugget_to_displayed_items):
    (highlight_color, highlight_size), (reset_color, reset_size) = determine_update_values(
        currently_highlighted_nugget, nugget, best_guess)

    highlight_nugget(nugget, nugget_to_displayed_items, highlight_color, highlight_size)

    if currently_highlighted_nugget is not None:
        currently_highlighted_scatter, _ = nugget_to_displayed_items[currently_highlighted_nugget]
        currently_highlighted_scatter.setData(color=reset_color, size=reset_size)


def highlight_nugget(nugget_to_highlight, nugget_to_displayed_items, new_color, new_size):
    scatter_to_highlight, _ = nugget_to_displayed_items[nugget_to_highlight]

    if scatter_to_highlight is None:
        logger.warning("Couldn't find nugget to highlight")
        return

    scatter_to_highlight.setData(color=new_color, size=new_size)


def determine_update_values(previously_selected_nugget, newly_selected_nugget, best_guess) -> (
        (int, Color), (int, Color)):
    highlight_color = BLUE
    highlight_size = 15 if newly_selected_nugget == best_guess else 10

    reset_color = WHITE if previously_selected_nugget == best_guess else GREEN
    reset_size = 15 if previously_selected_nugget == best_guess else 3

    return (highlight_color, highlight_size), (reset_color, reset_size)


class EmbeddingVisualizerWindow(QMainWindow):
    def __init__(self, attribute, nuggets, currently_highlighted_nugget, best_guess):
        super(EmbeddingVisualizerWindow, self).__init__()

        self.nugget_to_displayed_items = {}
        self.currently_highlighted_nugget = None
        self.best_guess = best_guess

        self.setWindowTitle("3D Grid Visualizer")
        self.setGeometry(100, 100, WINDOW_WIDTH, WINDOW_HEIGHT)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.fullscreen_layout = QVBoxLayout()
        central_widget.setLayout(self.fullscreen_layout)

        self.fullscreen_gl_widget = GLViewWidget()
        self.fullscreen_layout.addWidget(self.fullscreen_gl_widget)

        add_grids(self.fullscreen_gl_widget)
        self.copy_state(attribute, nuggets)

        highlight_best_guess(best_guess, currently_highlighted_nugget, self.nugget_to_displayed_items)
        self.highlight_selected_nugget(currently_highlighted_nugget)

    def closeEvent(self, event):
        event.accept()

    def copy_state(self, attribute, nuggets):
        update_grid(self.fullscreen_gl_widget,
                    [attribute[PCADimensionReducedLabelEmbeddingSignal]],
                    RED,
                    attribute.name)

        for nugget in nuggets:
            nugget_embedding: np.ndarray = np.array([nugget[PCADimensionReducedTextEmbeddingSignal]])
            scatter, annotation = update_grid(self.fullscreen_gl_widget, nugget_embedding, GREEN,
                                              build_annotation_text(nugget))
            self.nugget_to_displayed_items[nugget] = (scatter, annotation)

    def highlight_selected_nugget(self, nugget):
        highlight_selected_nugget(nugget, self.currently_highlighted_nugget, self.best_guess,
                                  self.nugget_to_displayed_items)

        self.currently_highlighted_nugget = nugget

    def display_other_best_guesses(self, other_best_guesses):
        for other_best_guess in other_best_guesses:
            add_other_best_guess(self.fullscreen_gl_widget, other_best_guess, self.nugget_to_displayed_items)

    def remove_other_best_guesses(self, other_best_guesses):
        remove_nuggets_from_widget(other_best_guesses, self.nugget_to_displayed_items, self.fullscreen_gl_widget)


class EmbeddingVisualizerWidget(QWidget):
    def __init__(self):
        super(EmbeddingVisualizerWidget, self).__init__()

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)

        self.gl_widget = GLViewWidget()
        self.gl_widget.setMinimumHeight(300)  # Set the initial height of the grid to 200
        self.layout.addWidget(self.gl_widget)

        self.best_guesses_widget = QWidget()
        self.best_guesses_widget_layout = QHBoxLayout(self.best_guesses_widget)
        self.best_guesses_widget_layout.setContentsMargins(0, 0, 0, 0)
        self.best_guesses_widget_layout.setSpacing(0)
        self.fullscreen_button = QPushButton("Show 3D Grid in windowed fullscreen mode")
        self.fullscreen_button.clicked.connect(self._show_embedding_visualizer_window)
        self.best_guesses_widget_layout.addWidget(self.fullscreen_button)
        self.show_other_best_guesses_button = QPushButton("Show best guesses from other documents")
        self.show_other_best_guesses_button.clicked.connect(self._display_other_best_guesses)
        self.best_guesses_widget_layout.addWidget(self.show_other_best_guesses_button)
        self.remove_other_best_guesses_button = QPushButton("Stop showing best guesses from other documents")
        self.remove_other_best_guesses_button.setEnabled(False)
        self.remove_other_best_guesses_button.clicked.connect(self._remove_other_best_guesses)
        self.best_guesses_widget_layout.addWidget(self.remove_other_best_guesses_button)
        self.layout.addWidget(self.best_guesses_widget)

        add_grids(self.gl_widget)

        self.fullscreen_window = None
        self.attribute = None
        self.nugget_to_displayed_items = {}
        self.currently_highlighted_nugget = None
        self.best_guess = None
        self.other_best_guesses = None

    def _show_embedding_visualizer_window(self):
        if self.fullscreen_window is None:
            self.fullscreen_window = EmbeddingVisualizerWindow(attribute=self.attribute,
                                                               nuggets=self.nugget_to_displayed_items.keys(),
                                                               currently_highlighted_nugget=self.currently_highlighted_nugget,
                                                               best_guess=self.best_guess)
        self.fullscreen_window.show()

    def return_from_embedding_visualizer_window(self):
        self.fullscreen_window.close()
        self.fullscreen_window = None

    def display_attribute_embedding(self, attribute):
        attribute_embedding = np.array([attribute[PCADimensionReducedLabelEmbeddingSignal]])
        update_grid(self.gl_widget, attribute_embedding, RED, attribute.name)
        self.attribute = attribute  # save for later use

    def display_nugget_embedding(self, nuggets):
        for nugget in nuggets:
            self._add_nugget_embedding(nugget)

    def _display_other_best_guesses(self):
        for other_best_guess in self.other_best_guesses:
            add_other_best_guess(self.gl_widget, other_best_guess, self.nugget_to_displayed_items)

        self.show_other_best_guesses_button.setEnabled(False)
        self.remove_other_best_guesses_button.setEnabled(True)

        if self.fullscreen_window is not None:
            self.fullscreen_window.display_other_best_guesses(self.other_best_guesses)

    def _remove_other_best_guesses(self):
        remove_nuggets_from_widget(self.other_best_guesses, self.nugget_to_displayed_items, self.gl_widget)

        self.show_other_best_guesses_button.setEnabled(True)
        self.remove_other_best_guesses_button.setEnabled(False)

        if self.fullscreen_window is not None:
            self.fullscreen_window.remove_other_best_guesses(self.other_best_guesses)

    def update_other_best_guesses(self, other_best_guesses):
        self.other_best_guesses = other_best_guesses

    def _add_nugget_embedding(self, nugget):
        nugget_embedding: np.ndarray = np.array([nugget[PCADimensionReducedTextEmbeddingSignal]])
        scatter, annotation = update_grid(self.gl_widget, nugget_embedding, GREEN, build_annotation_text(nugget))
        self.nugget_to_displayed_items[nugget] = (scatter, annotation)

    def highlight_selected_nugget(self, nugget):
        highlight_selected_nugget(nugget, self.currently_highlighted_nugget, self.best_guess,
                                  self.nugget_to_displayed_items)

        if self.fullscreen_window is not None:
            self.fullscreen_window.highlight_selected_nugget(nugget)

        self.currently_highlighted_nugget = nugget

    def highlight_best_guess(self, nugget):
        self.best_guess = nugget

        highlight_best_guess(nugget, self.currently_highlighted_nugget, self.nugget_to_displayed_items)

    def reset(self):
        for scatter, annotation in self.nugget_to_displayed_items.values():
            self.gl_widget.removeItem(scatter)
            self.gl_widget.removeItem(annotation)

        self.fullscreen_window = None
        self.nugget_to_displayed_items = {}
        self.currently_highlighted_nugget = None
        self.best_guess = None
        self.other_best_guesses = None

        self.show_other_best_guesses_button.setEnabled(True)
        self.remove_other_best_guesses_button.setEnabled(False)


class BarChartVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super(BarChartVisualizerWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("Show Bar Chart with cosine values")
        self.layout.addWidget(self.button)
        self.data = []
        self.button.clicked.connect(self.show_bar_chart)
        self.window = None

    def append_data(self, data_tuple):
        self.data.append(data_tuple)

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
        ax.set_ylabel('Cosine Similarity', fontsize=15)
        ax.set_xlabel('Information Nuggets', fontsize=15)
        fig.subplots_adjust(left=0.115, right=0.920, top=0.945, bottom=0.065)
        for idx, rect in enumerate(self.bar):
            height = rect.get_height()
            ax.text(
                rect.get_x() + rect.get_width() / 2,
                height/2,
                f'{texts[idx]}',
                ha='center',
                va='center',
                rotation=90,  # Rotate text by 90 degrees
                fontsize=12,
                color='white'# fontcolors[idx]# Optional: Adjust font size
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

    def on_pick(self, event):
        if isinstance(event.artist, Rectangle):
            patch = event.artist
            index = self.bar.get_children().index(patch)
            text = f"Information Nugget: \n{self.texts[index]} \n\n Value: {self.distances[index]}"
            self.annotation.set_text(text)
            annotation_x = patch.get_x() + patch.get_width() / 2
            annotation_y = patch.get_height() / 2
            self.annotation.xy = (annotation_x, annotation_y)
            self.annotation.set_visible(True)
            self.bar_chart_canvas.draw_idle()

    def clear_data(self):
        self.data = []
        self.bar = None


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

    def append_data(self, data_tuple):
        self.data.append(data_tuple)

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
