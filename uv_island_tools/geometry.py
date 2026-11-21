"""UV geometry, similarity transforms and contour matching."""

from dataclasses import dataclass
from collections import Counter
from functools import cached_property
import math

import numpy as np


ROTATION = 1
SCALE = 2
POSITION = 4
EPSILON = 1e-7


@dataclass(frozen=True)
class Transform:
    multiplier: complex = 1 + 0j
    offset: complex = 0j

    def __call__(self, point):
        return self.multiplier * point + self.offset

    @classmethod
    def around(cls, multiplier, center):
        return cls(multiplier, (1 - multiplier) * center)


def area_center(triangles, points):
    area = 0.0
    moment = 0j
    for a, b, c in triangles:
        weight = abs(((b - a).conjugate() * (c - a)).imag) / 2
        area += weight
        moment += weight * (a + b + c) / 3
    return area, moment / area if area else sum(points) / max(1, len(points))


def polygon_area(ring):
    relative = [point - ring[0] for point in ring]
    return sum((a.conjugate() * b).imag for a, b in zip(relative, relative[1:] + relative[:1])) / 2


def simplify_ring(ring):
    """Remove collinear points while retaining corners and winding."""
    points = [point for index, point in enumerate(ring) if point != ring[index - 1]]
    if len(points) < 3:
        return ()
    result = []
    for index, point in enumerate(points):
        previous = point - points[index - 1]
        following = points[(index + 1) % len(points)] - point
        turn = previous.conjugate() * following
        if turn.real <= 0 or abs(turn.imag) > 2e-6 * abs(previous) * abs(following):
            result.append(point)
    if len(result) < 3 or abs(polygon_area(result)) < 1e-24:
        return ()
    if polygon_area(result) < 0:
        result.reverse()
    return tuple(result)


def contour_from_edges(edges):
    """Recover closed rings from the boundary of a UV island."""
    neighbors = {}
    for a, b in edges:
        if a != b:
            neighbors.setdefault(a, set()).add(b)
            neighbors.setdefault(b, set()).add(a)
    if not neighbors or any(len(adjacent) != 2 for adjacent in neighbors.values()):
        return None
    remaining = set(neighbors)
    rings = []
    point_order = lambda point: (point.real, point.imag)
    while remaining:
        first = min(remaining, key=point_order)
        current = min(neighbors[first], key=point_order)
        previous = first
        ring = [first]
        remaining.remove(first)
        while current != first:
            if current not in remaining:
                return None
            ring.append(current)
            remaining.remove(current)
            following, = neighbors[current] - {previous}
            previous, current = current, following
        simplified = simplify_ring(ring)
        if not simplified:
            return None
        rings.append(simplified)
    return Contour(rings)


def samples_along_ring(points, count=128):
    starts = np.asarray(points, dtype=np.complex128)
    vectors = np.roll(starts, -1) - starts
    lengths = np.abs(vectors)
    stops = np.cumsum(lengths)
    locations = np.arange(count) * (stops[-1] / count)
    indices = np.searchsorted(stops, locations, side="right")
    fraction = (locations - (stops[indices] - lengths[indices])) / lengths[indices]
    return starts[indices] + vectors[indices] * fraction


class Contour:
    def __init__(self, rings):
        self.rings = sorted(rings, key=lambda ring: -abs(polygon_area(ring)))
        self.outer_samples = samples_along_ring(self.rings[0])
        self.segments = [
            (np.asarray(ring), np.roll(np.asarray(ring), -1) - np.asarray(ring))
            for ring in self.rings
        ]
        self.samples = [
            np.concatenate((np.asarray(ring), samples_along_ring(ring))) for ring in self.rings
        ]
        points = np.concatenate(self.samples)
        self.diagonal = math.hypot(float(np.ptp(points.real)), float(np.ptp(points.imag)))
        self.normalized_hole_areas = sorted(
            abs(polygon_area(ring)) / abs(polygon_area(self.rings[0])) for ring in self.rings[1:]
        )


def distinct_anchors(anchors):
    if not anchors:
        return ()
    first, *others = anchors
    for other in others:
        if abs(first - other) > EPSILON:
            return first, other
    return (first,)


def _fit(source, target, flags, anchors):
    if len(anchors) > 1:
        return Transform()
    source_center = anchors[0] if anchors else np.mean(source)
    target_center = anchors[0] if anchors else np.mean(target)
    x = source - source_center
    y = target - target_center
    denominator = np.vdot(x, x).real
    if denominator <= 1e-30:
        return Transform()
    multiplier = complex(np.vdot(x, y) / denominator)
    if flags & ROTATION:
        multiplier = complex(max(multiplier.real, 1e-10))
    if flags & SCALE:
        multiplier = multiplier / abs(multiplier) if abs(multiplier) > 1e-10 else 1 + 0j
    if abs(multiplier) < 1e-10:
        multiplier = 1e-10 + 0j
    return Transform(multiplier, complex(target_center - multiplier * source_center))


def _nearest_on_segments(points, starts, vectors):
    results = np.empty(len(points), dtype=np.complex128)
    lengths = np.abs(vectors) ** 2
    batch = min(128, max(1, 131072 // len(starts)))
    for start in range(0, len(points), batch):
        end = min(start + batch, len(points))
        delta = points[start:end, None] - starts
        fractions = np.clip((delta * vectors.conjugate()).real / lengths, 0, 1)
        projected = starts + vectors * fractions
        closest = np.argmin(np.abs(projected - points[start:end, None]), axis=1)
        results[start:end] = projected[np.arange(end - start), closest]
    return results


def _one_way(points, segments):
    return float(np.max(np.abs(points - _nearest_on_segments(points, *segments))))


def _ring_error(source, target, transform, source_index, target_index):
    a, av = source.segments[source_index]
    b, bv = target.segments[target_index]
    return max(
        _one_way(transform(source.samples[source_index]), (b, bv)),
        _one_way(target.samples[target_index], (transform(a), transform.multiplier * av)),
    )


def _contour_error(source, target, transform, limit):
    error = _ring_error(source, target, transform, 0, 0)
    if error > limit or len(source.rings) == 1:
        return error

    # Match holes one-to-one by boundary error. Their order in the mesh can differ.
    candidates = [
        sorted(
            (_ring_error(source, target, transform, a, b), b)
            for b in range(1, len(target.rings))
        )
        for a in range(1, len(source.rings))
    ]
    matches = {}

    def assign(index, visited):
        for distance, hole in candidates[index]:
            if distance > limit:
                break
            if hole in visited:
                continue
            visited.add(hole)
            if hole not in matches or assign(matches[hole][0], visited):
                matches[hole] = (index, distance)
                return True
        return False

    for index in range(len(candidates)):
        if not assign(index, set()):
            return math.inf
    return max(error, *(distance for _, distance in matches.values()))


def find_match(source, target, tolerance, flags=0, anchors=(), evaluate=None):
    """Fit the UV contours, returning (relative deviation, transformation)."""
    if source is None or target is None or len(source.rings) != len(target.rings):
        return None
    if any(abs(a - b) > max(0.04, tolerance * 8) for a, b in zip(
        source.normalized_hole_areas, target.normalized_hole_areas,
    )):
        return None
    reference = target.diagonal
    limit = max(reference * tolerance, 1e-9)
    if flags & SCALE and abs(source.diagonal - target.diagonal) > 0.5 * reference:
        # Axis-aligned diagonals can differ after rotation, so this is a loose bound.
        return None
    anchors = distinct_anchors(anchors)
    if len(anchors) > 1 or flags & ROTATION and anchors and flags & SCALE:
        identity = Transform()
        error = _contour_error(source, target, identity, limit)
        if error > limit:
            return None
        error, transform = evaluate(identity, limit) if evaluate else (error, identity)
        return (error / reference, transform) if error <= limit else None

    a, b = source.outer_samples, target.outer_samples
    correlation = np.fft.ifft(np.fft.fft(b - b.mean()) * np.fft.fft(a - a.mean()).conj())
    likelihood = correlation.real if flags & ROTATION else np.abs(correlation)
    peaks = [index for index in range(len(a)) if likelihood[index] >= max(
        likelihood[index - 1], likelihood[(index + 1) % len(a)],
    )]
    peaks.sort(key=lambda index: (-likelihood[index], index))
    result = None
    for index in peaks if evaluate else peaks[:8]:
        prev, mid, following = (likelihood[(index + step) % len(a)] for step in (-1, 0, 1))
        curvature = prev - 2 * mid + following
        fraction = float(np.clip((prev - following) / (2 * curvature), -0.5, 0.5)) if curvature < 0 else 0
        offset = index + fraction
        base = math.floor(offset)
        target_samples = np.roll(b, -base) * (1 - offset + base) + np.roll(b, -base - 1) * (offset - base)
        transform = _fit(a, target_samples, flags, anchors)
        approximate = _ring_error(source, target, transform, 0, 0)
        if approximate > max(limit * 4, reference * 0.035):
            continue
        original = source.samples[0]
        for _ in range(5):
            error = _contour_error(source, target, transform, limit)
            if error <= limit:
                error, fitted = evaluate(transform, limit) if evaluate else (error, transform)
                if error <= limit and (result is None or error / reference < result[0]):
                    result = error / reference, fitted
                    if error <= max(reference * 1e-7, 1e-9):
                        return result
            closest = _nearest_on_segments(transform(original), *target.segments[0])
            transform = _fit(original, closest, flags, anchors)
    return result


def _face_cycle(face):
    start = face.index(min(face))
    cycle = face[start:] + face[:start]
    return min(cycle, cycle[:1] + cycle[:0:-1])


@dataclass
class UVTopology:
    vertices: tuple  # (mesh vertex index, UV)
    faces: tuple     # indices of UV vertices in each face

    @cached_property
    def points(self):
        return np.asarray([point for _, point in self.vertices], dtype=np.complex128)

    @cached_property
    def vertex_types(self):
        sizes = [[] for _ in self.vertices]
        neighbors = [Counter() for _ in self.vertices]
        for face in self.faces:
            for index, left in enumerate(face):
                right = face[index - 1]
                neighbors[left][right] += 1
                neighbors[right][left] += 1
                sizes[left].append(len(face))
        return tuple((tuple(sorted(faces)), tuple(sorted(edges.values())))
                     for faces, edges in zip(sizes, neighbors))

    @cached_property
    def signature(self):
        return Counter(self.vertex_types)

    @cached_property
    def face_cycles(self):
        return Counter(_face_cycle(face) for face in self.faces)

    @cached_property
    def by_type(self):
        result = {}
        for index, kind in enumerate(self.vertex_types):
            result.setdefault(kind, []).append(index)
        return {kind: np.asarray(indices) for kind, indices in result.items()}


def vertex_correspondence(source, target, transform, limit):
    """Pair nearest compatible UV vertices and check the complete face graph."""
    mapped = np.empty(len(source.vertices), dtype=np.intp)
    points = transform(source.points)
    for kind, indices in source.by_type.items():
        choices = target.by_type[kind]
        targets = target.points[choices]
        batch = max(1, 131072 // len(choices))
        for start in range(0, len(indices), batch):
            part = indices[start:start + batch]
            distances = np.abs(points[part, None] - targets)
            nearest = distances.argmin(axis=1)
            if np.any(distances[np.arange(len(part)), nearest] > limit):
                return None
            mapped[part] = choices[nearest]
    if len(set(mapped)) != len(mapped):
        return None
    cycles = Counter(_face_cycle(tuple(mapped[i] for i in face)) for face in source.faces)
    return mapped if cycles == target.face_cycles else None


def match_islands(source, target, tolerance, flags=0, anchors=()):
    """Find a similarity that agrees with both geometry and internal UV topology."""
    a, b = source.topology, target.topology
    if a.signature != b.signature:
        return None

    def evaluate(transform, limit):
        matched = vertex_correspondence(a, b, transform, 2 * limit)
        if matched is None:
            return math.inf, transform
        target_points = b.points[matched]
        fitted = _fit(a.points, target_points, flags, anchors)
        return float(np.max(np.abs(fitted(a.points) - target_points))), fitted

    return find_match(source.contour, target.contour, tolerance, flags, anchors, evaluate)


def stretch_percent(spatial_triangles, uv_triangles, aspect):
    """Report the largest directional stretch relative to the least stretched direction."""
    peak = None
    for (a, b, c), (u, v, w) in zip(spatial_triangles, uv_triangles):
        edge, other = b - a, c - a
        length = edge.length
        cross_length = edge.cross(other).length
        if length == 0 or cross_length == 0:
            continue
        first = v - u
        second = w - u - first * (edge.dot(other) / (length * length))
        first /= length
        second *= length / cross_length
        first = complex(first.real * aspect, first.imag)
        second = complex(second.real * aspect, second.imag)
        determinant = abs((first.conjugate() * second).imag)
        if determinant == 0:
            return math.inf
        # The singular-value ratio equals the largest squared singular value / |det|.
        diagonal = abs(first)**2 - abs(second)**2
        off_diagonal = 2 * (first.conjugate() * second).real
        largest = (abs(first)**2 + abs(second)**2 + math.hypot(diagonal, off_diagonal)) / 2
        percent = 100 * max(0.0, largest / determinant - 1)
        peak = percent if peak is None else max(peak, percent)
    return peak
