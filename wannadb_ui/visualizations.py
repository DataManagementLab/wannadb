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


def get_colors(distances, color_start='red', color_end='blue'):
    cmap = LinearSegmentedColormap.from_list("CustomMap", [color_start, color_end])
    # Normalize the data for color mapping
    norm = plt.Normalize(min(distances), max(distances))
    # Generate the colors based on the data
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


class EmbeddingVisualizerWidget(QWidget):

    def __init__(self):
        super(EmbeddingVisualizerWidget, self).__init__()

        layout = QVBoxLayout()
        self.setLayout(layout)

        self.gl_widget = gl.GLViewWidget()
        layout.addWidget(self.gl_widget)

        add_grids(self.gl_widget)

    def update_grid(self, new_points_to_display):
        scatter = gl.GLScatterPlotItem(pos=np.array(new_points_to_display),
                                       color=pg.glColor((0, 6.5)),
                                       size=3,
                                       pxMode=True)
        self.gl_widget.addItem(scatter)


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
        #self.window.destroyed.connect(self.cleanup)

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

    def cleanup(self):
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

    def append_data(self, data_tuple):
        self.data.append(data_tuple)

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
