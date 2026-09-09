# -*- coding: utf-8 -*-
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (QDockWidget, QWidget, QVBoxLayout, QFormLayout,
    QDoubleSpinBox, QLabel, QPushButton, QHBoxLayout, QFileDialog, QCheckBox, QLineEdit)
from qgis.core import QgsMapLayerProxyModel
from qgis.gui import QgsMapLayerComboBox


class EducationalDock(QDockWidget):
    startRequested = pyqtSignal()
    targetRequested = pyqtSignal()
    beginRequested = pyqtSignal()
    finishRequested = pyqtSignal()
    exportRequested = pyqtSignal(str)
    referenceRequested = pyqtSignal()
    retryRequested = pyqtSignal()
    startCoordinatesEdited = pyqtSignal(str)
    targetCoordinatesEdited = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__("Oktatási semlegesvonal", parent)
        self.setObjectName("EducationalNeutralLineDock")
        host = QWidget(self); layout = QVBoxLayout(host); form = QFormLayout()
        self.raster = QgsMapLayerComboBox(host)
        self.raster.setFilters(QgsMapLayerProxyModel.RasterLayer)
        self.band = QDoubleSpinBox(host); self.band.setRange(1, 99); self.band.setDecimals(0); self.band.setValue(1)
        self.gradient = QDoubleSpinBox(host); self.gradient.setRange(-100, 100); self.gradient.setDecimals(4); self.gradient.setSuffix(" %"); self.gradient.setValue(-6)
        self.step = QDoubleSpinBox(host); self.step.setRange(0.1, 10000); self.step.setDecimals(2); self.step.setSuffix(" m"); self.step.setValue(20)
        self.arrival = QDoubleSpinBox(host); self.arrival.setRange(0.1, 10000); self.arrival.setDecimals(2); self.arrival.setSuffix(" m"); self.arrival.setValue(5)
        self.show_target = QCheckBox("Célpont és érkezési kör használata", host); self.show_target.setChecked(True)
        self.start_xy = QLineEdit(host); self.start_xy.setPlaceholderText("X; Y (projekt CRS)")
        self.target_xy = QLineEdit(host); self.target_xy.setPlaceholderText("X; Y (projekt CRS)")
        self.start_z = QLabel("Z: —", host); self.target_z = QLabel("Z: —", host)
        form.addRow("DEM", self.raster); form.addRow("Rasztersáv", self.band); form.addRow("Előjeles meredekség", self.gradient)
        form.addRow("Lépéshossz", self.step); form.addRow("Célpont tolerancia", self.arrival); form.addRow("", self.show_target)
        form.addRow("Kezdőpont X; Y", self.start_xy); form.addRow("Kezdőpont magassága", self.start_z)
        form.addRow("Célpont X; Y", self.target_xy); form.addRow("Célpont magassága", self.target_z)
        layout.addLayout(form)
        self.start_button = QPushButton("Kezdőpont kijelölése", host)
        self.target_button = QPushButton("Célpont kijelölése", host)
        self.begin_button = QPushButton("Tervezés indítása", host)
        self.finish_button = QPushButton("Tervezés vége", host); self.finish_button.setEnabled(False)
        self.retry_button = QPushButton("Vonal újrapróbálása másik meredekséggel", host); self.retry_button.setEnabled(False)
        self.reference_button = QPushButton("Vonal megtartása referenciaként", host); self.reference_button.setEnabled(False)
        self.export_button = QPushButton("Vonal mentése…", host); self.export_button.setEnabled(False)
        for button in (self.start_button, self.target_button, self.begin_button, self.retry_button, self.finish_button, self.reference_button, self.export_button): layout.addWidget(button)
        self.status = QLabel("Válassz DEM-et, majd jelöld ki a kezdőpontot.", host); self.status.setWordWrap(True); self.status.setAlignment(Qt.AlignLeft | Qt.AlignTop); layout.addWidget(self.status)
        self.warning = QLabel("Nincs tervezési figyelmeztetés.", host)
        self.warning.setWordWrap(True); self.warning.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.warning.setStyleSheet("QLabel { background: #e8f5e9; border: 1px solid #66a66b; padding: 6px; color: #1b5e20; }")
        layout.addWidget(self.warning)
        self.version_label = QLabel("Oktatási semlegesvonal · v1.1.0", host)
        self.version_label.setAlignment(Qt.AlignRight)
        self.version_label.setStyleSheet("QLabel { color: #666; font-size: 9pt; }")
        layout.addWidget(self.version_label)
        self.start_button.clicked.connect(self.startRequested); self.target_button.clicked.connect(self.targetRequested)
        self.begin_button.clicked.connect(self.beginRequested); self.finish_button.clicked.connect(self.finishRequested)
        self.retry_button.clicked.connect(self.retryRequested)
        self.reference_button.clicked.connect(self.referenceRequested); self.export_button.clicked.connect(self._export)
        self.start_xy.editingFinished.connect(lambda: self.startCoordinatesEdited.emit(self.start_xy.text()))
        self.target_xy.editingFinished.connect(lambda: self.targetCoordinatesEdited.emit(self.target_xy.text()))
        self.setWidget(host)

    def values(self):
        return dict(raster=self.raster.currentLayer(), band=int(self.band.value()), gradient=self.gradient.value(), step=self.step.value(), arrival=self.arrival.value(), use_target=self.show_target.isChecked())

    def set_status(self, text): self.status.setText(text)
    def set_start_point(self, point, z):
        self.start_xy.setText(f"{point.x():.3f}; {point.y():.3f}"); self.start_z.setText(f"Z: {z:.3f} m")
    def set_target_point(self, point, z):
        self.target_xy.setText(f"{point.x():.3f}; {point.y():.3f}"); self.target_z.setText(f"Z: {z:.3f} m")
    def clear_points(self):
        self.start_xy.clear(); self.target_xy.clear(); self.start_z.setText("Z: —"); self.target_z.setText("Z: —")
    def set_warnings(self, warnings):
        if warnings:
            self.warning.setText("FIGYELMEZTETÉSEK – a lezárás előtt ellenőrizd:\n• " + "\n• ".join(warnings))
            self.warning.setStyleSheet("QLabel { background: #fff3cd; border: 2px solid #d68a00; padding: 6px; color: #6a3900; font-weight: bold; }")
        else:
            self.warning.setText("Nincs tervezési figyelmeztetés.")
            self.warning.setStyleSheet("QLabel { background: #e8f5e9; border: 1px solid #66a66b; padding: 6px; color: #1b5e20; }")
    def set_running(self, running):
        self.finish_button.setEnabled(running); self.retry_button.setEnabled(running); self.export_button.setEnabled(not running and self.export_button.isEnabled())
    def set_finished(self, ready):
        self.finish_button.setEnabled(False); self.retry_button.setEnabled(False); self.export_button.setEnabled(ready); self.reference_button.setEnabled(ready)
    def _export(self):
        path, _ = QFileDialog.getSaveFileName(self, "Semlegesvonal mentése", "oktatasi_semlegesvonal.gpkg", "GeoPackage (*.gpkg);;ESRI Shapefile (*.shp)")
        if path: self.exportRequested.emit(path)
