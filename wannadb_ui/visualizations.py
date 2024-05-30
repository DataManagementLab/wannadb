import pyqtgraph as pg
import pyqtgraph.opengl as gl
import numpy as np
from pyqtgraph.opengl import GLViewWidget


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

