"""Read UV islands from Blender and commit changes to edit-mode meshes."""

from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property
from hashlib import blake2s
from itertools import chain
from math import isfinite
from uuid import uuid4

import bmesh
import bpy

from .geometry import POSITION, UVTopology, area_center, contour_from_edges, distinct_anchors
from .packing import Unit


_PREFIX = ".uvit_v1_"
_STACK = "_stack"
_CLUSTER = "_cluster"


def _layer_names(uv_name):
    suffix = blake2s(uv_name.encode("utf-8"), digest_size=10).hexdigest()
    name = _PREFIX + suffix
    return name + "_locks", name + _STACK, name + _CLUSTER, name + "_stretch_ignore"


def is_uv_edit(context):
    area = context.area
    return bool(context.mode == "EDIT_MESH" and area and area.ui_type == "UV")


def _selection_modes(settings):
    if settings.use_uv_select_sync:
        return {mode for mode, enabled in zip(("VERTEX", "EDGE", "FACE"), settings.mesh_select_mode) if enabled}
    return {settings.uv_select_mode}


def _face_selected(face, uv_selection_available, modes):
    if not uv_selection_available:
        return (
            ("FACE" in modes and face.select)
            or ("VERTEX" in modes and any(vertex.select for vertex in face.verts))
            or ("EDGE" in modes and any(edge.select for edge in face.edges))
        )
    if modes & {"FACE", "ISLAND"}:
        return face.uv_select
    return (
        ("VERTEX" in modes and any(loop.uv_select_vert for loop in face.loops))
        or ("EDGE" in modes and any(loop.uv_select_edge for loop in face.loops))
    )


def _group_id(value):
    return value.partition(b":")[0] if value else b""


def group_token():
    return uuid4().hex.encode("ascii")


def membership(group, previous_storage):
    previous = previous_storage.partition(b":")[2]
    return group + b":" + (previous or group_token())


@dataclass(frozen=True)
class MeshState:
    mesh: object
    uv_name: str
    lock_name: str
    stack_name: str
    cluster_name: str
    ignore_name: str

    @property
    def bm(self):
        return bmesh.from_edit_mesh(self.mesh)


@dataclass
class Island:
    state: MeshState
    faces: tuple
    visible_faces: tuple
    editable: bool
    selected: bool
    active: bool
    triangles: tuple
    boundary: tuple
    area: float
    center: complex
    flags: int
    storage: bytes
    cluster: bytes
    stretch_ignored: bool
    topology: UVTopology
    spatial_triangles: tuple

    @property
    def snap_id(self):
        return _group_id(self.storage)

    @property
    def cluster_id(self):
        return _group_id(self.cluster)

    @cached_property
    def key(self):
        return self.state.mesh.as_pointer(), self.faces[0]

    @cached_property
    def contour(self):
        return contour_from_edges(self.boundary)

    @cached_property
    def surface_area(self):
        return sum((b - a).cross(c - a).length / 2 for a, b, c in self.spatial_triangles)

    @cached_property
    def topology_key(self):
        vertices = tuple(vertex for vertex, _ in self.topology.vertices)
        return blake2s(repr((self.faces, vertices, self.topology.faces)).encode(), digest_size=12).hexdigest()


@dataclass
class Group:
    key: object
    islands: list
    available: bool

    @property
    def visible(self):
        return any(island.visible_faces for island in self.islands)

    @property
    def selected(self):
        return any(island.selected for island in self.islands)

    @cached_property
    def flags(self):
        flags = 0
        for island in self.islands:
            flags |= island.flags
        return flags

    @cached_property
    def anchors(self):
        return distinct_anchors([island.center for island in self.islands if island.flags & POSITION])

    @cached_property
    def representative(self):
        preferred = [island for island in self.islands if island.selected]
        return min(preferred or self.islands, key=lambda island: (
            not bool(island.flags & POSITION), not island.active, -island.area,
            island.state.mesh.name_full, island.faces[0],
        ))

    def unit(self):
        # Count overlapped Snap members once and retain the full cluster footprint.
        layers = {}
        for island in self.islands:
            key = island.snap_id or island.key
            if key not in layers or island.area > layers[key].area:
                layers[key] = island
        return Unit(
            self.key, tuple(chain.from_iterable(island.triangles for island in self.islands)),
            self.anchors[0] if self.anchors else self.representative.center,
            sum(island.area for island in layers.values()), self.flags, self.anchors,
            tuple(chain.from_iterable(island.boundary for island in self.islands)),
            sum(island.surface_area for island in layers.values()),
        )


@dataclass
class Snapshot:
    islands: list
    groups: list
    clusters: list
    packing_groups: list

    def signature(self):
        return (
            tuple((island.key, island.state.uv_name, island.faces, island.visible_faces,
                   island.editable, island.selected, island.triangles, island.flags, island.storage,
                   island.cluster, island.surface_area)
                  for island in self.islands),
            tuple((group.key, group.available) for group in self.packing_groups),
        )


def _mesh_islands(obj, settings):
    mesh = obj.data
    bm = bmesh.from_edit_mesh(mesh)
    uv = bm.loops.layers.uv.active
    if uv is None:
        return None, []
    state = MeshState(mesh, uv.name, *_layer_names(uv.name))
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    flags_layer = bm.faces.layers.int.get(state.lock_name)
    stack_layer = bm.faces.layers.string.get(state.stack_name)
    cluster_layer = bm.faces.layers.string.get(state.cluster_name)
    ignore_layer = bm.faces.layers.int.get(state.ignore_name)
    faces = list(bm.faces)
    if not faces:
        return state, []
    bm.verts.index_update()
    sync = settings.use_uv_select_sync
    uv_selection_available = not sync or bm.uv_select_sync_valid
    modes = _selection_modes(settings)
    active_face = bm.faces.active
    members = [face[stack_layer] if stack_layer is not None else b"" for face in faces]
    clusters = [face[cluster_layer] if cluster_layer is not None else b"" for face in faces]
    flags = [face[flags_layer] if flags_layer is not None else 0 for face in faces]
    parents = list(range(len(faces)))
    component_member = members.copy()
    points = {}
    per_face_edges = [[] for _ in faces]
    edge_faces = defaultdict(list)

    def root(index):
        while index != parents[index]:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def join(left, right):
        a, b = sorted((root(left), root(right)))
        if a == b or component_member[a] != component_member[b] or clusters[a] != clusters[b]:
            return
        parents[b] = a
        component_member[a] = component_member[a] or component_member[b]

    for face in faces:
        for loop in face.loops:
            coordinate = loop[uv].uv
            point = complex(*coordinate)
            if not isfinite(point.real) or not isfinite(point.imag):
                raise ValueError(f"Некорректные UV-координаты в объекте {mesh.name_full}")
            points[loop] = point
        for loop in face.loops:
            a, b = points[loop], points[loop.link_loop_next]
            if loop.vert != loop.edge.verts[0]:
                a, b = b, a
            key = (loop.edge, a, b)
            neighbors = edge_faces[key]
            for neighbor in neighbors:
                join(neighbor, face.index)
            neighbors.append(face.index)
            per_face_edges[face.index].append(key)

    components = defaultdict(list)
    for index in range(len(faces)):
        components[root(index)].append(index)
    face_triangles = defaultdict(list)
    spatial_triangles = defaultdict(list)
    world = obj.matrix_world.to_3x3()
    coords = {vertex.index: world @ vertex.co for vertex in bm.verts}
    for loops in bm.calc_loop_triangles():
        index = loops[0].face.index
        face_triangles[index].append(tuple(points[loop] for loop in loops))
        spatial_triangles[index].append(tuple(coords[loop.vert.index] for loop in loops))

    islands = []
    for start, indices in components.items():
        visible = tuple(i for i in indices if not faces[i].hide and (sync or faces[i].select))
        selected = any(_face_selected(faces[i], uv_selection_available, modes) for i in visible)
        active = active_face is not None and active_face.index in visible
        boundary = tuple(
            (edge[1], edge[2]) for i in indices for edge in per_face_edges[i]
            if sum(root(other) == start for other in edge_faces[edge]) == 1
        )
        triangles = tuple(tri for i in indices for tri in face_triangles[i])
        spatial = tuple(tri for i in indices for tri in spatial_triangles[i])
        corners = [points[loop] for i in indices for loop in faces[i].loops]
        nodes = {}
        face_cycles = tuple(tuple(
            nodes.setdefault((loop.vert.index, points[loop]), len(nodes)) for loop in faces[i].loops
        ) for i in indices)
        area, center = area_center(triangles, corners)
        # A degenerate island still acts as an obstacle. Retain its vertices.
        if not triangles:
            triangles = tuple((point, point, point) for point in corners)
        lock_bits = 0
        for index in indices:
            lock_bits |= flags[index]
        islands.append(Island(
            state, tuple(indices), visible, bool(visible) and all(not faces[i].hide for i in indices),
            selected, active, triangles, boundary, area, center, lock_bits, component_member[start],
            clusters[start], ignore_layer is not None and any(faces[i][ignore_layer] for i in indices),
            UVTopology(tuple(nodes), face_cycles), spatial,
        ))
    return state, islands


def _external_groups(states, ids, suffix, field):
    if not ids:
        return set()
    current = {(state.mesh.as_pointer(), getattr(state, field)) for state in states}
    external = set()
    for mesh in bpy.data.meshes:
        if not mesh.users:
            continue
        pointer = mesh.as_pointer()
        if mesh.is_editmode:
            bm = bmesh.from_edit_mesh(mesh)
            layers = bm.faces.layers.string
            values = (
                face[layers[name]] for name in layers.keys()
                if name.startswith(_PREFIX) and name.endswith(suffix) and (pointer, name) not in current
                for face in bm.faces
            )
        else:
            values = (
                item.value for attribute in mesh.attributes
                if attribute.domain == "FACE" and attribute.data_type == "STRING"
                and attribute.name.startswith(_PREFIX) and attribute.name.endswith(suffix)
                and (pointer, attribute.name) not in current
                for item in attribute.data
            )
        for value in values:
            if isinstance(value, str):
                value = value.encode("ascii", errors="ignore")
            group = _group_id(value)
            if group in ids:
                external.add(group)
        if external == ids:
            break
    return external


def read_snapshot(context):
    islands = []
    states = []
    objects = sorted(context.objects_in_mode_unique_data, key=lambda obj: obj.name_full)
    for obj in objects:
        if obj.type == "MESH":
            state, parts = _mesh_islands(obj, context.tool_settings)
            if state is not None:
                states.append(state)
                islands.extend(parts)
    by_snap = defaultdict(list)
    by_cluster = defaultdict(list)
    for island in islands:
        by_snap[island.snap_id or island.key].append(island)
        if island.cluster_id:
            by_cluster[island.cluster_id].append(island)
    ext_snap = _external_groups(states, {key for key in by_snap if isinstance(key, bytes)}, _STACK, "stack_name")
    ext_cluster = _external_groups(states, set(by_cluster), _CLUSTER, "cluster_name")
    groups = [Group(key, parts, key not in ext_snap and all(i.editable for i in parts))
              for key, parts in by_snap.items()]
    clusters = [Group(key, parts, key not in ext_cluster and all(i.editable for i in parts))
                for key, parts in by_cluster.items()]
    # Build connected packing units even for junctions created by older meshes or copies.
    by_island = defaultdict(list)
    for group in groups + clusters:
        for island in group.islands:
            by_island[island.key].append(group)
    handled = set()
    packing_groups = []
    for group in groups:
        if id(group) in handled:
            continue
        pending = [group]
        parts = {}
        available = True
        while pending:
            connected = pending.pop()
            if id(connected) in handled:
                continue
            handled.add(id(connected))
            available &= connected.available
            for island in connected.islands:
                if island.key not in parts:
                    parts[island.key] = island
                    pending.extend(by_island[island.key])
        packing_groups.append(Group(group.key, list(parts.values()), available))
    return Snapshot(islands, groups, clusters, packing_groups)


def select_islands(islands, settings, clear=(), select=True):
    by_mesh = defaultdict(list)
    clear_by_mesh = defaultdict(list)
    for island in islands:
        by_mesh[island.state.mesh].extend(island.visible_faces)
    for island in clear:
        clear_by_mesh[island.state.mesh].extend(island.visible_faces)
    for mesh in by_mesh.keys() | clear_by_mesh.keys():
        bm = bmesh.from_edit_mesh(mesh)
        sync = settings.use_uv_select_sync
        if sync and not bm.uv_select_sync_valid:
            bm.uv_select_sync_from_mesh(sticky_select_mode=settings.uv_sticky_select_mode)
        bm.faces.ensure_lookup_table()
        for index in clear_by_mesh[mesh]:
            bm.faces[index].uv_select_set(False)
        for index in by_mesh[mesh]:
            bm.faces[index].uv_select_set(select)
        if sync:
            bm.uv_select_flush_mode(flush_down=True)
            bm.uv_select_sync_to_mesh()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)


def selection_locks(context):
    """Returns flags shared by selected faces, for the panel's toggle indicators."""
    common = 7
    any_selected = False
    settings = context.tool_settings
    modes = _selection_modes(settings)
    for obj in context.objects_in_mode_unique_data:
        bm = bmesh.from_edit_mesh(obj.data)
        uv = bm.loops.layers.uv.active
        if uv is None:
            continue
        layer = bm.faces.layers.int.get(_layer_names(uv.name)[0])
        sync = settings.use_uv_select_sync
        uv_selection_available = not sync or bm.uv_select_sync_valid
        for face in bm.faces:
            if face.hide or (not sync and not face.select):
                continue
            if _face_selected(face, uv_selection_available, modes):
                common &= face[layer] if layer is not None else 0
                any_selected = True
                if not common:
                    return 0
    return common if any_selected else 0


def apply_changes(islands, transforms=None, locks=None, memberships=None, clusters=None,
                  ignored=None, uv_targets=None):
    """Commit an already validated edit and roll back if a write fails."""
    transforms = transforms or {}
    locks = locks or {}
    memberships = memberships or {}
    clusters = clusters or {}
    ignored = ignored or {}
    uv_targets = uv_targets or {}
    by_mesh = defaultdict(list)
    changed_keys = transforms.keys() | locks.keys() | memberships.keys() | clusters.keys() | ignored.keys() | uv_targets.keys()
    for island in islands:
        if island.key in changed_keys:
            by_mesh[island.state].append(island)
    backup = defaultdict(list)
    created = defaultdict(list)
    try:
        for state, parts in by_mesh.items():
            bm = state.bm
            edits = (
                (bm.faces.layers.int, state.lock_name, locks),
                (bm.faces.layers.string, state.stack_name, memberships),
                (bm.faces.layers.string, state.cluster_name, clusters),
                (bm.faces.layers.int, state.ignore_name, ignored),
            )
            for collection, name, requested in edits:
                if any(island.key in requested for island in parts) and collection.get(name) is None:
                    collection.new(name)
                    created[state].append((name, requested is locks or requested is ignored))
            # Adding a custom layer invalidates previously obtained BMesh element handles.
            bm.faces.ensure_lookup_table()
            uv = bm.loops.layers.uv.get(state.uv_name)
            layers = [(collection.get(name), requested) for collection, name, requested in edits]
            for island in parts:
                transform = transforms.get(island.key)
                targets = uv_targets.get(island.key)
                for index in island.faces:
                    face = bm.faces[index]
                    previous_uvs = tuple(tuple(loop[uv].uv) for loop in face.loops) if transform or targets else None
                    values = tuple((i, face[layer]) for i, (layer, requested) in enumerate(layers)
                                   if island.key in requested)
                    backup[state].append((index, previous_uvs, values))
                    if previous_uvs is not None:
                        for loop, coords in zip(face.loops, previous_uvs):
                            point = complex(*coords)
                            point = targets[(loop.vert.index, point)] if targets else transform(point)
                            loop[uv].uv = (point.real, point.imag)
                    for i, _ in values:
                        layer, requested = layers[i]
                        face[layer] = requested[island.key]
        for state in by_mesh:
            bmesh.update_edit_mesh(state.mesh, loop_triangles=False, destructive=False)
    except Exception:
        for state in backup.keys() | created.keys():
            bm = state.bm
            bm.faces.ensure_lookup_table()
            uv = bm.loops.layers.uv.get(state.uv_name)
            layers = (bm.faces.layers.int.get(state.lock_name), bm.faces.layers.string.get(state.stack_name),
                      bm.faces.layers.string.get(state.cluster_name), bm.faces.layers.int.get(state.ignore_name))
            for index, coords, values in backup[state]:
                face = bm.faces[index]
                if coords is not None:
                    for loop, coordinate in zip(face.loops, coords):
                        loop[uv].uv = coordinate
                for i, value in values:
                    face[layers[i]] = value
            for name, is_lock in created[state]:
                collection = bm.faces.layers.int if is_lock else bm.faces.layers.string
                collection.remove(collection.get(name))
            bmesh.update_edit_mesh(state.mesh, loop_triangles=False, destructive=False)
        raise
