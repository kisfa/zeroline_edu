# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import pyqtSignal
from qgis.gui import QgsMapToolEmitPoint


class TwoPointMapTool(QgsMapToolEmitPoint):
    pointsCaptured = pyqtSignal(object, object)
    pointCaptured = pyqtSignal(object, int)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.points = []

    def reset(self):
        self.points = []

    def canvasReleaseEvent(self, event):
        point = self.toMapCoordinates(event.pos())
        self.points.append(point)
        self.pointCaptured.emit(point, len(self.points))

        if len(self.points) == 2:
            self.pointsCaptured.emit(self.points[0], self.points[1])
            self.reset()
