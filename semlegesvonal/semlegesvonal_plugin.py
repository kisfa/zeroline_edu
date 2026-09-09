# -*- coding: utf-8 -*-

from pathlib import Path

from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    QgsFeature,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsProject,
    QgsVectorFileWriter,
    QgsVectorLayer,
)

from .dock_widget import SemlegesvonalDockWidget
from .map_tool import TwoPointMapTool
from .neutral_line_finder import (
    SLOPE_TOLERANCE_PERCENT,
    NeutralLineError,
    NeutralLineFinder,
    SearchParameters,
)


class SemlegesvonalPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.action = None
        self.dock = None
        self.map_tool = None
        self.previous_map_tool = None
        self.start_point = None
        self.end_point = None
        self.result_layer = None

    def initGui(self):
        self.action = QAction("Semlegesvonal", self.iface.mainWindow())
        self.action.triggered.connect(self.show_dock)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("Semlegesvonal", self.action)

    def unload(self):
        if self.map_tool is not None and self.canvas.mapTool() == self.map_tool:
            self.canvas.setMapTool(self.previous_map_tool)
        if self.dock is not None:
            self.iface.removeDockWidget(self.dock)
        if self.action is not None:
            self.iface.removePluginMenu("Semlegesvonal", self.action)
            self.iface.removeToolBarIcon(self.action)

    def show_dock(self):
        if self.dock is None:
            self.dock = SemlegesvonalDockWidget(self.iface.mainWindow())
            self.dock.captureRequested.connect(self.activate_capture)
            self.dock.runRequested.connect(self.run_search)
            self.dock.saveRequested.connect(self.save_result)
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show()
        self.dock.raise_()

    def activate_capture(self):
        self.show_dock()
        self.start_point = None
        self.end_point = None
        self.previous_map_tool = self.canvas.mapTool()
        self.map_tool = TwoPointMapTool(self.canvas)
        self.map_tool.pointCaptured.connect(self._point_captured)
        self.map_tool.pointsCaptured.connect(self._points_captured)
        self.canvas.setMapTool(self.map_tool)
        self.dock.set_status("Kattints a kezdopontra, majd a celpontra.")

    def _point_captured(self, point, count):
        label = "kezdopont" if count == 1 else "celpont"
        self.dock.set_status(
            f"{count}. pont rogzitve ({label}): {point.x():.2f}, {point.y():.2f}"
        )

    def _points_captured(self, start_point, end_point):
        self.start_point = start_point
        self.end_point = end_point
        if self.previous_map_tool is not None:
            self.canvas.setMapTool(self.previous_map_tool)
        self.dock.set_status("Ket pont rogzitve. Indithato a semlegesvonal keresese.")
        self.run_search()

    def run_search(self):
        self.show_dock()
        raster = self.dock.raster_layer()
        if raster is None:
            self._warn("Valassz ki egy DEM rasztert.")
            return
        if self.start_point is None or self.end_point is None:
            self._warn("Elobb jelolj ki ket pontot a terkepen.")
            return

        params = self._search_parameters(raster)
        self.dock.set_status("Kereses folyamatban...")

        try:
            finder = NeutralLineFinder(raster, self.canvas.mapSettings().destinationCrs())
            result = finder.find(self.start_point, self.end_point, params)
        except NeutralLineError as exc:
            self.dock.set_has_result(False)
            self.dock.set_status(str(exc))
            return
        except Exception as exc:
            self.dock.set_has_result(False)
            self.dock.set_status(f"Varatlan hiba: {exc}")
            raise

        self.result_layer = self._create_result_layer(result, params, raster)
        QgsProject.instance().addMapLayer(self.result_layer)
        self.dock.set_has_result(True)
        self.dock.set_status(
            "Semlegesvonal kesz. "
            f"Hossz: {result.length:.1f} m, "
            f"erkezesi tavolsag: {result.arrival_distance_m:.1f} m, "
            f"atlag lejtes: {result.mean_slope_percent:.2f} %, "
            f"lejtesszures: +/-{SLOPE_TOLERANCE_PERCENT:.1f} %, "
            f"vizsgalt csomopont: {result.expanded_nodes}."
        )

    def save_result(self, path):
        if self.result_layer is None:
            self._warn("Nincs mentheto eredmeny.")
            return

        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "ESRI Shapefile"
        options.fileEncoding = "UTF-8"
        writer_result = QgsVectorFileWriter.writeAsVectorFormatV3(
            self.result_layer,
            path,
            QgsProject.instance().transformContext(),
            options,
        )
        error = writer_result[0]
        message = writer_result[1] if len(writer_result) > 1 else ""
        if error == QgsVectorFileWriter.NoError:
            self.dock.set_status(f"SHP elmentve: {path}")
        else:
            self._warn(f"Nem sikerult menteni: {message}")

    def _search_parameters(self, raster):
        values = self.dock.parameters()
        target_slope = values["target_slope_percent"]
        if values["auto_slope"]:
            target_slope = self._direct_slope_percent(raster)

        return SearchParameters(
            target_slope_percent=target_slope,
            arrival_radius_m=values["arrival_radius_m"],
            step_length_m=values["step_length_m"],
            search_angle_degrees=values["search_angle_degrees"],
            max_expansions=values["max_expansions"],
            turn_penalty=values["turn_penalty"],
            max_detour_factor=values["max_detour_factor"],
        )

    def _direct_slope_percent(self, raster):
        finder = NeutralLineFinder(raster, self.canvas.mapSettings().destinationCrs())
        sampler = finder.sampler
        start = sampler.to_raster_point(self.start_point)
        end = sampler.to_raster_point(self.end_point)
        start_z = sampler.elevation_at(start)
        end_z = sampler.elevation_at(end)
        distance = sampler.point_distance(start, end)
        if distance == 0:
            return 0.0
        return ((end_z - start_z) / distance) * 100.0

    def _create_result_layer(self, result, params, raster):
        crs_authid = self.canvas.mapSettings().destinationCrs().authid()
        layer = QgsVectorLayer(f"LineString?crs={crs_authid}", "semlegesvonal", "memory")
        provider = layer.dataProvider()

        fields = QgsFields()
        fields.append(QgsField("target_pct", QVariant.Double))
        fields.append(QgsField("slope_tol", QVariant.Double))
        fields.append(QgsField("arriv_m", QVariant.Double))
        fields.append(QgsField("step_m", QVariant.Double))
        fields.append(QgsField("length_m", QVariant.Double))
        fields.append(QgsField("dist_m", QVariant.Double))
        fields.append(QgsField("mean_pct", QVariant.Double))
        fields.append(QgsField("min_pct", QVariant.Double))
        fields.append(QgsField("max_pct", QVariant.Double))
        fields.append(QgsField("dem", QVariant.String))
        provider.addAttributes(fields)
        layer.updateFields()

        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromPolylineXY(result.points))
        feature.setAttributes(
            [
                params.target_slope_percent,
                SLOPE_TOLERANCE_PERCENT,
                params.arrival_radius_m,
                params.step_length_m,
                result.length,
                result.arrival_distance_m,
                result.mean_slope_percent,
                result.min_slope_percent,
                result.max_slope_percent,
                Path(raster.source()).name,
            ]
        )
        provider.addFeature(feature)
        layer.updateExtents()
        return layer

    def _warn(self, message):
        if self.dock is not None:
            self.dock.set_status(message)
        QMessageBox.warning(self.iface.mainWindow(), "Semlegesvonal", message)
