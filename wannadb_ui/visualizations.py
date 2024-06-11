from collections import OrderedDict

import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton, QMainWindow, QLabel, QSizePolicy
from matplotlib import pyplot as plt
from pyqtgraph.opengl import GLViewWidget
import sys
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar

class EmbeddingVisualizerWidget(GLViewWidget):

    def __init__(self):
        super(EmbeddingVisualizerWidget, self).__init__()

        grid = gl.GLGridItem()
        self.addItem(grid)

        pts = [0, 0, 0]

        scatter = gl.GLScatterPlotItem(pos=np.array(pts),
            color=pg.glColor((0, 6.5)),
            size=3,
            pxMode=True)
        self.addItem(scatter)


class BarChartVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super(BarChartVisualizerWidget, self).__init__(parent)
        self.setFixedHeight(200)

        self.layout = QVBoxLayout(self)
        self.button = QPushButton("Show Bar Chart with cosine values")
        self.layout.addWidget(self.button)

        self.data = {}  # Initialize data as an empty dictionary
        self.button.clicked.connect(self.show_bar_chart)

    def append_data(self, data_tuple):
        self.data[data_tuple[0]] = data_tuple[1]

    def show_bar_chart(self):
        self.data = OrderedDict(sorted(self.data.items(), key=lambda x: x[1]))
        self.plot_bar_chart(self.data)

    def plot_bar_chart(self, data):
        fig = plt.Figure()
        ax = fig.add_subplot(111)
        bars = ax.bar(data.keys(), data.values())

        for bar, nugget_text in zip(bars, data.keys()):
            ax.text(bar.get_x() + bar.get_width() / 2, bar.get_height() / 2, nugget_text,
                    ha='center', va='center', rotation=90, fontsize=bar.get_width(), color='white')

        ax.tick_params(axis='x', which='both', bottom=False, top=False, labelbottom=True)

        for label in ax.get_xticklabels():
            label.set_visible(False)
        fig.tight_layout()

        self.canvas = FigureCanvas(fig)
        self.window = QWidget()
        self.window.setWindowTitle("Bar Chart")
        self.window.setGeometry(100, 100, 800, 600)

        layout = QVBoxLayout()
        layout.addWidget(self.canvas)
        self.window.setLayout(layout)
        self.window.show()


class ScatterPlotVisualizerWidget(QWidget):
    def __init__(self, parent=None):
        super(ScatterPlotVisualizerWidget, self).__init__(parent)
        self.layout = QVBoxLayout(self)
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
        ax.set_xlim(min(rounded_distances) - 0.05, max(rounded_distances) + 0.05)  # Adjust x-axis limits for better visibility
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
