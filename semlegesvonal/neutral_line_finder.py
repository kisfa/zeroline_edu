# -*- coding: utf-8 -*-

from dataclasses import dataclass
from heapq import heappop, heappush
from math import atan2, cos, degrees, floor, hypot, radians, sin

from qgis.core import QgsCoordinateTransform, QgsPointXY, QgsProject, QgsRaster


SLOPE_TOLERANCE_PERCENT = 0.5
DIRECTION_COUNT = 72
ROOT_SAMPLE_COUNT = 10


@dataclass(frozen=True)
class SearchParameters:
    target_slope_percent: float
    arrival_radius_m: float
    step_length_m: float
    search_angle_degrees: float
    max_expansions: int
    turn_penalty: float
    max_detour_factor: float


@dataclass
class SearchResult:
    points: list
    length: float
    arrival_distance_m: float
    mean_slope_percent: float
    min_slope_percent: float
    max_slope_percent: float
    expanded_nodes: int


@dataclass(frozen=True)
class SearchNode:
    point: QgsPointXY
    elevation: float
    direction_index: int


class NeutralLineError(Exception):
    pass


class RasterSampler:
    def __init__(self, raster_layer, source_crs):
        self.layer = raster_layer
        self.provider = raster_layer.dataProvider()
        self.extent = raster_layer.extent()
        self.width = raster_layer.width()
        self.height = raster_layer.height()
        self.x_size = self.extent.width() / self.width
        self.y_size = self.extent.height() / self.height
        self.pixel_size = (abs(self.x_size) + abs(self.y_size)) / 2.0
        self.to_raster = QgsCoordinateTransform(
            source_crs, raster_layer.crs(), QgsProject.instance()
        )
        self.from_raster = QgsCoordinateTransform(
            raster_layer.crs(), source_crs, QgsProject.instance()
        )
        self._z_cache = {}

    def to_raster_point(self, point):
        raster_point = self.to_raster.transform(QgsPointXY(point))
        if not self.extent.contains(raster_point):
            raise NeutralLineError("A megadott pont a DEM kiterjedesen kivul van.")
        return raster_point

    def to_cell(self, point):
        raster_point = self.to_raster_point(point)
        col = int((raster_point.x() - self.extent.xMinimum()) / self.x_size)
        row = int((self.extent.yMaximum() - raster_point.y()) / self.y_size)
        return self._clamp_cell(row, col)

    def cell_center(self, cell):
        row, col = cell
        x = self.extent.xMinimum() + (col + 0.5) * self.x_size
        y = self.extent.yMaximum() - (row + 0.5) * self.y_size
        return QgsPointXY(x, y)

    def map_point(self, cell):
        return self.from_raster.transform(self.cell_center(cell))

    def to_map_point(self, raster_point):
        return self.from_raster.transform(QgsPointXY(raster_point))

    def elevation_at(self, raster_point):
        if not self.extent.contains(raster_point):
            return None

        col_f = (raster_point.x() - self.extent.xMinimum()) / self.x_size - 0.5
        row_f = (self.extent.yMaximum() - raster_point.y()) / self.y_size - 0.5
        col0 = floor(col_f)
        row0 = floor(row_f)
        col1 = col0 + 1
        row1 = row0 + 1

        if row0 < 0 or col0 < 0 or row1 >= self.height or col1 >= self.width:
            return self._identify_elevation(raster_point)

        tx = col_f - col0
        ty = row_f - row0
        z00 = self.elevation((row0, col0))
        z10 = self.elevation((row0, col1))
        z01 = self.elevation((row1, col0))
        z11 = self.elevation((row1, col1))
        if None in (z00, z10, z01, z11):
            return None

        top = z00 * (1.0 - tx) + z10 * tx
        bottom = z01 * (1.0 - tx) + z11 * tx
        return top * (1.0 - ty) + bottom * ty

    def elevation(self, cell):
        if cell in self._z_cache:
            return self._z_cache[cell]

        if not self.in_bounds(cell):
            return None

        result = self.provider.identify(self.cell_center(cell), QgsRaster.IdentifyFormatValue)
        if not result.isValid():
            self._z_cache[cell] = None
            return None

        values = result.results()
        value = values.get(1)
        if value is None:
            self._z_cache[cell] = None
            return None

        try:
            value = float(value)
        except (TypeError, ValueError):
            self._z_cache[cell] = None
            return None

        self._z_cache[cell] = value
        return value

    def in_bounds(self, cell):
        row, col = cell
        return 0 <= row < self.height and 0 <= col < self.width

    def distance(self, a, b):
        ar, ac = a
        br, bc = b
        return hypot((bc - ac) * self.x_size, (br - ar) * self.y_size)

    def direct_distance(self, a, b):
        return self.distance(a, b)

    def point_distance(self, a, b):
        return hypot(b.x() - a.x(), b.y() - a.y())

    def quantized_key(self, point, resolution):
        return (
            int(round((point.x() - self.extent.xMinimum()) / resolution)),
            int(round((point.y() - self.extent.yMinimum()) / resolution)),
        )

    def _identify_elevation(self, raster_point):
        result = self.provider.identify(raster_point, QgsRaster.IdentifyFormatValue)
        if not result.isValid():
            return None

        value = result.results().get(1)
        if value is None:
            return None

        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _clamp_cell(self, row, col):
        row = min(max(row, 0), self.height - 1)
        col = min(max(col, 0), self.width - 1)
        return row, col


class NeutralLineFinder:
    def __init__(self, raster_layer, map_crs):
        self.sampler = RasterSampler(raster_layer, map_crs)

    def find(self, start_point, end_point, params):
        start = self.sampler.to_raster_point(start_point)
        goal = self.sampler.to_raster_point(end_point)
        start_z = self.sampler.elevation_at(start)
        goal_z = self.sampler.elevation_at(goal)

        if start_z is None:
            raise NeutralLineError("A kezdopont alatt nincs ervenyes DEM ertek.")
        if goal_z is None:
            raise NeutralLineError("A celpont alatt nincs ervenyes DEM ertek.")

        direct_distance = self.sampler.point_distance(start, goal)
        if direct_distance <= params.arrival_radius_m:
            raise NeutralLineError("A kezdopont mar a celpont erkezesi korzeteben van.")

        max_path_length = direct_distance * max(params.max_detour_factor, 1.0)
        search_result = self._search(start, start_z, goal, params, max_path_length)
        if search_result is None:
            raise NeutralLineError(
                "Nem talaltam vonalat a megadott lejtessel es erkezesi sugarral."
            )

        path_nodes, expanded = search_result
        raster_points = [node.point for node in path_nodes]
        points = [self.sampler.to_map_point(point) for point in raster_points]
        slopes = self._path_slopes(path_nodes)
        length = self._path_length(raster_points)
        arrival_distance = self.sampler.point_distance(raster_points[-1], goal)
        return SearchResult(
            points=points,
            length=length,
            arrival_distance_m=arrival_distance,
            mean_slope_percent=sum(slopes) / len(slopes) if slopes else 0.0,
            min_slope_percent=min(slopes) if slopes else 0.0,
            max_slope_percent=max(slopes) if slopes else 0.0,
            expanded_nodes=expanded,
        )

    def _search(self, start, start_z, goal, params, max_path_length):
        start_node = SearchNode(start, start_z, -1)
        start_key = self._state_key(start_node, params)
        frontier = []
        sequence = 0
        heappush(frontier, (0.0, sequence, start_key))

        nodes = {start_key: start_node}
        came_from = {start_key: None}
        cost_so_far = {start_key: 0.0}
        length_so_far = {start_key: 0.0}
        expanded = 0

        while frontier:
            _, _, current_key = heappop(frontier)
            current = nodes[current_key]
            expanded += 1

            if expanded > params.max_expansions:
                break
            if self._is_goal(current.point, goal, params):
                return self._reconstruct(came_from, nodes, current_key), expanded

            for candidate in self._candidate_nodes(current, goal, params):
                step_length = self.sampler.point_distance(current.point, candidate.point)
                new_length = length_so_far[current_key] + step_length
                if new_length > max_path_length:
                    continue

                step_slope = self._step_slope(current, candidate, step_length)
                slope_error = abs(step_slope - params.target_slope_percent)
                if slope_error > SLOPE_TOLERANCE_PERCENT:
                    continue

                slope_cost = self._slope_cost(slope_error)
                step_cost = step_length * (1.0 + slope_cost)
                new_cost = cost_so_far[current_key] + step_cost
                candidate_key = self._state_key(candidate, params)

                if candidate_key not in cost_so_far or new_cost < cost_so_far[candidate_key]:
                    sequence += 1
                    nodes[candidate_key] = candidate
                    came_from[candidate_key] = current_key
                    cost_so_far[candidate_key] = new_cost
                    length_so_far[candidate_key] = new_length
                    priority = new_cost + self.sampler.point_distance(candidate.point, goal)
                    heappush(frontier, (priority, sequence, candidate_key))

        return None

    def _candidate_nodes(self, current, goal, params):
        center_angle = degrees(
            atan2(goal.y() - current.point.y(), goal.x() - current.point.x())
        )
        if params.search_angle_degrees >= 360:
            angles = [index * 360.0 / DIRECTION_COUNT for index in range(DIRECTION_COUNT)]
        else:
            count = max(3, int(DIRECTION_COUNT * params.search_angle_degrees / 360.0))
            angle_step = params.search_angle_degrees / (count - 1)
            start_angle = center_angle - params.search_angle_degrees / 2.0
            angles = [start_angle + index * angle_step for index in range(count)]

        for direction_index, angle in enumerate(angles):
            candidate = self._find_point_on_slope(current, angle, params)
            if candidate is not None:
                yield SearchNode(candidate[0], candidate[1], direction_index)

    def _find_point_on_slope(self, current, angle_degrees, params):
        step = params.step_length_m
        min_distance = max(step * 0.5, self.sampler.pixel_size * 0.5)
        max_distance = max(step * 1.5, min_distance + self.sampler.pixel_size)
        distances = [
            min_distance + (max_distance - min_distance) * index / ROOT_SAMPLE_COUNT
            for index in range(ROOT_SAMPLE_COUNT + 1)
        ]

        samples = []
        for distance in distances:
            point = self._point_from_angle(current.point, angle_degrees, distance)
            elevation = self.sampler.elevation_at(point)
            if elevation is None:
                continue
            target_z = current.elevation + distance * params.target_slope_percent / 100.0
            samples.append((distance, point, elevation, elevation - target_z))

        best = None
        for left, right in zip(samples, samples[1:]):
            if left[3] == 0:
                best = left
                break
            if left[3] * right[3] <= 0:
                best = self._bisect_slope_root(current, angle_degrees, left, right, params)
                break

        if best is None:
            accepted = [
                sample
                for sample in samples
                if abs(self._sample_slope(current, sample) - params.target_slope_percent)
                <= SLOPE_TOLERANCE_PERCENT
            ]
            if not accepted:
                return None
            best = min(accepted, key=lambda sample: abs(sample[0] - step))

        return best[1], best[2]

    def _bisect_slope_root(self, current, angle_degrees, left, right, params):
        low_distance, _, _, low_value = left
        high_distance, _, _, high_value = right
        best = min((left, right), key=lambda sample: abs(sample[3]))

        for _ in range(12):
            mid_distance = (low_distance + high_distance) / 2.0
            mid_point = self._point_from_angle(current.point, angle_degrees, mid_distance)
            mid_z = self.sampler.elevation_at(mid_point)
            if mid_z is None:
                break
            target_z = current.elevation + mid_distance * params.target_slope_percent / 100.0
            mid_value = mid_z - target_z
            mid_sample = (mid_distance, mid_point, mid_z, mid_value)
            if abs(mid_value) < abs(best[3]):
                best = mid_sample
            if low_value * mid_value <= 0:
                high_distance = mid_distance
                high_value = mid_value
            else:
                low_distance = mid_distance
                low_value = mid_value

        return best

    @staticmethod
    def _point_from_angle(point, angle_degrees, distance):
        angle = radians(angle_degrees)
        return QgsPointXY(
            point.x() + cos(angle) * distance,
            point.y() + sin(angle) * distance,
        )

    @staticmethod
    def _sample_slope(current, sample):
        distance, _, elevation, _ = sample
        if distance == 0:
            return 0.0
        return ((elevation - current.elevation) / distance) * 100.0

    @staticmethod
    def _step_slope(current, candidate, step_length):
        if step_length == 0:
            return 0.0
        return ((candidate.elevation - current.elevation) / step_length) * 100.0

    def _path_slopes(self, path_nodes):
        slopes = []
        for current, candidate in zip(path_nodes, path_nodes[1:]):
            length = self.sampler.point_distance(current.point, candidate.point)
            slopes.append(self._step_slope(current, candidate, length))
        return slopes

    def _path_length(self, path_points):
        return sum(
            self.sampler.point_distance(current, candidate)
            for current, candidate in zip(path_points, path_points[1:])
        )

    def _is_goal(self, current, goal, params):
        return self.sampler.point_distance(current, goal) <= params.arrival_radius_m

    @staticmethod
    def _slope_cost(slope_error):
        return slope_error / SLOPE_TOLERANCE_PERCENT

    def _state_key(self, node, params):
        resolution = max(params.step_length_m * 0.5, self.sampler.pixel_size * 0.5)
        return (*self.sampler.quantized_key(node.point, resolution), node.direction_index)

    @staticmethod
    def _reconstruct(came_from, nodes, state):
        path = []
        while state is not None:
            path.append(nodes[state])
            state = came_from[state]
        path.reverse()
        return path
