"""Selection tools for redundant N-gon vertices and self-intersecting UVs."""

import math

import bmesh
import bpy
from bpy.props import FloatProperty

from . import blender_data as data
from .i18n import tr
from .operators import _UVOperator
from .packing import Triangle, _proper_crossing, triangles_conflict


def _redundant_vertex(vertex, limit):
    if len(vertex.link_edges) != 2:
        return False
    left, right = (edge.other_vert(vertex).co - vertex.co for edge in vertex.link_edges)
    lengths = left.length * right.length
    return lengths > 0 and left.dot(right) <= -limit * lengths


def select_stray_vertices(context, tolerance):
    """Select collinear degree-two vertices used by visible N-gons."""
    settings = context.tool_settings
    sync = settings.use_uv_select_sync
    if sync:
        settings.mesh_select_mode = (True, False, False)
    else:
        settings.uv_select_mode = "VERTEX"
    cos_limit = math.cos(tolerance)
    count = 0
    for obj in context.objects_in_mode_unique_data:
        if obj.type != "MESH":
            continue
        mesh = obj.data
        bm = bmesh.from_edit_mesh(mesh)
        if bm.loops.layers.uv.active is None:
            continue
        if sync and not bm.uv_select_sync_valid:
            bm.uv_select_sync_from_mesh(sticky_select_mode=settings.uv_sticky_select_mode)
        visible = [face for face in bm.faces if not face.hide and (sync or face.select)]
        candidates = {vert for face in visible if len(face.verts) > 4 for vert in face.verts if not vert.hide}
        stray = {vert for vert in candidates if _redundant_vertex(vert, cos_limit)}
        count += len(stray)
        for face in visible:
            face.uv_select_set(False)
        for face in visible:
            for loop in face.loops:
                if loop.vert in stray:
                    loop.uv_select_vert_set(True)
        bm.uv_select_flush_mode()
        if sync:
            bm.uv_select_sync_to_mesh()
        bmesh.update_edit_mesh(mesh, loop_triangles=False, destructive=False)
    return count


def _crossed_face(topology):
    for face in topology.faces:
        if len(face) < 4:
            continue
        points = [topology.vertices[index][1] for index in face]
        edges = tuple(zip(points, points[1:] + points[:1]))
        for index, (a, b) in enumerate(edges[:-2]):
            end = len(edges) - (index == 0)
            if any(_proper_crossing(a, b, c, d) for c, d in edges[index + 2:end]):
                return True
    return False


def has_self_intersection(island):
    """Detect crossed polygon edges or positive-area UV overlap within one island."""
    if _crossed_face(island.topology):
        return True
    triangles = [triangle for points in island.triangles
                 if (triangle := Triangle.from_points(points)).nondegenerate]
    if len(triangles) < 2:
        return False

    def span_score(axis):
        total = max(t.box[axis + 2] for t in triangles) - min(t.box[axis] for t in triangles)
        return sum(t.box[axis + 2] - t.box[axis] for t in triangles) / total

    axis = min((0, 1), key=span_score)
    other = 1 - axis
    pending = []
    for triangle in sorted(triangles, key=lambda t: t.box[axis]):
        box = triangle.box
        pending = [peer for peer in pending if peer.box[axis + 2] > box[axis]]
        for peer in pending:
            if (peer.box[other + 2] > box[other] and box[other + 2] > peer.box[other]
                    and triangles_conflict(triangle, peer, 0j, 0)):
                return True
        pending.append(triangle)
    return False


class UVIT_OT_find_stray(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_find_stray"
    bl_label = "Find Stray Vertices"
    bl_description = "Select redundant collinear vertices on N-gons"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        count = select_stray_vertices(context, context.scene.uvit_stray_angle)
        self.report({"INFO"}, tr("Vertices found: {count}", count=count))
        return {"FINISHED"}


class UVIT_OT_find_self_intersections(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_find_self_intersections"
    bl_label = "Find UV Self-Intersections"
    bl_description = "Select islands with crossed UV edges or overlapping UV faces"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            visible = [island for island in data.read_snapshot(context).islands if island.visible_faces]
            matches = [island for island in visible if has_self_intersection(island)]
            data.select_islands(matches, context.tool_settings, clear=visible)
        except ValueError as error:
            return self.warn(str(error))
        self.report({"INFO"}, tr("Islands found: {count}", count=len(matches)))
        return {"FINISHED"}


class UVIT_PT_diagnostics(bpy.types.Panel):
    bl_label = ""
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_parent_id = "UVIT_PT_tools"
    bl_options = {"DEFAULT_CLOSED"}

    def draw_header(self, _context):
        self.layout.label(text=tr("UV Diagnostics"), translate=False)

    def draw(self, context):
        layout = self.layout
        layout.enabled = not context.window_manager.uvit_runtime.running
        layout.prop(context.scene, "uvit_stray_angle", text=tr("Angle tolerance"), translate=False)
        layout.operator(UVIT_OT_find_stray.bl_idname, text=tr("Find Stray Vertices"), translate=False)
        layout.operator(UVIT_OT_find_self_intersections.bl_idname, text=tr("Find UV Self-Intersections"), translate=False)


_CLASSES = (UVIT_OT_find_stray, UVIT_OT_find_self_intersections, UVIT_PT_diagnostics)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.uvit_stray_angle = FloatProperty(
        name="Angle tolerance", description="Allowed deviation from a straight edge",
        subtype="ANGLE", default=math.radians(0.1), min=0, max=math.radians(10),
    )


def unregister():
    del bpy.types.Scene.uvit_stray_angle
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
