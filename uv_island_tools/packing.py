"""Continuous, seeded multi-start UV packing with exact footprint clearance."""

from dataclasses import dataclass
from functools import cached_property, lru_cache
import math
import random
import struct

import numpy as np

from .geometry import EPSILON, ROTATION, SCALE, Transform


PRESETS = {
    "512": (512, 4, 2), "1024": (1024, 8, 4), "2048": (2048, 16, 8),
    "4096": (4096, 32, 16), "8192": (8192, 64, 32),
}
DEFAULT_PASSES = 100
# Geometry is expressed in units of the longer texture side. The guard leaves
# room for roundoff when Blender stores the final transform as float32 UVs.
CLEARANCE_GUARD = 1.5e-6


@dataclass(frozen=True)
class Unit:
    key: object
    triangles: tuple
    center: complex
    area: float
    flags: int = 0
    anchors: tuple = ()
    boundary: tuple = ()
    surface_area: float = 0.0


@dataclass(frozen=True)
class PackConfig:
    width: int
    height: int
    gap: int
    border: int
    passes: int
    scale: bool
    seed: int = 0

    def validate(self):
        if 2 * self.border >= self.short_side:
            raise ValueError("The border takes up the entire UV tile.")
        if self.gap > self.short_side:
            raise ValueError("The gap exceeds the shorter side of the texture.")
        if not 1 <= self.passes <= 1000:
            raise ValueError("Set the number of passes to 1–1000.")

    @property
    def long_side(self):
        return max(self.width, self.height)

    @property
    def short_side(self):
        return min(self.width, self.height)

    @property
    def metric(self):
        return self.width / self.long_side, self.height / self.long_side


def cross(a, b):
    return (a.conjugate() * b).imag


def bounds(points):
    return (min(p.real for p in points), min(p.imag for p in points),
            max(p.real for p in points), max(p.imag for p in points))


def union(a, b):
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def box_at(box, delta):
    x, y = delta.real, delta.imag
    return box[0] + x, box[1] + y, box[2] + x, box[3] + y


def box_distance_sq(a, b):
    dx = max(0.0, a[0] - b[2], b[0] - a[2])
    dy = max(0.0, a[1] - b[3], b[1] - a[3])
    return dx * dx + dy * dy


def _box_reaches(a, b, gap_sq):
    return box_distance_sq(a, b) <= gap_sq


def _metric(point, metric):
    return complex(point.real * metric[0], point.imag * metric[1])


@dataclass(frozen=True)
class Triangle:
    points: tuple
    box: tuple
    nondegenerate: bool

    @classmethod
    def from_points(cls, points):
        a, b, c = points
        twice_area = cross(b - a, c - a)
        if twice_area < 0:
            points = a, c, b
        return cls(points, bounds(points), abs(twice_area) > 1e-20)


def _separated(a, b):
    for start, end in zip(a, (a[1], a[2], a[0])):
        edge = end - start
        if edge and max(cross(edge, p - start) for p in b) <= 0:
            return True
    return False


def _point_edge_sq(point, start, stop):
    edge = stop - start
    delta = point - start
    length_sq = edge.real * edge.real + edge.imag * edge.imag
    if length_sq:
        t = max(0.0, min(1.0, (edge.conjugate() * delta).real / length_sq))
        delta -= edge * t
    return delta.real * delta.real + delta.imag * delta.imag


def _proper_crossing(a, b, c, d):
    return (cross(b - a, c - a) * cross(b - a, d - a) < 0
            and cross(d - c, a - c) * cross(d - c, b - c) < 0)


def triangles_conflict(a, b, offset, gap_sq):
    if not _box_reaches(box_at(a.box, offset), b.box, gap_sq):
        return False
    moved = tuple(p + offset for p in a.points)
    fixed = b.points
    if a.nondegenerate and b.nondegenerate and not (_separated(moved, fixed) or _separated(fixed, moved)):
        return True
    if not gap_sq:
        return False
    if a.nondegenerate != b.nondegenerate:
        solid, flat = (moved, fixed) if a.nondegenerate else (fixed, moved)
        if not _separated(solid, flat):
            return True
    elif not a.nondegenerate:
        edges_a = zip(moved, (moved[1], moved[2], moved[0]))
        edges_b = tuple(zip(fixed, (fixed[1], fixed[2], fixed[0])))
        if any(_proper_crossing(a, b, c, d) for a, b in edges_a for c, d in edges_b):
            return True
    for source, target in ((moved, fixed), (fixed, moved)):
        for point in source:
            for start, stop in zip(target, (target[1], target[2], target[0])):
                if _point_edge_sq(point, start, stop) < gap_sq:
                    return True
    return False


@dataclass(frozen=True)
class Node:
    box: tuple
    skip: int
    triangle: int = -1


def _tree(triangles):
    """Lay out a bounding-volume tree in depth-first order, with escape indices."""
    nodes = []

    def append(indices):
        slot = len(nodes)
        box = triangles[indices[0]].box
        for index in indices[1:]:
            box = union(box, triangles[index].box)
        nodes.append(None)
        if len(indices) == 1:
            nodes[slot] = Node(box, slot + 1, indices[0])
            return
        axis = int(box[3] - box[1] > box[2] - box[0])
        indices.sort(key=lambda index: triangles[index].box[axis] + triangles[index].box[axis + 2])
        mid = len(indices) // 2
        append(indices[:mid])
        append(indices[mid:])
        nodes[slot] = Node(box, len(nodes))

    append(list(range(len(triangles))))
    return tuple(nodes)


@dataclass(frozen=True)
class Shape:
    triangles: tuple
    box: tuple
    supports: tuple
    multiplier: complex
    edges: tuple

    @cached_property
    def tree(self):
        return _tree(self.triangles)


def _shape(triangles, footprint, multiplier=1 + 0j, edges=()):
    values = tuple(Triangle.from_points(points) for points in triangles)
    points = [p for triangle in values for p in triangle.points]
    return Shape(values, bounds(points), footprint or tuple(dict.fromkeys(points[:24])), multiplier, edges)


@dataclass(frozen=True)
class Pose:
    shape: Shape
    offset: complex

    @cached_property
    def box(self):
        return box_at(self.shape.box, self.offset)


class Board:
    """Continuously placed geometry. Spatial buckets only accelerate CPU queries."""

    def __init__(self, config, guard=CLEARANCE_GUARD, track_gaps=True):
        self.width, self.height = config.metric
        self.gap = config.gap / config.long_side
        self.gap_sq = self.gap * self.gap
        self.guard = guard
        border = config.border / config.long_side
        self.inside_box = border, border, self.width - border, self.height - border
        self.poses = []
        self.bounding_box = None
        self._cells = {}
        self._bins = 16
        self.free_boxes = [self.inside_box] if track_gaps else []

    def _cell_range(self, box, padding=0.0):
        x0, y0, x1, y1 = box
        first_x = max(0, math.floor(self._bins * (x0 - padding) / self.width))
        first_y = max(0, math.floor(self._bins * (y0 - padding) / self.height))
        last_x = min(self._bins - 1, math.floor(self._bins * (x1 + padding) / self.width))
        last_y = min(self._bins - 1, math.floor(self._bins * (y1 + padding) / self.height))
        return ((i, j) for i in range(first_x, last_x + 1) for j in range(first_y, last_y + 1))

    def add(self, pose):
        x0, y0, x1, y1 = pose.box
        if x1 + self.gap < 0 or x0 - self.gap > self.width or y1 + self.gap < 0 or y0 - self.gap > self.height:
            return
        index = len(self.poses)
        self.poses.append(pose)
        for cell in self._cell_range(pose.box, self.gap):
            self._cells.setdefault(cell, []).append(index)
        self._reserve_box(pose.box)
        clipped = max(0.0, x0), max(0.0, y0), min(self.width, x1), min(self.height, y1)
        if clipped[2] >= clipped[0] and clipped[3] >= clipped[1]:
            self.bounding_box = union(self.bounding_box, clipped) if self.bounding_box is not None else clipped

    def _reserve_box(self, box):
        """Track rectangular gaps as placement hints. Exact shape tests still decide fit."""
        clearance = self.gap + 2 * self.guard
        a, b, c, d = box[0] - clearance, box[1] - clearance, box[2] + clearance, box[3] + clearance
        remaining = []
        split = False
        for x0, y0, x1, y1 in self.free_boxes:
            if x1 <= a or x0 >= c or y1 <= b or y0 >= d:
                remaining.append((x0, y0, x1, y1))
                continue
            split = True
            if x0 < a:
                remaining.append((x0, y0, a, y1))
            if x1 > c:
                remaining.append((c, y0, x1, y1))
            if y0 < b:
                remaining.append((x0, y0, x1, b))
            if y1 > d:
                remaining.append((x0, d, x1, y1))
        if not split:
            return
        remaining.sort(key=_box_area, reverse=True)
        kept = []
        for box in remaining:
            if not any(_box_contains(other, box) for other in kept):
                kept.append(box)
                if len(kept) == 36:
                    break
        self.free_boxes = kept

    def contains(self, pose):
        x0, y0, x1, y1 = pose.box
        left, bottom, right, top = self.inside_box
        return x0 >= left - 1e-12 and y0 >= bottom - 1e-12 and x1 <= right + 1e-12 and y1 <= top + 1e-12

    def fits(self, pose):
        if not self.contains(pose):
            return False
        indices = set()
        for cell in self._cell_range(pose.box):
            indices.update(self._cells.get(cell, ()))
        for index in indices:
            other = self.poses[index]
            if _box_reaches(pose.box, other.box, self.gap_sq) and self._conflict(pose, other):
                return False
        return True

    def _conflict(self, candidate, other):
        offset = candidate.offset - other.offset
        other_shape = other.shape
        for triangle in candidate.shape.triangles:
            moved_box = box_at(triangle.box, offset)
            index = 0
            while index < len(other_shape.tree):
                node = other_shape.tree[index]
                if not _box_reaches(moved_box, node.box, self.gap_sq):
                    index = node.skip
                    continue
                if node.triangle != -1 and triangles_conflict(
                    triangle, other_shape.triangles[node.triangle], offset, self.gap_sq,
                ):
                    return True
                index += 1
        return False


class CPUBackend:
    label = "CPU"

    def find(self, board, candidates):
        return next((candidate for candidate in candidates if board.fits(candidate)), None)

    def close(self):
        pass


@dataclass
class Result:
    transforms: dict
    scale: float
    coverage: float
    rectangle: float
    passes: int = 0
    spread: float = 0.0
    layout: tuple = ()
    order: tuple = ()

    @property
    def score(self):
        return self.scale, -round(self.rectangle, 10), -self.spread, self.coverage


def _box_area(box):
    return (box[2] - box[0]) * (box[3] - box[1])


def _box_contains(outer, inner):
    return outer[0] <= inner[0] and outer[1] <= inner[1] and outer[2] >= inner[2] and outer[3] >= inner[3]


def _outline_edges(unit):
    if unit.boundary:
        edges = tuple(unit.boundary)
    else:
        counts = {}
        for a, b, c in unit.triangles:
            for start, end in ((a, b), (b, c), (c, a)):
                key = frozenset((start, end))
                count, _ = counts.get(key, (0, None))
                counts[key] = count + 1, (start, end)
        edges = tuple(edge for count, edge in counts.values() if count == 1)
    edges = tuple(dict.fromkeys((a, b) for a, b in edges if a != b))
    if len(edges) <= 20:
        return edges
    longest = sorted(edges, key=lambda edge: abs(edge[1] - edge[0]), reverse=True)[:10]
    sampled = [edges[index * len(edges) // 12] for index in range(12)]
    return tuple(dict.fromkeys((*longest, *sampled)))


def _edge_angles(edges):
    directions = [b - a for a, b in edges if a != b]
    directions.sort(key=abs, reverse=True)
    angles = []
    for vector in directions[:10]:
        angle = (-math.atan2(vector.imag, vector.real)) % (math.pi / 2)
        if all(abs(angle - old) > 0.02 for old in angles):
            angles.append(angle)
    return angles or [0.0]


def _angles(unit, axes, pass_index, rng):
    if unit.flags & ROTATION or len(unit.anchors) > 1:
        return (0.0,)
    if pass_index == 0:
        return tuple(dict.fromkeys((0.0, math.pi / 2, axes[0], axes[0] + math.pi / 2)))
    quadrant = rng.randrange(4) * math.pi / 2
    tangent = rng.choice(axes)
    random_angle = rng.uniform(-math.pi, math.pi)
    return tuple(dict.fromkeys((quadrant, tangent + quadrant, tangent + quadrant + math.pi / 2, random_angle)))


def _support_hull(unit):
    points = sorted({point for triangle in unit.triangles for point in triangle},
                    key=lambda point: (point.real, point.imag))
    if len(points) <= 2:
        return tuple(points)

    def chain(sequence):
        side = []
        for point in sequence:
            while len(side) >= 2 and cross(side[-1] - side[-2], point - side[-1]) <= 0:
                side.pop()
            side.append(point)
        return side

    return tuple(chain(points)[:-1] + chain(reversed(points))[:-1])


def _neighbors(board, rng):
    poses = board.poses
    if len(poses) <= 14:
        return poses
    # Recent placements and a changing sample of older borders and pockets.
    indices = [*range(len(poses) - 5, len(poses)), *rng.sample(range(len(poses) - 5), 9)]
    return [poses[index] for index in indices]


def _rank_positions(proposals, shape, board, limits, preference, bias):
    values = np.asarray(proposals, dtype=np.complex128) if isinstance(proposals, list) else np.fromiter(
        proposals, dtype=np.complex128,
    )
    min_x, max_x, min_y, max_y = limits
    np.clip(values.real, min_x, max_x, out=values.real)
    np.clip(values.imag, min_y, max_y, out=values.imag)
    unique = list(dict.fromkeys(values.tolist()))
    xy = np.asarray(unique, dtype=np.complex128)
    left, bottom, right, top = shape.box
    x0, y0, x1, y1 = left + xy.real, bottom + xy.imag, right + xy.real, top + xy.imag
    center_x = (x0 + x1) * 0.5 / board.width
    center_y = (y0 + y1) * 0.5 / board.height
    if board.bounding_box is not None:
        a, b, c, d = board.bounding_box
        x0, y0 = np.minimum(a, x0), np.minimum(b, y0)
        x1, y1 = np.maximum(c, x1), np.maximum(d, y1)
    width, height = (x1 - x0) / board.width, (y1 - y0) / board.height
    gravity = np.abs(center_x - preference[0]) * bias + np.abs(center_y - preference[1]) * (1 - bias)
    scores = width * height + 0.10 * np.maximum(width, height) + 0.025 * gravity
    return [(score, shape, delta) for score, delta in zip(scores.tolist(), unique)]


def _gap_positions(free_boxes, shape):
    x0, y0, x1, y1 = shape.box
    spaces = []
    for a, b, c, d in free_boxes:
        limit_x, limit_y = c - x1, d - y1
        start_x, start_y = a - x0, b - y0
        if start_x <= limit_x and start_y <= limit_y:
            unused = min(limit_x - start_x, limit_y - start_y)
            spaces.append((unused, start_x, start_y, limit_x, limit_y))
    spaces.sort()
    for _, a, b, c, d in spaces[:8]:
        yield from (complex(a, b), complex(a, d), complex(c, b), complex(c, d), complex((a + c) / 2, (b + d) / 2))


def _contact_traces(shape, other, gap, limit):
    # A point following an offset outline edge traces a continuous set of poses.
    for a, b in other.shape.edges[:limit]:
        edge = b - a
        if not edge:
            continue
        normal = 1j * edge / abs(edge)
        lowest = min(shape.supports, key=lambda point: (point.conjugate() * normal).real)
        highest = max(shape.supports, key=lambda point: (point.conjugate() * normal).real)
        for point, outward in ((lowest, normal), (highest, -normal)):
            delta = other.offset - point + outward * gap
            yield a + delta, b + delta


def _intersection(a, b, c, d):
    ab, cd = b - a, d - c
    denominator = cross(ab, cd)
    if abs(denominator) <= 1e-15:
        return None
    t, u = cross(c - a, cd) / denominator, cross(c - a, ab) / denominator
    if 0 <= t <= 1 and 0 <= u <= 1:
        return a + t * ab
    return None


def _trace_positions(shape, neighbors, gap):
    if not neighbors:
        return
    # Reserve more contour detail for a few surrounding shapes. The general
    # search already probes the rest through the gap and bounding-box candidates.
    surrounding = sorted(neighbors, key=lambda pose: -_box_area(pose.box))[:4]
    limit = max(5, 20 // len(surrounding))
    traces = [trace for other in surrounding for trace in _contact_traces(shape, other, gap, limit)]
    for a, b in traces:
        yield a
        yield b
        yield (a + b) / 2
    for index, (a, b) in enumerate(traces):
        for c, d in traces[:index]:
            point = _intersection(a, b, c, d)
            if point is not None:
                yield point


def _candidates(board, shapes, rng, pass_index, detailed=False, random_start=False):
    left, bottom, right, top = board.inside_box
    preference = ((0, 0), (1, 0), (0, 1), (1, 1))[pass_index % 4]
    bias = 0.5 if pass_index == 0 else rng.uniform(0.15, 0.85)
    neighbors = _neighbors(board, rng)
    gap = board.gap + 2 * board.guard
    ranks = []
    starters = []
    for shape in shapes:
        x0, y0, x1, y1 = shape.box
        min_x, max_x = left - x0, right - x1
        min_y, max_y = bottom - y0, top - y1
        if min_x > max_x or min_y > max_y:
            continue
        if max_x - min_x >= 2 * board.guard:
            min_x, max_x = min_x + board.guard, max_x - board.guard
        if max_y - min_y >= 2 * board.guard:
            min_y, max_y = min_y + board.guard, max_y - board.guard
        if detailed:
            proposals = _trace_positions(shape, neighbors, gap)
        else:
            proposals = [complex(x, y) for x in (min_x, max_x) for y in (min_y, max_y)]
            proposals.extend(_gap_positions(board.free_boxes, shape))
            for other in neighbors:
                a, b, c, d = other.box
                l, r = a - gap - x1, c + gap - x0
                down, up = b - gap - y1, d + gap - y0
                along_x = rng.uniform(a - x0, c - x1) if pass_index else a - x0
                along_y = rng.uniform(b - y0, d - y1) if pass_index else b - y0
                proposals.extend((complex(l, along_y), complex(r, b - y0), complex(r, along_y),
                                  complex(along_x, down), complex(a - x0, up), complex(along_x, up)))
                # Midpoints on actual contours also compete when a distant
                # unoccupied rectangle exists. This makes cavities attractive.
                if (c - a) * (d - b) > _box_area(shape.box) * 1.25:
                    for start, end in _contact_traces(shape, other, gap, 3):
                        proposals.append((start + end) / 2)
            random_positions = [complex(rng.uniform(min_x, max_x), rng.uniform(min_y, max_y))
                                for _ in range(32 if random_start else 12)]
            if random_start:
                starters.extend(Pose(shape, point) for point in random_positions)
            proposals.extend(random_positions)

        # Clamping finds additional edge contacts while preserving continuous UV coordinates.
        ranks.extend(_rank_positions(proposals, shape, board, (min_x, max_x, min_y, max_y), preference, bias))
    ranks.sort(key=lambda value: value[0])
    rng.shuffle(starters)
    return starters + [Pose(shape, delta) for _, shape, delta in ranks]


def _obstacles(config, obstacles, outlines=True):
    metric = config.metric
    def shape(unit):
        triangles = tuple(tuple(_metric(p, metric) for p in triangle) for triangle in unit.triangles)
        edges = tuple((_metric(a, metric), _metric(b, metric)) for a, b in _outline_edges(unit)) if outlines else ()
        return _shape(triangles, (), edges=edges)
    return [Pose(shape(unit), 0j) for unit in obstacles]


def _layout_measure(placements):
    extent = None
    weighted_center = 0j
    moment = mass = 0.0
    for pose, area in placements:
        box = pose.box
        extent = box if extent is None else union(extent, box)
        center = complex((box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5)
        weighted_center += center * area
        moment += area * abs(center)**2
        mass += area
    return extent, weighted_center, moment, mass


def _place_order(movable, units, dimensions, index, rng, previous):
    if previous and index % 6 in (4, 5):
        ordered = list(previous)
        window = min(len(ordered), max(2, len(ordered) // 5))
        for _ in range(min(8, len(ordered) // 2)):
            a = rng.randrange(len(ordered))
            b = rng.randint(max(0, a - window), min(len(ordered) - 1, a + window))
            ordered[a], ordered[b] = ordered[b], ordered[a]
        return ordered
    weights = []
    for unit_index in movable:
        width, height = dimensions[unit_index]
        area = units[unit_index].area
        weight = (area, max(width, height)**2, (width + height)**2, width * height)[index % 4]
        if index:
            weight *= rng.uniform(0.82, 1.18)
        weights.append((weight, unit_index))
    weights.sort(key=lambda item: -item[0])
    return [unit_index for _, unit_index in weights]


def _result(units, layout, order, scale, metric):
    extent, center_sum, moment, mass = _layout_measure(
        (pose, unit.area * abs(pose.shape.multiplier)**2) for unit, pose in zip(units, layout)
    )
    transforms = {}
    for unit, pose in zip(units, layout):
        center = unit.anchors[0] if unit.anchors else unit.center
        position = complex(pose.offset.real / metric[0], pose.offset.imag / metric[1])
        transforms[unit.key] = Transform(pose.shape.multiplier, position - pose.shape.multiplier * center)
    spread = max(0.0, moment / mass - abs(center_sum / mass)**2) if mass else 0.0
    return Result(transforms, scale, min(1.0, mass), _box_area(extent) / (metric[0] * metric[1]),
                  spread=spread, layout=tuple(layout), order=tuple(order))


def _insertion_key(pose, extent, center_sum, moment, mass, area):
    box = pose.box
    center = complex((box[0] + box[2]) * 0.5, (box[1] + box[3]) * 0.5)
    extent = union(extent, box) if extent is not None else box
    total = mass + area
    variance = (moment + area * abs(center)**2) / total - abs((center_sum + area * center) / total)**2
    return round(_box_area(extent), 10), round(variance, 12)


def _compact(units, fixed, config, backend, best, movable, shape_at, obstacles):
    if len(movable) < 2:
        return best
    layout = list(best.layout)
    metric = config.metric
    rng = random.Random(0xA3EA)
    # First move islands that define the outside bounds, then try smaller fillers.
    edges = [selector(movable, key=lambda i: layout[i].box[axis])
             for axis, selector in enumerate((min, min, max, max))]
    small = sorted(movable, key=lambda i: units[i].area)
    order = tuple(dict.fromkeys((*edges, *small[:10], *reversed(small[-4:]))))
    for index in order:
        yield float(config.passes)
        unit = units[index]
        old_pose = layout[index]
        scale_here = abs(old_pose.shape.multiplier)
        others = [pose for i, pose in enumerate(layout) if i != index]
        extent, center_sum, moment, mass = _layout_measure(
            (pose, units[i].area * abs(pose.shape.multiplier)**2)
            for i, pose in enumerate(layout) if i != index
        )
        area = unit.area * scale_here**2
        threshold = _insertion_key(old_pose, extent, center_sum, moment, mass, area)
        board = Board(config)
        for pose in (*fixed, *others):
            board.add(pose)
        shapes = [old_pose.shape]
        if not unit.flags & ROTATION:
            multiplier = old_pose.shape.multiplier
            angle = math.atan2(multiplier.imag, multiplier.real)
            shapes.append(shape_at(index, scale_here, angle + math.pi / 2))
        candidates = _candidates(board, shapes, rng, 0)
        candidates.extend(_candidates(board, shapes, rng, 0, detailed=True))
        scored = []
        for pose in candidates:
            key = _insertion_key(pose, extent, center_sum, moment, mass, area)
            if key < threshold:
                scored.append((key, pose))
        scored.sort(key=lambda item: item[0])
        found = backend.find(board, [pose for _, pose in scored]) if scored else None
        if found is not None:
            layout[index] = found
    candidate = _result(units, layout, best.order, best.scale, metric)
    if candidate.score > best.score and validate_layout(units, obstacles, candidate.transforms, config):
        return candidate
    return best


def _grow_to_tile(best, config):
    """Uniform growth preserves both island ratios and established clearance."""
    x0, y0, x1, y1 = _layout_measure((pose, 1.0) for pose in best.layout)[0]
    width, height = config.metric
    margin = config.border / config.long_side + CLEARANCE_GUARD
    gain = min((width - 2 * margin) / max(1e-15, x1 - x0), (height - 2 * margin) / max(1e-15, y1 - y0))
    if gain <= 1 + 1e-6:
        return best
    offset = complex((margin - gain * x0) / width, (margin - gain * y0) / height)
    transforms = {key: Transform(t.multiplier * gain, t.offset * gain + offset)
                  for key, t in best.transforms.items()}
    return Result(transforms, best.scale * gain, min(1.0, best.coverage * gain**2), best.rectangle * gain**2,
                  spread=best.spread * gain**2)


def pack_iter(units, obstacles, config, backend):
    """Explore independent layouts and retain the best feasible arrangement."""
    config.validate()
    if not units:
        return None
    metric = config.metric
    fixed = _obstacles(config, obstacles)
    anchors = [index for index, unit in enumerate(units) if unit.anchors]
    movable = [index for index, unit in enumerate(units) if not unit.anchors]
    boundary_points = [_support_hull(unit) for unit in units]
    outlines = [_outline_edges(unit) for unit in units]
    axes = [_edge_angles(edges) for edges in outlines]
    resizable = [i for i, u in enumerate(units) if not u.flags & SCALE and len(u.anchors) < 2]
    natural = [i for i in resizable if units[i].surface_area > 0 and units[i].area > 0]
    normalizers = [1.0] * len(units)
    if natural:
        density_sq = sum(units[i].area for i in natural) / sum(units[i].surface_area for i in natural)
        for i in natural:
            normalizers[i] = math.sqrt(density_sq * units[i].surface_area / units[i].area)
    dimensions = []
    for unit, normalizer in zip(units, normalizers):
        x0, y0, x1, y1 = bounds(tuple(p for triangle in unit.triangles for p in triangle))
        dimensions.append(((x1 - x0) * normalizer, (y1 - y0) * normalizer))
    scalable = set(resizable) if config.scale else set()
    target_area = sum(units[i].area * normalizers[i]**2 for i in scalable)
    usable = (1 - 2 * config.border / config.width) * (1 - 2 * config.border / config.height)
    estimate = math.sqrt(0.58 * usable / max(1e-22, target_area))
    max_dimension = max((max(dimensions[index]) for index in scalable), default=0.0)
    ceiling = min(1e7, math.sqrt(2) / max(max_dimension, 1e-12))
    original = {unit.key: Transform() for unit in units}
    @lru_cache(maxsize=768)
    def shape_at(index, factor, angle):
        unit = units[index]
        multiplier = factor * complex(math.cos(angle), math.sin(angle))
        pivot = unit.anchors[0] if unit.anchors else unit.center
        def relative(point):
            return _metric((point - pivot) * multiplier, metric)
        triangles = tuple(tuple(relative(point) for point in triangle) for triangle in unit.triangles)
        footprint = tuple(relative(point) for point in boundary_points[index])
        edges = tuple((relative(a), relative(b)) for a, b in outlines[index])
        return _shape(triangles, footprint, multiplier, edges)

    best = None
    if all(abs(n - 1) < EPSILON for n in normalizers) and validate_layout(units, obstacles, original, config):
        original_poses = [Pose(shape_at(i, 1.0, 0.0), _metric(unit.anchors[0] if unit.anchors else unit.center, metric))
                          for i, unit in enumerate(units)]
        best = _result(units, original_poses, movable, 1.0, metric)
        best.transforms = original

    may_grow = not anchors and not fixed and len(scalable) == len(units)
    winner = source = best

    def consider(layout):
        nonlocal winner, source
        projected = _grow_to_tile(layout, config) if may_grow else layout
        if winner is None or projected.score > winner.score:
            if validate_layout(units, obstacles, projected.transforms, config):
                winner, source = projected, layout

    if best is not None and may_grow:
        consider(best)

    def attempt(scale, index, progress=None, random_start=False):
        rng = random.Random(config.seed ^ (0x71A903 + index))
        board = Board(config)
        for pose in fixed:
            board.add(pose)
        ordered = _place_order(movable, units, dimensions, index, rng, best.order if best else ())
        constrained = sorted(anchors, key=lambda i: (-len(units[i].anchors), -units[i].flags.bit_count(),
                                                     -max(dimensions[i])**2 * rng.uniform(0.8, 1.2)))
        sequence = constrained + ordered
        layout = [None] * len(units)
        placed = 0
        rearranged = False
        while placed < len(sequence):
            i = sequence[placed]
            yield index + placed / len(units) if progress is None else progress
            unit = units[i]
            scale_here = normalizers[i] * (scale if i in scalable else 1.0)
            shapes = [shape_at(i, scale_here, angle) for angle in _angles(unit, axes[i], index, rng)]
            if unit.anchors:
                center = _metric(unit.anchors[0], metric)
                candidates = [pose for shape in shapes if board.contains(pose := Pose(shape, center))]
            else:
                candidates = _candidates(board, shapes, rng, index, random_start=random_start and placed <= len(anchors) + 1)
            pose = backend.find(board, candidates) if candidates else None
            if pose is None and not unit.anchors:
                if not unit.flags & ROTATION:
                    angles = []
                    for neighbor in _neighbors(board, rng)[:3]:
                        if neighbor.shape.edges:
                            a, b = max(neighbor.shape.edges, key=lambda edge: abs(edge[1] - edge[0]))
                            alignment = math.atan2((b - a).imag, (b - a).real) + axes[i][0]
                            angles.extend((alignment, alignment + math.pi))
                    shapes.extend(shape_at(i, scale_here, angle) for angle in dict.fromkeys(angles))
                candidates = _candidates(board, shapes, rng, index, detailed=True)
                pose = backend.find(board, candidates) if candidates else None
            if pose is None:
                if rearranged or placed < max(len(anchors) + 2, len(units) // 2):
                    return None
                # Try the last two slots with the constrained island first.
                # Keep the already valid prefix intact and bound work per pass.
                rear = placed - 2
                displaced = sequence[rear:placed]
                sequence[rear:placed + 1] = [i, *displaced]
                for removed in displaced:
                    layout[removed] = None
                board = Board(config)
                for kept in (*fixed, *(layout[j] for j in sequence[:rear])):
                    board.add(kept)
                placed = rear
                rearranged = True
                continue
            layout[i] = pose
            board.add(pose)
            placed += 1
        return _result(units, layout, sequence[len(anchors):], scale, metric)

    failed_scale = math.inf
    factor = min(ceiling, estimate)
    if best is None:
        # Establish a valid starting layout independently of the input UV positions.
        # Early movable units sample the whole tile; placement then returns to contact search.
        seed_scale = min(1.0, factor) * 0.82
        for restart in range(4):
            seed = yield from attempt(seed_scale if scalable else 1.0, restart + 1, 0.0, random_start=True)
            if seed is not None and validate_layout(units, obstacles, seed.transforms, config):
                best = seed
                consider(seed)
                break
            seed_scale *= 0.62
    for index in range(config.passes):
        if not scalable:
            factor = 1.0
        elif best is None:
            factor = factor if not index else factor * 0.84
        elif index % 5 == 0:
            # A failed attempt only bounds this heuristic, not mathematical feasibility.
            factor = min(ceiling, best.scale * 1.016)
        elif index % 5 == 4:
            factor = best.scale
        else:
            cap = min(ceiling, failed_scale)
            growth = min(1.12, math.sqrt(max(1.0, cap / best.scale)))
            factor = min(ceiling, best.scale * growth)
        candidate = yield from attempt(factor, index, random_start=index % 5 == 3)
        if candidate is not None and (best is None or candidate.score > best.score):
            if validate_layout(units, obstacles, candidate.transforms, config):
                best = candidate
                if not may_grow:
                    winner = source = candidate
                if failed_scale <= best.scale:
                    failed_scale = math.inf
            else:
                candidate = None
        if candidate is not None and may_grow:
            consider(candidate)
        if candidate is None and (best is None or factor > best.scale):
            failed_scale = min(failed_scale, factor)
        yield index + 1
    if winner is None:
        # Short searches can exhaust their requested passes before finding a feasible
        # seed. Retry with wider size reductions and independent placements.
        recovery = min(factor, seed_scale)
        for restart in range(6):
            seed = yield from attempt(recovery if scalable else 1.0, config.passes + 8 + restart,
                                      float(config.passes), random_start=restart % 2 == 0)
            if seed is not None:
                consider(seed)
                if winner is not None:
                    break
            recovery *= 0.48
    if source is not None:
        compacted = yield from _compact(units, fixed, config, backend, source, movable, shape_at, obstacles)
        if compacted is not source:
            consider(compacted)
        winner.passes = config.passes
    return winner


def validate_layout(units, obstacles, transforms, config):
    """Validate Blender's rounded UVs with continuous geometry and requested padding."""
    def f32(value):
        return struct.unpack("f", struct.pack("f", value))[0]

    board = Board(config, guard=0.0, track_gaps=False)
    for pose in _obstacles(config, obstacles, outlines=False):
        board.add(pose)
    metric = config.metric
    for unit in units:
        transform = transforms[unit.key]
        if (unit.flags & ROTATION and (abs(transform.multiplier.imag) > EPSILON or transform.multiplier.real <= 0)
                or unit.flags & SCALE and abs(abs(transform.multiplier) - 1) > EPSILON
                or any(abs(transform(anchor) - anchor) > EPSILON for anchor in unit.anchors)):
            return False
        triangles = []
        for triangle in unit.triangles:
            transformed = [transform(point) for point in triangle]
            triangles.append(tuple(_metric(complex(f32(p.real), f32(p.imag)), metric) for p in transformed))
        pose = Pose(_shape(triangles, ()), 0j)
        if not board.fits(pose):
            return False
        board.add(pose)
    return True
