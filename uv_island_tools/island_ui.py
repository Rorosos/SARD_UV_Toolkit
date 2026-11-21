"""Cluster management and UV stretch inspection in the UV Editor."""

import math

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import blender_data as data
from .geometry import stretch_percent
from .operators import _UVOperator


class UVIT_ClusterRow(bpy.types.PropertyGroup):
    token: StringProperty()
    count: IntProperty()
    available: BoolProperty()


class UVIT_StretchRow(bpy.types.PropertyGroup):
    mesh: StringProperty()
    uv_name: StringProperty()
    topology: StringProperty()
    first_face: IntProperty()
    percent: StringProperty()
    ignored: BoolProperty()


class UVIT_IslandLists(bpy.types.PropertyGroup):
    clusters: CollectionProperty(type=UVIT_ClusterRow)
    cluster_index: IntProperty(min=0)
    stretch: CollectionProperty(type=UVIT_StretchRow)
    stretch_index: IntProperty(min=0)


def _refresh_clusters(state, snapshot, active=b""):
    state.clusters.clear()
    state.cluster_index = 0
    for index, cluster in enumerate(snapshot.clusters):
        row = state.clusters.add()
        row.token = cluster.key.decode("ascii")
        row.count = len(cluster.islands)
        row.available = cluster.available
        if cluster.key == active:
            state.cluster_index = index


def _cluster_updates(snapshot, action, active):
    clusters = {group.key: group for group in snapshot.clusters}
    if action == "MERGE":
        groups = [group for group in snapshot.packing_groups if group.selected]
        if not groups or any(not group.available for group in groups):
            raise ValueError("Выделите доступные острова и откройте все части их групп")
        islands = [island for group in groups for island in group.islands]
        if len({i.snap_id or i.key for i in islands}) < 2:
            raise ValueError("Для кластера выделите хотя бы два острова или две Snap-группы")
        existing = {island.cluster_id for island in islands if island.cluster_id}
        token = active if active in existing else min(existing) if existing else data.group_token()
        return {i.key: data.membership(token, i.cluster) for i in islands if i.cluster_id != token}, token

    if action == "REMOVE":
        selected = [group for group in snapshot.groups if group.selected]
        leaving = {i.key for group in selected for i in group.islands if i.cluster_id}
        touched = [cluster for cluster in clusters.values() if any(i.key in leaving for i in cluster.islands)]
        if not touched:
            raise ValueError("Выделите острова, входящие в кластер")
        if any(not cluster.available for cluster in touched) or any(
                not group.available for group in selected if any(i.key in leaving for i in group.islands)):
            raise ValueError("Откройте все части затронутых кластеров и Snap-групп")
        for cluster in touched:
            if len({i.snap_id or i.key for i in cluster.islands if i.key not in leaving}) < 2:
                leaving.update(i.key for i in cluster.islands)
        return dict.fromkeys(leaving, b""), active

    cluster = clusters.get(active)
    if cluster is None or not cluster.available:
        raise ValueError("Выберите доступный кластер в таблице")
    return {i.key: b"" for i in cluster.islands}, b""


class UVIT_OT_cluster(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_cluster"
    bl_label = "Кластеры UV"
    bl_options = {"UNDO"}

    action: EnumProperty(items=[
        ("REFRESH", "Обновить список", "Показать кластеры открытых UV-карт"),
        ("MERGE", "Объединить в кластер", "Создать кластер, добавить острова или объединить выделенные кластеры"),
        ("SELECT", "Выделить кластер", "Выделить острова строки таблицы"),
        ("REMOVE", "Убрать выделенные", "Убрать выделенные острова из кластеров"),
        ("DISSOLVE", "Расформировать", "Разъединить все острова выбранного кластера"),
    ])

    def execute(self, context):
        state = context.window_manager.uvit_island_lists
        row = state.clusters[state.cluster_index] if state.cluster_index < len(state.clusters) else None
        active = row.token.encode("ascii") if row else b""
        try:
            snapshot = data.read_snapshot(context)
            if self.action == "SELECT":
                cluster = next((group for group in snapshot.clusters if group.key == active), None)
                if cluster is None:
                    return self.warn("Выберите кластер в таблице и обновите список при необходимости")
                data.select_islands(cluster.islands, context.tool_settings, clear=snapshot.islands)
            elif self.action != "REFRESH":
                updates, active = _cluster_updates(snapshot, self.action, active)
                if not updates:
                    return self.warn("Все выделенные острова уже входят в этот кластер")
                data.apply_changes(snapshot.islands, clusters=updates)
                snapshot = data.read_snapshot(context)
            _refresh_clusters(state, snapshot, active)
        except ValueError as error:
            return self.warn(str(error))
        return {"FINISHED"}


class UVIT_UL_clusters(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, _index):
        row = layout.row()
        row.label(text=f"Кластер {item.token[:8]}", icon="GROUP_UVS")
        row.label(text=str(item.count), icon="NONE" if item.available else "LOCKED")


class UVIT_PT_clusters(bpy.types.Panel):
    bl_label = "Кластеры UV"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_parent_id = "UVIT_PT_tools"
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        layout = self.layout
        layout.enabled = not context.window_manager.uvit_runtime.running
        state = context.window_manager.uvit_island_lists
        layout.operator(UVIT_OT_cluster.bl_idname, text="Объединить в кластер").action = "MERGE"
        row = layout.row(align=True)
        row.label(text="Кластер / острова")
        row.operator(UVIT_OT_cluster.bl_idname, text="", icon="FILE_REFRESH").action = "REFRESH"
        layout.template_list(UVIT_UL_clusters.__name__, "", state, "clusters", state, "cluster_index", rows=3)
        layout.operator(UVIT_OT_cluster.bl_idname, text="Выделить кластер").action = "SELECT"
        layout.operator(UVIT_OT_cluster.bl_idname, text="Убрать выделенные").action = "REMOVE"
        layout.operator(UVIT_OT_cluster.bl_idname, text="Расформировать").action = "DISSOLVE"


class UVIT_OT_stretch_scan(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_stretch_scan"
    bl_label = "Найти растянутые острова"
    bl_description = "Показать острова от заданного порога и выделить все, кроме игнорируемых"
    bl_options = {"UNDO"}

    def execute(self, context):
        state = context.window_manager.uvit_island_lists
        settings = context.scene.uvit_settings
        aspect = settings.texture_width / settings.texture_height
        threshold = context.scene.uvit_stretch_threshold
        try:
            snapshot = data.read_snapshot(context)
            matches = []
            for island in snapshot.islands:
                if not island.visible_faces:
                    continue
                percent = stretch_percent(island.spatial_triangles, island.triangles, aspect)
                if percent is not None and percent + 1e-8 >= threshold:
                    matches.append((percent, island))
            matches.sort(key=lambda entry: -entry[0])
            selected = [island for _, island in matches if not island.stretch_ignored]
            data.select_islands(selected, context.tool_settings, clear=snapshot.islands)
            state.stretch.clear()
            state.stretch_index = 0
            for percent, island in matches:
                row = state.stretch.add()
                row.mesh = island.state.mesh.name_full
                row.uv_name = island.state.uv_name
                row.topology = island.topology_key
                row.first_face = island.faces[0]
                row.percent = "∞" if math.isinf(percent) else f"{percent:.1f}%"
                row.ignored = island.stretch_ignored
        except ValueError as error:
            return self.warn(str(error))
        self.report({"INFO"}, f"Найдено: {len(matches)}. Выделено: {len(selected)}")
        return {"FINISHED"}


class UVIT_OT_stretch_ignore(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_stretch_ignore"
    bl_label = "Переключить игнорирование"
    bl_description = "Сохранить остров в отчёте и исключить его из автовыделения или вернуть в выделение"
    bl_options = {"UNDO"}

    row_index: IntProperty(default=-1, options={"HIDDEN", "SKIP_SAVE"})

    def execute(self, context):
        state = context.window_manager.uvit_island_lists
        index = state.stretch_index if self.row_index < 0 else self.row_index
        if index >= len(state.stretch):
            return self.warn("Сначала найдите растянутые острова")
        row = state.stretch[index]
        try:
            snapshot = data.read_snapshot(context)
            island = next((item for item in snapshot.islands if item.state.mesh.name_full == row.mesh
                           and item.state.uv_name == row.uv_name and item.faces[0] == row.first_face
                           and item.topology_key == row.topology), None)
            if island is None or not island.editable:
                return self.warn("Остров изменился или скрыт. Обновите таблицу")
            ignored = not island.stretch_ignored
            data.apply_changes([island], ignored={island.key: int(ignored)})
            data.select_islands([island], context.tool_settings, select=not ignored)
            row.ignored = ignored
        except ValueError as error:
            return self.warn(str(error))
        return {"FINISHED"}


class UVIT_UL_stretch(bpy.types.UIList):
    def draw_item(self, _context, layout, _data, item, _icon, _active_data, _active_propname, index):
        row = layout.row(align=True)
        row.label(text=f"{item.mesh} · {item.first_face + 1}")
        row.label(text=item.percent)
        row.operator(UVIT_OT_stretch_ignore.bl_idname, text="",
                     icon="HIDE_ON" if item.ignored else "HIDE_OFF").row_index = index


class UVIT_PT_stretch(bpy.types.Panel):
    bl_label = "Растяжение UV"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "UV Stretch"

    @classmethod
    def poll(cls, context):
        return data.is_uv_edit(context)

    def draw(self, context):
        layout = self.layout
        layout.enabled = not context.window_manager.uvit_runtime.running
        state = context.window_manager.uvit_island_lists
        layout.prop(context.scene, "uvit_stretch_threshold")
        layout.operator(UVIT_OT_stretch_scan.bl_idname, icon="VIEWZOOM")
        layout.label(text="Остров / растяжение / игнор")
        layout.template_list(UVIT_UL_stretch.__name__, "", state, "stretch", state, "stretch_index", rows=5)


_CLASSES = (
    UVIT_ClusterRow, UVIT_StretchRow, UVIT_IslandLists,
    UVIT_OT_cluster, UVIT_UL_clusters, UVIT_PT_clusters,
    UVIT_OT_stretch_scan, UVIT_OT_stretch_ignore, UVIT_UL_stretch, UVIT_PT_stretch,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.WindowManager.uvit_island_lists = PointerProperty(type=UVIT_IslandLists, options={"SKIP_SAVE"})
    bpy.types.Scene.uvit_stretch_threshold = FloatProperty(
        name="Порог", description="Максимальное направленное растяжение UV на треугольнике, в процентах",
        subtype="PERCENTAGE", default=10.0, min=0.0, soft_max=100.0,
    )


def unregister():
    del bpy.types.Scene.uvit_stretch_threshold
    del bpy.types.WindowManager.uvit_island_lists
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
