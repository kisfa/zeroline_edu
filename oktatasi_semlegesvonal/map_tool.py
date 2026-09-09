# -*- coding: utf-8 -*-
from math import atan2

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.gui import QgsMapTool
from qgis.gui import QgsMapToolEmitPoint


class InteractiveTraceTool(QgsMapTool):
    """Select the candidate whose bearing is nearest to the mouse bearing."""
    activeChanged = pyqtSignal(int)
    candidateAccepted = pyqtSignal(int)
    undoRequested = pyqtSignal()

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.origin = None
        self.candidates = []
        self.active_index = -1
        self.setCursor(Qt.CrossCursor)

    def set_candidates(self, origin, candidates):
        self.origin, self.candidates = origin, list(candidates)
        self._set_active(-1)

    def _set_active(self, index):
        if self.active_index != index:
            self.active_index = index
            self.activeChanged.emit(index)

    def canvasMoveEvent(self, event):
        if self.origin is None or not self.candidates:
            return
        point = self.toMapCoordinates(event.pos())
        mouse_angle = atan2(point.y() - self.origin.y(), point.x() - self.origin.x())
        def delta(candidate):
            angle = atan2(candidate.y() - self.origin.y(), candidate.x() - self.origin.x())
            return abs((angle - mouse_angle + 3.141592653589793) % 6.283185307179586 - 3.141592653589793)
        self._set_active(min(range(len(self.candidates)), key=lambda i: delta(self.candidates[i])))

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.undoRequested.emit()
        elif event.button() == Qt.LeftButton and self.active_index >= 0:
            self.candidateAccepted.emit(self.active_index)


class PointCaptureTool(QgsMapToolEmitPoint):
    pointCaptured = pyqtSignal(object)

    def canvasReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.pointCaptured.emit(self.toMapCoordinates(event.pos()))
