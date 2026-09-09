# -*- coding: utf-8 -*-
"""Continuous B-spline elevation sampling for the educational plugin.

The implementation deliberately samples at arbitrary map positions, rather
than at raster-cell centres.  It uses GDAL's CubicSpline interpolator when it
is available and has an equivalent 4x4 B-spline fallback for QGIS builds with
an older GDAL.
"""
from __future__ import annotations

from collections import OrderedDict
from math import floor, isfinite

import numpy as np
from osgeo import gdal


class TerrainError(RuntimeError):
    pass


class BSplineDemSampler:
    """Read a single DEM band with continuous cubic B-spline interpolation."""

    def __init__(self, source: str, band_number: int = 1, cache_size: int = 512):
        self.dataset = gdal.Open(source, gdal.GA_ReadOnly)
        if self.dataset is None:
            raise TerrainError("A kiválasztott DEM-et a GDAL nem tudta megnyitni.")
        if not 1 <= band_number <= self.dataset.RasterCount:
            raise TerrainError("Érvénytelen DEM-sáv.")
        self.band = self.dataset.GetRasterBand(band_number)
        self.width, self.height = self.dataset.RasterXSize, self.dataset.RasterYSize
        if self.width < 4 or self.height < 4:
            raise TerrainError("B-spline mintavételhez legalább 4×4 pixeles DEM szükséges.")
        self.gt = self.dataset.GetGeoTransform()
        inv = gdal.InvGeoTransform(self.gt)
        if inv is None:
            raise TerrainError("A DEM geotranszformációja nem invertálható.")
        if len(inv) == 2 and isinstance(inv[0], (bool, int)):
            if not inv[0]:
                raise TerrainError("A DEM geotranszformációja nem invertálható.")
            inv = inv[1]
        self.inv_gt = inv
        self.nodata = self.band.GetNoDataValue()
        self.scale = self.band.GetScale() or 1.0
        self.offset = self.band.GetOffset() or 0.0
        self.mask = self.band.GetMaskBand()
        self.mask_flags = self.band.GetMaskFlags()
        self.cache_size = cache_size
        self.cache = OrderedDict()
        self.gdal_spline = getattr(gdal, "GRIORA_CubicSpline", None)
        self.can_gdal_interpolate = bool(
            self.gdal_spline is not None and callable(getattr(self.band, "InterpolateAtPoint", None))
        )

    @property
    def backend_label(self) -> str:
        return "GDAL CubicSpline" if self.can_gdal_interpolate else "belső 4×4 B-spline"

    def close(self):
        self.cache.clear()
        self.mask = self.band = self.dataset = None

    def _window(self, col, row):
        key = (col, row)
        if key in self.cache:
            value = self.cache.pop(key)
            self.cache[key] = value
            return value
        values = self.band.ReadAsArray(col, row, 4, 4)
        valid = values is not None and getattr(values, "shape", None) == (4, 4)
        if valid:
            values = np.asarray(values, dtype=float)
            valid = np.isfinite(values).all()
        if valid and self.nodata is not None:
            valid = not np.equal(values, self.nodata).any()
        if valid and self.mask is not None and not (self.mask_flags & gdal.GMF_ALL_VALID):
            mask = self.mask.ReadAsArray(col, row, 4, 4)
            valid = mask is not None and np.asarray(mask).shape == (4, 4) and np.all(np.asarray(mask) != 0)
        value = values if valid else None
        self.cache[key] = value
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return value

    @staticmethod
    def _weights(t):
        t2, t3 = t * t, t * t * t
        return np.array(((1 - 3*t + 3*t2 - t3) / 6, (4 - 6*t2 + 3*t3) / 6,
                         (1 + 3*t + 3*t2 - 3*t3) / 6, t3 / 6), dtype=float)

    def sample(self, x, y):
        """Return physical DEM elevation at DEM-CRS coordinates, else None."""
        if self.band is None:
            return None
        px, py = gdal.ApplyGeoTransform(self.inv_gt, float(x), float(y))
        fx, fy = px - 0.5, py - 0.5  # GDAL pixels are corner-based
        col, row = int(floor(fx)), int(floor(fy))
        x0, y0 = col - 1, row - 1
        if x0 < 0 or y0 < 0 or x0 + 3 >= self.width or y0 + 3 >= self.height:
            return None
        values = self._window(x0, y0)
        if values is None:
            return None
        raw = None
        if self.can_gdal_interpolate:
            try:
                raw = self.band.InterpolateAtPoint(float(px), float(py), self.gdal_spline)
            except Exception:
                raw = None
        if raw is None:
            raw = float(self._weights(fy - row) @ values @ self._weights(fx - col))
        try:
            z = float(raw) * float(self.scale) + float(self.offset)
        except (TypeError, ValueError):
            return None
        return z if isfinite(z) else None
