from collections import OrderedDict

import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QPushButton
from matplotlib import pyplot as plt
from pyqtgraph.opengl import GLViewWidget
import sys
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas



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
