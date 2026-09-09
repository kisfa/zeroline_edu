# -*- coding: utf-8 -*-

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qgis.core import QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox


class SemlegesvonalDockWidget(QDockWidget):
    captureRequested = pyqtSignal()
    runRequested = pyqtSignal()
    saveRequested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Semlegesvonal", parent)
        self.setObjectName("SemlegesvonalDockWidget")

        container = QWidget(self)
        layout = QVBoxLayout(container)

        self.raster_combo = QgsMapLayerComboBox(container)
        self.raster_combo.setFilters(QgsMapLayerProxyModel.RasterLayer)

        self.auto_slope = QCheckBox("Cel-lejtes szamitasa A-B magassagkulonbsegbol")
        self.auto_slope.setChecked(True)

        self.target_slope = QDoubleSpinBox(container)
        self.target_slope.setRange(-100.0, 100.0)
        self.target_slope.setDecimals(2)
        self.target_slope.setSuffix(" %")
        self.target_slope.setValue(6.0)

        self.arrival_radius = QDoubleSpinBox(container)
        self.arrival_radius.setRange(0.1, 10000.0)
        self.arrival_radius.setDecimals(1)
        self.arrival_radius.setSuffix(" m")
        self.arrival_radius.setValue(20.0)

        self.step_length = QDoubleSpinBox(container)
        self.step_length.setRange(0.1, 1000.0)
        self.step_length.setDecimals(1)
        self.step_length.setSuffix(" m")
        self.step_length.setValue(10.0)

        self.search_angle = QDoubleSpinBox(container)
        self.search_angle.setRange(10.0, 360.0)
        self.search_angle.setDecimals(0)
        self.search_angle.setSuffix(" fok")
        self.search_angle.setValue(160.0)

        self.max_detour = QDoubleSpinBox(container)
        self.max_detour.setRange(1.0, 20.0)
        self.max_detour.setDecimals(1)
        self.max_detour.setValue(4.0)

        self.max_expansions = QSpinBox(container)
        self.max_expansions.setRange(1000, 5000000)
        self.max_expansions.setSingleStep(10000)
        self.max_expansions.setValue(250000)

        form = QFormLayout()
        form.addRow("DEM raszter", self.raster_combo)
        form.addRow("", self.auto_slope)
        form.addRow("Cel-lejtes", self.target_slope)
        form.addRow("Erkezesi sugar", self.arrival_radius)
        form.addRow("Lepeshossz", self.step_length)
        form.addRow("Keresszog", self.search_angle)
        form.addRow("Max. kerulo szorzo", self.max_detour)
        form.addRow("Max. vizsgalt csomopont", self.max_expansions)
        layout.addLayout(form)

        self.capture_button = QPushButton("Ket pont kijelolese")
        self.run_button = QPushButton("Semlegesvonal keresese")
        self.save_button = QPushButton("SHP mentes")
        self.save_button.setEnabled(False)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.capture_button)
        button_layout.addWidget(self.run_button)
        layout.addLayout(button_layout)
        layout.addWidget(self.save_button)

        self.status_label = QLabel("Valassz DEM-et, majd jelolj ki ket pontot.")
        self.status_label.setWordWrap(True)
        self.status_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        layout.addWidget(self.status_label)

        self.capture_button.clicked.connect(self.captureRequested.emit)
        self.run_button.clicked.connect(self.runRequested.emit)
        self.save_button.clicked.connect(self._select_save_path)
        self.auto_slope.toggled.connect(self.target_slope.setDisabled)
        self.target_slope.setDisabled(self.auto_slope.isChecked())

        self.setWidget(container)

    def raster_layer(self):
        return self.raster_combo.currentLayer()

    def parameters(self):
        return {
            "auto_slope": self.auto_slope.isChecked(),
            "target_slope_percent": self.target_slope.value(),
            "arrival_radius_m": self.arrival_radius.value(),
            "step_length_m": self.step_length.value(),
            "search_angle_degrees": self.search_angle.value(),
            "max_detour_factor": self.max_detour.value(),
            "turn_penalty": 0.0,
            "max_expansions": self.max_expansions.value(),
        }

    def set_status(self, message):
        self.status_label.setText(message)

    def set_has_result(self, has_result):
        self.save_button.setEnabled(has_result)

    def _select_save_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Semlegesvonal mentese",
            "semlegesvonal.shp",
            "ESRI Shapefile (*.shp)",
        )
        if path:
            self.saveRequested.emit(path)
