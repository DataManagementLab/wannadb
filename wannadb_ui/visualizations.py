import copy
from collections import OrderedDict

import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QMainWindow, QLabel
from matplotlib import pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from matplotlib.patches import Rectangle
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from pyqtgraph.opengl import GLViewWidget, GLScatterPlotItem

RED = pg.mkColor('red')
BLUE = pg.mkColor('blue')
GREEN = pg.mkColor('green')


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


def update_grid(gl_widget, points_to_display, color):
    scatter = GLScatterPlotItem(pos=points_to_display, color=color, size=3, pxMode=True)
    print(f"type of points_to_display: {type(points_to_display)}")
    gl_widget.addItem(scatter)



class FullscreenWindow(QMainWindow):
    def __init__(self, attribute_embeddings, nugget_embeddings):
        super(FullscreenWindow, self).__init__()

        self.setWindowTitle("3D Grid Visualizer")
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.fullscreen_layout = QVBoxLayout()
        central_widget.setLayout(self.fullscreen_layout)

        self.fullscreen_gl_widget = GLViewWidget()
        self.fullscreen_layout.addWidget(self.fullscreen_gl_widget)

        add_grids(self.fullscreen_gl_widget)
        self.copy_state(attribute_embeddings, nugget_embeddings, self.fullscreen_gl_widget)

    def closeEvent(self, event):
        self.parent().return_from_fullscreen()
        event.accept()

    def copy_state(self, attribute_embeddings, nugget_embeddings, target_gl_widget):
        update_grid(target_gl_widget, attribute_embeddings, RED)
        update_grid(target_gl_widget, nugget_embeddings, GREEN)

class EmbeddingVisualizerWidget(QWidget):
    def __init__(self):
        super(EmbeddingVisualizerWidget, self).__init__()

        self.layout = QVBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(self.layout)

        self.gl_widget = GLViewWidget()
        self.gl_widget.setMinimumHeight(200)  # Set the initial height of the grid to 200
        self.layout.addWidget(self.gl_widget)

        self.fullscreen_button = QPushButton("Show 3D Grid in windowed fullscreen mode")
        self.fullscreen_button.clicked.connect(self._show_fullscreen)
        self.layout.addWidget(self.fullscreen_button)

        add_grids(self.gl_widget)

        self.fullscreen_window = None
        self.attribute_embeddings = None
        self.nugget_embeddings = None

    def _show_fullscreen(self):
        if self.fullscreen_window is None:
            self.fullscreen_window = FullscreenWindow(attribute_embeddings=self.attribute_embeddings, nugget_embeddings=self.nugget_embeddings)
        self.fullscreen_window.show()

    def return_from_fullscreen(self):
        self.fullscreen_window.close()
        self.fullscreen_window = None

    def display_attribute_embedding(self, attribute_embeddings):
        update_grid(self.gl_widget, attribute_embeddings, RED)
        self.attribute_embeddings = attribute_embeddings  # save for later use

    def display_nugget_embedding(self, nugget_embeddings):
        update_grid(self.gl_widget, nugget_embeddings, GREEN)
        self.nugget_embeddings = nugget_embeddings



class BarChartVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super(BarChartVisualizerWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.button = QPushButton("Show Bar Chart with cosine values")
        self.layout.addWidget(self.button)
        self.data = []  # Initialize data as an empty dictionary
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
        fig.tight_layout()

        self.bar_chart_canvas = FigureCanvas(fig)
        self.window = QMainWindow()
        self.window.setWindowTitle("Bar Chart")
        self.window.setGeometry(100, 100, 800, 600)
        self.window.setCentralWidget(self.bar_chart_canvas)

        self.bar_chart_toolbar = NavigationToolbar(self.bar_chart_canvas, self.window)
        print(f"BAR CHART TOOLBAR TYPE: {type(self.bar_chart_toolbar)}")
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

        # todo after value is confirmed or value not in document, reinitialize data
        # self.window.destroyed.connect(self.cleanup)

    def on_pick(self, event):
        if isinstance(event.artist, Rectangle):
            patch = event.artist
            index = self.bar.get_children().index(patch)
            text = f"Infomation Nugget: \n{self.texts[index]} \n\n Value: {self.distances[index]}"
            self.annotation.set_text(text)
            print(patch.get_x())
            print(patch.get_width())
            # if patch.get_x() + patch.get_width() > 20:
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
        colors = plt.cm.jet(np.linspace(0, 1, num_points))

        # Plot the points
        scatter = ax.scatter(rounded_distances, y, c=colors, alpha=0.75, picker=True)  # Enable picking

        ax.set_xlabel("Cosine Distance")
        ax.set_xlim(min(rounded_distances) - 0.05,
                    max(rounded_distances) + 0.05)  # Adjust x-axis limits for better visibility
        ax.set_yticks([])  # Remove y-axis labels to avoid confusion
        fig.tight_layout()

        # Create canvas
        self.scatter_plot_canvas = FigureCanvas(fig)

        # Create a new window for the plot
        self.window = QMainWindow()
        self.window.setWindowTitle("Scatter Plot")
        self.window.setGeometry(100, 100, 800, 600)

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
        text = f"Distance: {self.distances[ind]:.3f}\nText: {self.texts[ind]}"
        self.annotation.set_text(text)
        self.annotation.set_visible(True)
        self.scatter_plot_canvas.draw_idle()