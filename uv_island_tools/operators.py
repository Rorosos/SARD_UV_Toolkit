"""Blender operators, scene settings and UV Editor panel."""

import time
from random import getrandbits

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import blender_data as data
from . import packing
from .cuda_backend import CudaBackend
from .geometry import EPSILON, POSITION, ROTATION, SCALE, match_islands, vertex_correspondence
from .gpu_backend import AutoBackend, GPUBackend, GPUUnavailable, HybridBackend
from .i18n import draw_language, enum_items, tr
from .native_cpu import NativeCPUBackend


def _apply_preset(self, _context):
    preset = packing.PRESETS.get(self.resolution)
    if preset is not None:
        side, self.gap, self.border = preset
        self.texture_width = side
        self.texture_height = side


class UVIT_Settings(bpy.types.PropertyGroup):
    resolution: EnumProperty(
        name="Resolution", default=2, update=_apply_preset,
        items=enum_items([
            (key, f"{side} × {side}", f"{gap} px / {border} px")
            for key, (side, gap, border) in packing.PRESETS.items()
        ] + [("CUSTOM", "Custom resolution", "")]),
    )
    texture_width: IntProperty(name="Width (px)", default=2048, min=1, max=32768)
    texture_height: IntProperty(name="Height (px)", default=2048, min=1, max=32768)
    gap: IntProperty(name="Gap (px)", description="Minimum clearance between island shapes",
                     default=16, min=0, max=16384)
    border: IntProperty(name="Border (px)", description="Minimum clearance from the UV tile edge",
                        default=8, min=0, max=16384)
    scope: EnumProperty(
        name="Islands", default=0,
        items=enum_items([("SELECTED", "Selected", ""), ("VISIBLE", "All visible", "")]),
    )
    passes: IntProperty(name="Passes", default=packing.DEFAULT_PASSES, min=1, max=1000, soft_max=200,
                        description="Number of layout attempts with varied positions, angles and island order")
    backend: EnumProperty(
        name="Compute", default=0,
        items=enum_items([
            ("AUTO", "Automatic", ""),
            ("GPU", "Blender GPU", "OpenGL / Vulkan"),
            ("CPU", "CPU", ""),
            ("CUDA", "CUDA", "NVIDIA"),
            ("HYBRID", "CPU + GPU", ""),
        ]),
    )
    allow_scale: BoolProperty(name="Overall scale", default=True,
                              description="Optimize the shared scale after normalizing relative 3D area")
    tolerance: FloatProperty(name="Tolerance", default=1.0, min=0.0, max=25.0,
                             subtype="PERCENTAGE", precision=2,
                             description="UV vertex deviation as a percentage of the reference island diagonal")

    def pack_config(self):
        return packing.PackConfig(self.texture_width, self.texture_height, self.gap, self.border,
                                  self.passes, self.allow_scale, seed=getrandbits(32))


class UVIT_Runtime(bpy.types.PropertyGroup):
    running: BoolProperty(options={"SKIP_SAVE"})
    progress: FloatProperty(min=0, max=1, options={"SKIP_SAVE"})
    current: StringProperty(options={"SKIP_SAVE"})
    last_result: StringProperty(options={"SKIP_SAVE"})


class _UVOperator:
    @classmethod
    def poll(cls, context):
        return data.is_uv_edit(context) and not context.window_manager.uvit_runtime.running

    def warn(self, message):
        self.report({"WARNING"}, tr(message))
        return {"CANCELLED"}

    @classmethod
    def description(cls, _context, _properties):
        return tr(cls.bl_description)


class UVIT_OT_select_similar(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_select_similar"
    bl_label = "Select Similar"
    bl_description = "Select visible islands with matching topology and nearby UV vertices"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            snapshot = data.read_snapshot(context)
            references = [island for island in snapshot.islands if island.selected and island.contour]
            if not references:
                return self.warn("Select an island with a closed UV outline.")
            tolerance = context.scene.uvit_settings.tolerance / 100
            matches = [
                island for island in snapshot.islands if island.visible_faces and not island.selected
                and any(match_islands(island, reference, tolerance) is not None for reference in references)
            ]
            if not matches:
                return self.warn("No similar islands found.")
            data.select_islands(matches, context.tool_settings)
        except ValueError as error:
            return self.warn(str(error))
        self.report({"INFO"}, tr("Islands added to selection: {count}", count=len(matches)))
        return {"FINISHED"}


def _snap_order(group):
    island = group.representative
    return not bool(group.anchors), not island.active, -island.area, island.state.mesh.name_full, island.faces[0]


def _snap_vertices(source, reference, transform, tolerance):
    limit = max(reference.contour.diagonal * tolerance, 1e-9)
    # Exact snapping can change shape slightly. Locked members only accept the
    # floating-point correction of an otherwise valid similarity.
    if source.flags:
        limit = min(limit, EPSILON)
    targets = {}
    for island in source.islands:
        a, b = island.topology, reference.topology
        if a.signature != b.signature:
            return None
        mapping = vertex_correspondence(a, b, transform, limit)
        if mapping is None:
            return None
        targets[island.key] = {vertex: b.vertices[index][1] for vertex, index in zip(a.vertices, mapping)}
    return targets


class UVIT_OT_snap(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_snap"
    bl_label = "Snap"
    bl_description = "Align selected islands and keep them together as a Snap group"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            snapshot = data.read_snapshot(context)
            tolerance = context.scene.uvit_settings.tolerance / 100
            selected = [group for group in snapshot.groups if group.selected]
            pending = sorted((group for group in selected if group.available
                              and not any(i.cluster_id for i in group.islands)), key=_snap_order)
            if len(pending) < 2:
                return self.warn("Select at least two available islands outside clusters.")
            vertices, memberships = {}, {}
            merged = 0
            participants = set()
            locked = set()
            while pending:
                target = pending.pop(0)
                reference = target.representative
                if reference.contour is None:
                    continue
                remaining = []
                aligned = []
                for source in pending:
                    best = match_islands(source.representative, reference, tolerance, source.flags, source.anchors)
                    targets = _snap_vertices(source, reference, best[1], tolerance) if best else None
                    if targets is None:
                        if source.flags and match_islands(source.representative, reference, tolerance) is not None:
                            locked.add(source.key)
                        remaining.append(source)
                        continue
                    aligned.append((source, targets))
                pending = remaining
                if not aligned:
                    continue
                group_id = target.key if isinstance(target.key, bytes) else data.group_token()
                for island in target.islands:
                    memberships[island.key] = data.membership(group_id, island.storage)
                for source, targets in aligned:
                    vertices.update(targets)
                    for island in source.islands:
                        memberships[island.key] = data.membership(group_id, island.storage)
                    participants.add(source.key)
                participants.add(target.key)
                merged += 1
            details = tr("Groups skipped: {count}", count=len(selected) - len(participants))
            if locked - participants:
                details += f" · {tr('Locks')}: {len(locked - participants)}"
            if not merged:
                return self.warn(f"{tr('No compatible matches found.')} {details}")
            data.apply_changes(snapshot.islands, uv_targets=vertices, memberships=memberships)
        except ValueError as error:
            return self.warn(str(error))
        self.report({"INFO"}, f"{tr('Snap groups created: {count}', count=merged)}. {details}")
        return {"FINISHED"}


class UVIT_OT_unsnap(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_unsnap"
    bl_label = "Clear Snap"
    bl_description = "Disband selected Snap groups"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            snapshot = data.read_snapshot(context)
            selected = [g for g in snapshot.groups if g.selected and isinstance(g.key, bytes)]
            available = [g for g in selected if g.available]
            memberships = {island.key: b"" for group in available for island in group.islands}
            if not memberships:
                return self.warn("No available Snap groups. Open all members of the group.")
            data.apply_changes(snapshot.islands, memberships=memberships)
        except ValueError as error:
            return self.warn(str(error))
        cleared = tr("Snap groups cleared: {count}", count=len(available))
        skipped = tr("Groups skipped: {count}", count=len(selected) - len(available))
        self.report({"INFO"}, f"{cleared}. {skipped}")
        return {"FINISHED"}


class UVIT_OT_lock(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_lock"
    bl_label = "Toggle Lock"
    bl_options = {"REGISTER", "UNDO"}

    component: EnumProperty(
        name="Lock", default=0,
        items=enum_items([("ROTATION", "Rotation", ""), ("SCALE", "Size", ""), ("POSITION", "Position", "")]),
    )

    @classmethod
    def description(cls, _context, properties):
        descriptions = {
            "ROTATION": "Lock or unlock island rotation",
            "SCALE": "Lock or unlock island size",
            "POSITION": "Lock or unlock the island center",
        }
        return tr(descriptions[properties.component])

    def execute(self, context):
        try:
            snapshot = data.read_snapshot(context)
            selected = [island for island in snapshot.islands if island.selected and island.editable]
            if not selected:
                return self.warn("Select an available UV island.")
            bit = {"ROTATION": ROTATION, "SCALE": SCALE, "POSITION": POSITION}[self.component]
            enable = not all(island.flags & bit for island in selected)
            locks = {island.key: (island.flags | bit if enable else island.flags & ~bit) for island in selected}
            data.apply_changes(selected, locks=locks)
        except ValueError as error:
            return self.warn(str(error))
        status = "Locked islands: {count}" if enable else "Unlocked islands: {count}"
        self.report({"INFO"}, tr(status, count=len(selected)))
        return {"FINISHED"}


class UVIT_OT_pack(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_pack"
    bl_label = "Pack Islands"
    bl_description = "Find a dense layout in the 0–1 tile within padding and locks"
    bl_options = {"REGISTER", "UNDO", "BLOCKING"}

    def _begin(self, context):
        self.runtime = context.window_manager.uvit_runtime
        self.backend = self.search = self.timer = None
        self.fallback = ""
        self.start_time = time.perf_counter()
        settings = context.scene.uvit_settings
        self.requested_backend = settings.backend
        self.config = settings.pack_config()
        self.config.validate()
        self.snapshot = data.read_snapshot(context)
        self.target_groups = []
        self.units = []
        self.obstacles = []
        self.skipped = 0
        for group in self.snapshot.packing_groups:
            wanted = group.selected if settings.scope == "SELECTED" else group.visible
            unit = group.unit()
            if wanted and group.available and unit.area > 0:
                self.target_groups.append(group)
                self.units.append(unit)
            else:
                self.obstacles.append(unit)
                self.skipped += int(wanted)
        if not self.units:
            raise ValueError("No available islands to pack. Check the selection and groups.")
        try:
            units, obstacles = self.units, self.obstacles
            factories = {
                "AUTO": lambda: AutoBackend(len(units) + len(obstacles),
                                            sum(len(unit.triangles) for unit in (*units, *obstacles))),
                "CPU": NativeCPUBackend,
                "GPU": GPUBackend,
                "CUDA": CudaBackend,
                "HYBRID": HybridBackend,
            }
            self.backend = factories[self.requested_backend]()
        except GPUUnavailable as error:
            self._retry_cpu(error)
        else:
            self.search = packing.pack_iter(self.units, self.obstacles, self.config, self.backend)
        self.runtime.running = True
        self.runtime.progress = 0
        self.runtime.current = tr("Preparing layout")
        self.runtime.last_result = ""

    def _retry_cpu(self, error):
        try_native = (not self.fallback and self.requested_backend != "CPU"
                      and not isinstance(self.backend, NativeCPUBackend))
        if self.search is not None:
            self.search.close()
        if self.backend is not None:
            self.backend.close()
        self.fallback = str(error)
        try:
            self.backend = NativeCPUBackend() if try_native else packing.CPUBackend()
        except GPUUnavailable:
            self.backend = packing.CPUBackend()
        self.search = packing.pack_iter(self.units, self.obstacles, self.config, self.backend)
        self.runtime.progress = 0
        self.runtime.current = tr("Retrying on CPU")

    def _cleanup(self, context):
        if self.timer is not None:
            context.window_manager.event_timer_remove(self.timer)
            self.timer = None
        if self.search is not None:
            self.search.close()
            self.search = None
        if self.backend is not None:
            self.backend.close()
            self.backend = None
        self.runtime.running = False
        if context.area:
            context.area.tag_redraw()

    def _step(self, context):
        try:
            progress = next(self.search)
        except GPUUnavailable as error:
            self._retry_cpu(error)
        except StopIteration as completed:
            return self._finish(context, completed.value)
        else:
            self.runtime.progress = max(self.runtime.progress, progress / self.config.passes)
            if progress >= self.config.passes:
                self.runtime.current = f"{self.backend.label} · {tr('Compacting')}"
            else:
                current_pass = int(progress) + 1
                step = tr("Pass {current}/{total}", current=current_pass, total=self.config.passes)
                self.runtime.current = f"{self.backend.label} · {step}"
        return None

    def _finish(self, context, result):
        if result is None:
            reason = tr("No layout found. Check the locks and padding.")
            if self.fallback:
                reason += " " + tr("CPU fallback: {reason}", reason=self.fallback)
            return self._abort(context, reason)
        if not packing.validate_layout(self.units, self.obstacles, result.transforms, self.config):
            if not isinstance(self.backend, packing.CPUBackend):
                self._retry_cpu(GPUUnavailable("accelerated layout failed final validation"))
                return None
            return self._abort(context, "The layout failed the bounds, padding and lock checks.")
        latest = data.read_snapshot(context)
        if latest.signature() != self.snapshot.signature():
            return self._abort(context, "UV data changed. Start packing again.")
        transforms = {island.key: result.transforms[group.key] for group in self.target_groups for island in group.islands}
        data.apply_changes(latest.islands, transforms=transforms)
        elapsed = time.perf_counter() - self.start_time
        passes = tr("Passes")
        fill = tr("Fill ≈ {fill} · scale ×{scale}", fill=f"{result.coverage:.1%}", scale=f"{result.scale:.3g}")
        self.runtime.last_result = f"{self.backend.label} · {passes} {result.passes} · {elapsed:.2f} s\n{fill}"
        if self.skipped:
            self.runtime.last_result += "\n" + tr("Groups skipped: {count}", count=self.skipped)
        if self.fallback:
            self.runtime.last_result += "\n" + tr("CPU fallback: {reason}", reason=self.fallback)
        self.report({"INFO"}, self.runtime.last_result.replace("\n", ". "))
        self._cleanup(context)
        return {"FINISHED"}

    def _abort(self, context, message):
        self.runtime.last_result = tr(message)
        self._cleanup(context)
        return self.warn(message)

    def execute(self, context):
        try:
            self._begin(context)
            completed = None
            while completed is None:
                completed = self._step(context)
            return completed
        except Exception as error:
            return self._abort(context, str(error))

    def invoke(self, context, _event):
        try:
            self._begin(context)
            self.timer = context.window_manager.event_timer_add(0.016, window=context.window)
            context.window_manager.modal_handler_add(self)
        except Exception as error:
            return self._abort(context, str(error))
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type == "ESC" and event.value == "PRESS":
            self.cancel(context)
            return {"CANCELLED"}
        # Blender's Event RNA exposes the timer event type but no Timer handle.
        if event.type == "TIMER":
            try:
                deadline = time.perf_counter() + 0.012
                while True:
                    outcome = self._step(context)
                    if outcome is not None:
                        return outcome
                    if time.perf_counter() >= deadline:
                        break
            except Exception as error:
                return self._abort(context, str(error))
            if context.area:
                context.area.tag_redraw()
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        self.runtime.last_result = tr("Packing cancelled")
        self._cleanup(context)


class UVIT_PT_tools(bpy.types.Panel):
    bl_label = "SARD UV Toolkit"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "SARD UV Toolkit"

    @classmethod
    def poll(cls, context):
        return data.is_uv_edit(context)

    def draw(self, context):
        layout = self.layout
        settings = context.scene.uvit_settings
        runtime = context.window_manager.uvit_runtime
        layout.use_property_split = True
        layout.use_property_decorate = False
        controls = layout.column()
        controls.enabled = not runtime.running

        pack = controls.box()
        for key, label in (("scope", "Islands"), ("backend", "Compute"), ("passes", "Passes"),
                           ("resolution", "Resolution")):
            pack.prop(settings, key, text=tr(label), translate=False)
        if settings.resolution == "CUSTOM":
            pack.prop(settings, "texture_width", text=tr("Width (px)"), translate=False)
            pack.prop(settings, "texture_height", text=tr("Height (px)"), translate=False)
        pack.prop(settings, "gap", text=tr("Gap (px)"), translate=False)
        pack.prop(settings, "border", text=tr("Border (px)"), translate=False)
        pack.prop(settings, "allow_scale", text=tr("Overall scale"), translate=False)
        pack.operator_context = "INVOKE_DEFAULT"
        pack.operator(UVIT_OT_pack.bl_idname, text=tr(UVIT_OT_pack.bl_label), translate=False, icon="UV")

        snap = controls.box()
        snap.prop(settings, "tolerance", text=tr("Tolerance"), translate=False)
        snap.operator(UVIT_OT_select_similar.bl_idname, text=tr(UVIT_OT_select_similar.bl_label), translate=False)
        row = snap.row(align=True)
        row.operator(UVIT_OT_snap.bl_idname, text=tr(UVIT_OT_snap.bl_label), translate=False)
        row.operator(UVIT_OT_unsnap.bl_idname, text=tr(UVIT_OT_unsnap.bl_label), translate=False)

        locks = controls.box()
        locks.label(text=tr("Locks"), translate=False)
        flags = 0 if runtime.running else data.selection_locks(context)
        for which, label, bit in (("ROTATION", "Rotation", ROTATION), ("SCALE", "Size", SCALE),
                                  ("POSITION", "Position", POSITION)):
            locked = bool(flags & bit)
            locks.operator(UVIT_OT_lock.bl_idname, text=tr(label), translate=False,
                           icon="LOCKED" if locked else "UNLOCKED", depress=locked).component = which

        draw_language(controls, context)

        if runtime.running:
            layout.progress(factor=runtime.progress, type="BAR", text=runtime.current)
            layout.label(text=tr("Esc to cancel"), translate=False)
        elif runtime.last_result:
            for line in runtime.last_result.splitlines():
                layout.label(text=line, translate=False)


_CLASSES = (
    UVIT_Settings, UVIT_Runtime, UVIT_OT_select_similar, UVIT_OT_snap, UVIT_OT_unsnap,
    UVIT_OT_lock, UVIT_OT_pack, UVIT_PT_tools,
)


def register():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.uvit_settings = PointerProperty(type=UVIT_Settings)
    bpy.types.WindowManager.uvit_runtime = PointerProperty(type=UVIT_Runtime, options={"SKIP_SAVE"})


def unregister():
    del bpy.types.WindowManager.uvit_runtime
    del bpy.types.Scene.uvit_settings
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)
