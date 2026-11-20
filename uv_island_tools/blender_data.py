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

from .geometry import POSITION, area_center, contour_from_edges, distinct_anchors
from .packing import Unit


_PREFIX = ".uvit_v1_"
_STACK = "_stack"


def _layer_names(uv_name):
    suffix = blake2s(uv_name.encode("utf-8"), digest_size=10).hexdigest()
    return _PREFIX + suffix + "_locks", _PREFIX + suffix + _STACK


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


def membership(group, island):
    previous = island.storage.partition(b":")[2] if island.storage else b""
    return group + b":" + (previous or group_token())


@dataclass(frozen=True)
class MeshState:
    mesh: object
    uv_name: str
    lock_name: str
    stack_name: str

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

    @cached_property
    def key(self):
        return self.state.mesh.as_pointer(), self.faces[0]

    @cached_property
    def contour(self):
        return contour_from_edges(self.boundary)


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
        # Stacked islands often cover the same area. Use their largest member as
        # the search's area estimate and retain all triangles for collisions.
        return Unit(
            self.key, tuple(chain.from_iterable(island.triangles for island in self.islands)),
            self.anchors[0] if self.anchors else self.representative.center,
            max(island.area for island in self.islands), self.flags, self.anchors,
            tuple(chain.from_iterable(island.boundary for island in self.islands)),
        )


@dataclass
class Snapshot:
    islands: list
    groups: list

    def signature(self):
        return (
            tuple((island.key, island.state.uv_name, island.faces, island.visible_faces,
                   island.editable, island.selected, island.triangles, island.flags, island.storage)
                  for island in self.islands),
            tuple((group.key, group.available) for group in self.groups),
        )


def _mesh_islands(mesh, settings):
    bm = bmesh.from_edit_mesh(mesh)
    uv = bm.loops.layers.uv.active
    if uv is None:
        return None, []
    state = MeshState(mesh, uv.name, *_layer_names(uv.name))
    bm.faces.index_update()
    bm.faces.ensure_lookup_table()
    flags_layer = bm.faces.layers.int.get(state.lock_name)
    stack_layer = bm.faces.layers.string.get(state.stack_name)
    faces = list(bm.faces)
    if not faces:
        return state, []
    sync = settings.use_uv_select_sync
    uv_selection_available = not sync or bm.uv_select_sync_valid
    modes = _selection_modes(settings)
    active_face = bm.faces.active
    members = [face[stack_layer] if stack_layer is not None else b"" for face in faces]
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
        if a == b or component_member[a] != component_member[b]:
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
    for loops in bm.calc_loop_triangles():
        face_triangles[loops[0].face.index].append(tuple(points[loop] for loop in loops))

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
        corners = [points[loop] for i in indices for loop in faces[i].loops]
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
        ))
    return state, islands


def _external_groups(states, ids):
    if not ids:
        return set()
    current = {(state.mesh.as_pointer(), state.stack_name) for state in states}
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
                if name.startswith(_PREFIX) and name.endswith(_STACK) and (pointer, name) not in current
                for face in bm.faces
            )
        else:
            values = (
                item.value for attribute in mesh.attributes
                if attribute.domain == "FACE" and attribute.data_type == "STRING"
                and attribute.name.startswith(_PREFIX) and attribute.name.endswith(_STACK)
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
            state, parts = _mesh_islands(obj.data, context.tool_settings)
            if state is not None:
                states.append(state)
                islands.extend(parts)
    by_group = defaultdict(list)
    for island in islands:
        by_group[_group_id(island.storage) or island.key].append(island)
    external = _external_groups(states, {key for key in by_group if isinstance(key, bytes)})
    groups = [Group(key, parts, key not in external and all(i.editable for i in parts))
              for key, parts in by_group.items()]
    return Snapshot(islands, groups)


def select_islands(islands, settings):
    by_mesh = defaultdict(list)
    for island in islands:
        by_mesh[island.state.mesh].extend(island.visible_faces)
    for mesh, indices in by_mesh.items():
        bm = bmesh.from_edit_mesh(mesh)
        sync = settings.use_uv_select_sync
        if sync and not bm.uv_select_sync_valid:
            bm.uv_select_sync_from_mesh(sticky_select_mode=settings.uv_sticky_select_mode)
        bm.faces.ensure_lookup_table()
        for index in indices:
            bm.faces[index].uv_select_set(True)
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


def apply_changes(islands, transforms=None, locks=None, memberships=None):
    """Commit an already validated edit and roll back if a write fails."""
    transforms = transforms or {}
    locks = locks or {}
    memberships = memberships or {}
    by_mesh = defaultdict(list)
    changed_keys = transforms.keys() | locks.keys() | memberships.keys()
    for island in islands:
        if island.key in changed_keys:
            by_mesh[island.state].append(island)
    backup = defaultdict(list)
    created = defaultdict(list)
    try:
        for state, parts in by_mesh.items():
            bm = state.bm
            for collection, name, requested in (
                (bm.faces.layers.int, state.lock_name, locks),
                (bm.faces.layers.string, state.stack_name, memberships),
            ):
                if any(island.key in requested for island in parts) and collection.get(name) is None:
                    collection.new(name)
                    created[state].append((name, requested is locks))
            # Adding a custom layer invalidates previously obtained BMesh element handles.
            bm.faces.ensure_lookup_table()
            uv = bm.loops.layers.uv.get(state.uv_name)
            lock_layer = bm.faces.layers.int.get(state.lock_name)
            stack_layer = bm.faces.layers.string.get(state.stack_name)
            for island in parts:
                for index in island.faces:
                    face = bm.faces[index]
                    previous_uvs = tuple(tuple(loop[uv].uv) for loop in face.loops) if island.key in transforms else None
                    previous_lock = face[lock_layer] if island.key in locks else None
                    previous_stack = face[stack_layer] if island.key in memberships else None
                    backup[state].append((index, previous_uvs, previous_lock, previous_stack))
                    if previous_uvs is not None:
                        transform = transforms[island.key]
                        for loop, coords in zip(face.loops, previous_uvs):
                            point = transform(complex(*coords))
                            loop[uv].uv = (point.real, point.imag)
                    if previous_lock is not None:
                        face[lock_layer] = locks[island.key]
                    if previous_stack is not None:
                        face[stack_layer] = memberships[island.key]
        for state in by_mesh:
            bmesh.update_edit_mesh(state.mesh, loop_triangles=False, destructive=False)
    except Exception:
        for state in backup.keys() | created.keys():
            bm = state.bm
            bm.faces.ensure_lookup_table()
            uv = bm.loops.layers.uv.get(state.uv_name)
            lock_layer = bm.faces.layers.int.get(state.lock_name)
            stack_layer = bm.faces.layers.string.get(state.stack_name)
            for index, coords, flags, member in backup[state]:
                face = bm.faces[index]
                if coords is not None:
                    for loop, coordinate in zip(face.loops, coords):
                        loop[uv].uv = coordinate
                if flags is not None:
                    face[lock_layer] = flags
                if member is not None:
                    face[stack_layer] = member
            for name, is_lock in created[state]:
                collection = bm.faces.layers.int if is_lock else bm.faces.layers.string
                collection.remove(collection.get(name))
            bmesh.update_edit_mesh(state.mesh, loop_triangles=False, destructive=False)
        raise
