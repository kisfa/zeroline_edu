# -*- coding: utf-8 -*-
from math import acos, degrees

from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtGui import QColor
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (QgsCoordinateTransform, QgsFeature, QgsField, QgsGeometry,
    QgsLineSymbol, QgsPointXY, QgsProject, QgsUnitTypes, QgsVectorFileWriter, QgsVectorLayer, QgsWkbTypes)
from qgis.gui import QgsRubberBand, QgsVertexMarker

from .dialog import EducationalDock
from .map_tool import InteractiveTraceTool, PointCaptureTool
from .roots import find_circle_roots
from .terrain import BSplineDemSampler, TerrainError


class EducationalNeutralLinePlugin:
    def __init__(self, iface):
        self.iface, self.canvas = iface, iface.mapCanvas()
        self.action = self.dock = self.trace_tool = self.capture_tool = None
        self.previous_tool = None; self.sampler = self.transform = None
        self.points = []                 # [(QgsPointXY in project CRS, z), ...]
        self.segment_warnings = []       # one list for every accepted segment
        self.target = None               # (QgsPointXY, z)
        self.candidates = []             # [(QgsPointXY, z, heading), ...]
        self.path_band = self.target_band = None; self.candidate_bands = []
        self.trial_bands = []
        self.start_marker = self.target_marker = None
        self.result_layer = None; self.running = False

    def initGui(self):
        self.action = QAction("Oktatási semlegesvonal", self.iface.mainWindow())
        self.action.triggered.connect(self.show_dock)
        self.iface.addToolBarIcon(self.action); self.iface.addPluginToMenu("Oktatási semlegesvonal", self.action)

    def unload(self):
        self._clear_visuals()
        if self.sampler: self.sampler.close()
        if self.dock: self.iface.removeDockWidget(self.dock)
        if self.action:
            self.iface.removeToolBarIcon(self.action); self.iface.removePluginMenu("Oktatási semlegesvonal", self.action)

    def show_dock(self):
        if self.dock is None:
            self.dock = EducationalDock(self.iface.mainWindow())
            self.dock.startRequested.connect(lambda: self._capture("start"))
            self.dock.targetRequested.connect(lambda: self._capture("target"))
            self.dock.beginRequested.connect(self.begin)
            self.dock.finishRequested.connect(self.finish)
            self.dock.exportRequested.connect(self.export)
            self.dock.referenceRequested.connect(self.keep_reference)
            self.dock.retryRequested.connect(self.retry)
            self.dock.startCoordinatesEdited.connect(lambda text: self._coordinates_edited("start", text))
            self.dock.targetCoordinatesEdited.connect(lambda text: self._coordinates_edited("target", text))
            self.iface.addDockWidget(Qt.RightDockWidgetArea, self.dock)
        self.dock.show(); self.dock.raise_()

    def _metric_project(self):
        crs = self.canvas.mapSettings().destinationCrs()
        if not crs.isValid() or crs.isGeographic() or crs.mapUnits() != QgsUnitTypes.DistanceMeters:
            raise TerrainError("A projekt CRS-ének vetületi, méter alapú rendszernek kell lennie.")
        return crs

    def _prepare_dem(self):
        values = self.dock.values(); raster = values["raster"]
        if raster is None: raise TerrainError("Válassz ki egy DEM rasztert.")
        project_crs = self._metric_project()
        source = raster.source().split("|")[0]
        if self.sampler: self.sampler.close()
        self.sampler = BSplineDemSampler(source, values["band"])
        self.transform = QgsCoordinateTransform(project_crs, raster.crs(), QgsProject.instance())
        return values

    def _sample_project(self, point):
        dem_point = self.transform.transform(QgsPointXY(point))
        return self.sampler.sample(dem_point.x(), dem_point.y())

    def _capture(self, kind):
        self.show_dock()
        try: self._prepare_dem()
        except TerrainError as exc: return self._warn(str(exc))
        self.previous_tool = self.canvas.mapTool()
        self.capture_tool = PointCaptureTool(self.canvas)
        self.capture_tool.pointCaptured.connect(lambda point: self._captured(kind, point))
        self.canvas.setMapTool(self.capture_tool)
        self.dock.set_status("Kattints a {}ra a térképen.".format("kezdőpontra" if kind == "start" else "célpontra"))

    def _captured(self, kind, point):
        z = self._sample_project(point)
        if z is None: return self._warn("A kijelölt pont alatt nincs B-spline-nal mintázható DEM-érték.")
        if kind == "start":
            self._set_start(QgsPointXY(point), z)
            self.dock.set_warnings([])
            self.dock.set_status(f"Kezdőpont: z={z:.3f} m. Állítsd be a meredekséget, majd indítsd a tervezést.")
        else:
            self._set_target(QgsPointXY(point), z)
            self.dock.set_status(f"Célpont: z={z:.3f} m.")
        if self.previous_tool: self.canvas.setMapTool(self.previous_tool)

    @staticmethod
    def _parse_coordinates(text):
        parts = [part.strip().replace(",", ".") for part in text.split(";")]
        if len(parts) != 2:
            raise ValueError("Az alak: X; Y")
        return QgsPointXY(float(parts[0]), float(parts[1]))

    def _coordinates_edited(self, kind, text):
        if not text.strip(): return
        try:
            self._prepare_dem(); point = self._parse_coordinates(text); z = self._sample_project(point)
            if z is None: raise TerrainError("A megadott koordinátán nincs B-spline-nal mintázható DEM-érték.")
            if kind == "start": self._set_start(point, z)
            else: self._set_target(point, z)
        except (ValueError, TerrainError) as exc:
            self._warn(str(exc))

    def _set_start(self, point, z):
        self.points = [(QgsPointXY(point), z)]; self.segment_warnings = []; self.result_layer = None
        self._clear_candidate_bands(); self._clear_trial_bands(); self._draw_path(); self._draw_marker("start", point); self.dock.set_start_point(point, z)
        if self.running and self.trace_tool: self._update_candidates("A kezdőpont módosult; a korábbi próbavonal törölve.")

    def _set_target(self, point, z):
        self.target = (QgsPointXY(point), z)
        if self.points:
            self.points = [self.points[0]]; self.segment_warnings = []; self._clear_trial_bands(); self._draw_path(); self.dock.set_warnings([])
        self._draw_marker("target", point); self._draw_target(); self.dock.set_target_point(point, z)
        if self.running and self.trace_tool: self._update_candidates("A célpont módosult; a korábbi próbavonal törölve.")

    def _draw_marker(self, kind, point):
        attribute = "start_marker" if kind == "start" else "target_marker"
        marker = getattr(self, attribute)
        if marker is None:
            marker = QgsVertexMarker(self.canvas); marker.setIconType(QgsVertexMarker.ICON_CROSS)
            marker.setIconSize(14); marker.setPenWidth(3); marker.setColor(QColor(220, 50, 45) if kind == "start" else QColor(100, 60, 210))
            setattr(self, attribute, marker)
        marker.setCenter(QgsPointXY(point)); marker.show()

    def begin(self):
        self.show_dock()
        try: values = self._prepare_dem()
        except TerrainError as exc: return self._warn(str(exc))
        if not self.points: return self._warn("Előbb jelöld ki a kezdőpontot.")
        if values["use_target"] and self.target is None: return self._warn("Kapcsold ki a célpontot, vagy jelöld ki azt.")
        self.running = True; self.result_layer = None
        self.previous_tool = self.canvas.mapTool()
        self.trace_tool = InteractiveTraceTool(self.canvas)
        self.trace_tool.activeChanged.connect(self._draw_candidates)
        self.trace_tool.candidateAccepted.connect(self.accept_candidate)
        self.trace_tool.undoRequested.connect(self.undo)
        self.canvas.setMapTool(self.trace_tool)
        self._update_candidates()

    def _update_candidates(self, context_message=""):
        values = self.dock.values(); point, z = self.points[-1]
        required_z = z + values["step"] * values["gradient"] / 100.0
        raw = find_circle_roots(lambda x, y: self._sample_project(QgsPointXY(x, y)), point.x(), point.y(), values["step"], required_z)
        self.candidates = [(QgsPointXY(x, y), candidate_z, heading) for x, y, candidate_z, heading in raw]
        self.trace_tool.set_candidates(point, [candidate[0] for candidate in self.candidates])
        self._draw_candidates()
        self.dock.set_running(True)
        instruction = f"{len(self.candidates)} pontosan elérhető irány. Mozgasd az egeret, bal kattintás: választás; jobb kattintás: visszavonás."
        self.dock.set_status((context_message + " " if context_message else "") + instruction)

    def _clear_candidate_bands(self):
        for band in self.candidate_bands:
            band.hide()
            self.canvas.scene().removeItem(band)
        self.candidate_bands = []

    def _clear_trial_bands(self):
        for band in self.trial_bands:
            band.hide()
            self.canvas.scene().removeItem(band)
        self.trial_bands = []

    def _freeze_current_trial(self):
        """Keep the preceding slope trial visible until this session ends."""
        if len(self.points) < 2:
            return
        band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
        band.setToGeometry(QgsGeometry.fromPolylineXY([item[0] for item in self.points]), None)
        band.setColor(QColor(110, 110, 110, 180))
        band.setWidth(2)
        band.setLineStyle(Qt.DashLine)
        self.trial_bands.append(band)

    def _draw_candidates(self, active=-999):
        if self.trace_tool is None or not self.points: return
        self._clear_candidate_bands(); origin = self.points[-1][0]
        for index, (point, _z, _heading) in enumerate(self.candidates):
            band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry)
            band.setToGeometry(QgsGeometry.fromPolylineXY([origin, point]), None)
            is_active = index == self.trace_tool.active_index
            band.setColor(QColor(20, 160, 70) if is_active else QColor(70, 170, 230, 110))
            band.setWidth(4 if is_active else 2); self.candidate_bands.append(band)

    def _draw_path(self):
        if self.path_band is None:
            self.path_band = QgsRubberBand(self.canvas, QgsWkbTypes.LineGeometry); self.path_band.setColor(QColor(220, 50, 45)); self.path_band.setWidth(3)
        self.path_band.setToGeometry(QgsGeometry.fromPolylineXY([item[0] for item in self.points]), None)
        self.path_band.setLineStyle(Qt.DashLine)

    def _draw_target(self):
        if self.target_band is None:
            self.target_band = QgsRubberBand(self.canvas, QgsWkbTypes.PolygonGeometry); self.target_band.setColor(QColor(130, 80, 220, 100)); self.target_band.setWidth(2)
        radius = self.dock.values()["arrival"] if self.dock else 5
        self.target_band.setToGeometry(QgsGeometry.fromPointXY(self.target[0]).buffer(radius, 48), None)

    @staticmethod
    def _turn(a, b, c):
        ux, uy = b.x()-a.x(), b.y()-a.y(); vx, vy = c.x()-b.x(), c.y()-b.y()
        n1, n2 = (ux*ux+uy*uy)**.5, (vx*vx+vy*vy)**.5
        if not n1 or not n2: return 0.0
        return degrees(acos(max(-1.0, min(1.0, (ux*vx+uy*vy)/(n1*n2)))))

    def _warnings_for(self, point):
        warnings = []
        if len(self.points) >= 2:
            turn = self._turn(self.points[-2][0], self.points[-1][0], point)
            if turn >= 45: warnings.append(f"éles iránytörés ({turn:.1f}°)")
            if len(self.points) >= 3:
                previous = self._turn(self.points[-3][0], self.points[-2][0], self.points[-1][0])
                if previous >= 30 and turn >= 30: warnings.append("cikcakk vagy szerpentin jelleg")
        new_line = QgsGeometry.fromPolylineXY([self.points[-1][0], point])
        for i in range(len(self.points)-2):
            old_line = QgsGeometry.fromPolylineXY([self.points[i][0], self.points[i+1][0]])
            if new_line.intersects(old_line): warnings.append("önmetsző nyomvonal"); break
        return warnings

    def _all_warnings(self):
        result = []
        for index, warnings in enumerate(self.segment_warnings, start=1):
            for warning in warnings:
                result.append(f"{index}. szakasz: {warning}")
        return result

    def accept_candidate(self, index):
        if index < 0 or index >= len(self.candidates): return
        point, z, _heading = self.candidates[index]; warnings = self._warnings_for(point)
        self.points.append((point, z)); self._draw_path()
        self._clear_candidate_bands()
        message = "Szakasz elfogadva."
        if warnings: message += " Figyelmeztetés: " + "; ".join(warnings) + "."
        values = self.dock.values()
        if values["use_target"] and self.target:
            distance = point.distance(self.target[0]); target_z = self.target[1]
            previous_z = self.points[-2][1]
            crossed = min(previous_z, z) <= target_z <= max(previous_z, z)
            if distance <= values["arrival"]: message += f" A cél elérve ({distance:.2f} m)."
            elif crossed:
                target_warning = f"a cél magassága elérve/átlépve, de a cél még {distance:.1f} m-re van"
                warnings.append(target_warning)
                message += f" A cél magassága elérve/átlépve, de a cél még {distance:.1f} m-re van; ezen a meredekségen nincs értelme tovább lépni."
            else: message += f" Cél távolsága: {distance:.1f} m; eddig {len(self.points)-1} szakasz."
        self.segment_warnings.append(warnings)
        self.dock.set_warnings(self._all_warnings())
        self._update_candidates(message)

    def undo(self):
        if len(self.points) <= 1: return self._warn("A kezdőpont nem törölhető; jelölj ki új kezdőpontot.")
        self.points.pop(); self.segment_warnings.pop(); self._draw_path(); self.dock.set_warnings(self._all_warnings()); self._update_candidates(); self.dock.set_status("Utolsó szakasz visszavonva.")

    def finish(self):
        if not self.running or len(self.points) < 2: return self._warn("Legalább egy szakaszt tervezz meg.")
        warnings = self._all_warnings()
        if self.target and self.dock.values()["use_target"]:
            distance = self.points[-1][0].distance(self.target[0])
            if distance > self.dock.values()["arrival"]:
                warnings.append(f"A végpont a célpont toleranciakörén kívül van ({distance:.1f} m).")
        if warnings:
            dialog = QMessageBox(self.iface.mainWindow())
            dialog.setIcon(QMessageBox.Warning)
            dialog.setWindowTitle("Tervezési figyelmeztetés")
            dialog.setText("A nyomvonal figyelmeztetéseket tartalmaz.")
            dialog.setInformativeText("\n".join("• " + item for item in warnings) + "\n\nLezárod és menthetővé teszed így is?")
            accept = dialog.addButton("Lezárom így is", QMessageBox.AcceptRole)
            dialog.addButton("Vissza a tervezéshez", QMessageBox.RejectRole)
            dialog.exec()
            if dialog.clickedButton() is not accept:
                self.dock.set_status("A lezárás megszakítva; a vonal tovább szerkeszthető.")
                return
        self._clear_candidate_bands(); self.running = False
        if self.previous_tool: self.canvas.setMapTool(self.previous_tool)
        segment_count = len(self.points) - 1
        self.result_layer = self._make_result_layer(); QgsProject.instance().addMapLayer(self.result_layer)
        length = sum(self.points[i][0].distance(self.points[i+1][0]) for i in range(segment_count))
        self._clear_helpers()
        self.points = []; self.segment_warnings = []; self.target = None
        self.dock.clear_points(); self.dock.set_warnings([])
        self.dock.set_finished(True); self.dock.set_status(f"Tervezés lezárva: {segment_count} szakasz, {length:.2f} m. A vonal menthető.")

    def _make_result_layer(self):
        crs = self.canvas.mapSettings().destinationCrs().authid()
        layer = QgsVectorLayer(f"LineString?crs={crs}", "oktatasi_semlegesvonal", "memory"); provider = layer.dataProvider()
        provider.addAttributes([QgsField("gradient_pct", QVariant.Double), QgsField("step_m", QVariant.Double), QgsField("segments", QVariant.Int), QgsField("length_m", QVariant.Double)])
        layer.updateFields(); values = self.dock.values(); length = sum(self.points[i][0].distance(self.points[i+1][0]) for i in range(len(self.points)-1))
        feature = QgsFeature(layer.fields()); feature.setGeometry(QgsGeometry.fromPolylineXY([item[0] for item in self.points])); feature.setAttributes([values["gradient"], values["step"], len(self.points)-1, length])
        provider.addFeature(feature); layer.updateExtents()
        line_symbol = QgsLineSymbol.createSimple({"line_color": "220,50,45", "line_width": "2", "line_width_unit": "MM", "line_style": "dash"})
        layer.renderer().setSymbol(line_symbol)
        return layer

    def retry(self):
        if not self.running or not self.points:
            return self._warn("Az újrapróbálás csak aktív tervezési munkamenetben használható.")
        self._freeze_current_trial()
        self.points = [self.points[0]]; self.segment_warnings = []; self._clear_candidate_bands(); self._draw_path(); self.dock.set_warnings([])
        self._update_candidates("Új próba ugyanazzal a kezdő- és célponttal. Add meg az új meredekséget.")

    def keep_reference(self):
        if self.result_layer is None: return
        self.result_layer.setName("semlegesvonal_referencia")
        self.points = []; self.segment_warnings = []; self.target = None; self.result_layer = None; self._clear_helpers()
        self.dock.set_warnings([])
        self.dock.set_finished(False); self.dock.set_status("A korábbi vonal referencia-réteg maradt. Jelölj ki új kezdőpontot.")

    def export(self, path):
        if self.result_layer is None: return self._warn("Nincs menthető, lezárt vonal.")
        options = QgsVectorFileWriter.SaveVectorOptions(); options.driverName = "GPKG" if path.lower().endswith(".gpkg") else "ESRI Shapefile"; options.fileEncoding = "UTF-8"
        result = QgsVectorFileWriter.writeAsVectorFormatV3(self.result_layer, path, QgsProject.instance().transformContext(), options)
        if result[0] == QgsVectorFileWriter.NoError: self.dock.set_status(f"A vonal elmentve: {path}")
        else: self._warn("A mentés nem sikerült: " + str(result[1] if len(result) > 1 else "ismeretlen hiba"))

    def _clear_visuals(self):
        self._clear_candidate_bands()
        for band in (self.path_band, self.target_band):
            if band:
                band.hide()
                self.canvas.scene().removeItem(band)
        self.path_band = self.target_band = None

    def _clear_helpers(self):
        self._clear_visuals()
        self._clear_trial_bands()
        for attribute in ("start_marker", "target_marker"):
            marker = getattr(self, attribute)
            if marker:
                marker.hide()
                setattr(self, attribute, None)

    def _warn(self, message):
        if self.dock: self.dock.set_status(message)
        QMessageBox.warning(self.iface.mainWindow(), "Oktatási semlegesvonal", message)
