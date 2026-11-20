"""Blender operators, scene settings and UV Editor panel."""

import time

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty, PointerProperty, StringProperty

from . import blender_data as data
from . import packing
from .cuda_backend import CudaBackend
from .geometry import POSITION, ROTATION, SCALE, find_match
from .gpu_backend import AutoBackend, GPUBackend, GPUUnavailable, HybridBackend
from .native_cpu import NativeCPUBackend


def _apply_preset(self, _context):
    preset = packing.PRESETS.get(self.resolution)
    if preset is not None:
        side, self.gap, self.border = preset
        self.texture_width = side
        self.texture_height = side


class UVIT_Settings(bpy.types.PropertyGroup):
    resolution: EnumProperty(
        name="Разрешение", default="2048", update=_apply_preset,
        items=[(key, f"{side} × {side}", f"Зазор {gap} px, поле {border} px")
               for key, (side, gap, border) in packing.PRESETS.items()]
        + [("CUSTOM", "Своё разрешение", "Задать ширину и высоту текстуры")],
    )
    texture_width: IntProperty(name="Ширина (px)", default=2048, min=1, max=32768)
    texture_height: IntProperty(name="Высота (px)", default=2048, min=1, max=32768)
    gap: IntProperty(name="Зазор (px)", description="Минимальное расстояние между формами островов",
                     default=16, min=0, max=16384)
    border: IntProperty(name="Поле (px)", description="Минимальное расстояние от формы до края UV-тайла",
                        default=8, min=0, max=16384)
    scope: EnumProperty(
        name="Острова", default="SELECTED",
        items=[("SELECTED", "Выбранные", "Упаковать целиком острова, попавшие в выделение"),
               ("VISIBLE", "Все видимые", "Упаковать видимые острова активных UV-карт")],
    )
    passes: IntProperty(name="Проходы", default=packing.DEFAULT_PASSES, min=1, max=1000, soft_max=200,
                        description="Число вариантов раскладки с разными позициями, углами и порядком островов")
    backend: EnumProperty(
        name="Вычисления", default="AUTO",
        items=[("AUTO", "Авто", "Выбрать нативный CPU или CUDA с учётом размера задачи и доступных устройств"),
               ("GPU", "GPU Blender", "Проверять позиции шейдером Blender на OpenGL или Vulkan"),
               ("CPU", "CPU", "Использовать нативный CPU-модуль, если он доступен"),
               ("CUDA", "CUDA", "Проверять позиции напрямую через драйвер NVIDIA"),
               ("HYBRID", "CPU + GPU", "Проверять первые позиции на CPU, а сложные партии шейдером Blender")],
    )
    allow_scale: BoolProperty(name="Масштабировать", default=True,
                              description="Применять общий коэффициент к островам без фиксации размера")
    tolerance: FloatProperty(name="Допуск", default=1.0, min=0.0, max=25.0,
                             subtype="PERCENTAGE", precision=2,
                             description="Отклонение контура в процентах от диагонали эталона")

    def pack_config(self):
        return packing.PackConfig(self.texture_width, self.texture_height, self.gap, self.border,
                                  self.passes, self.allow_scale)


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
        self.report({"WARNING"}, message)
        return {"CANCELLED"}


class UVIT_OT_select_similar(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_select_similar"
    bl_label = "Выбрать схожие"
    bl_description = "Выделить видимые острова с похожим контуром"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            snapshot = data.read_snapshot(context)
            references = [island.contour for island in snapshot.islands if island.selected and island.contour]
            if not references:
                return self.warn("Выделите остров с замкнутым UV-контуром")
            tolerance = context.scene.uvit_settings.tolerance / 100
            matches = [
                island for island in snapshot.islands if island.visible_faces and not island.selected
                and any(find_match(island.contour, reference, tolerance) is not None for reference in references)
            ]
            if not matches:
                return self.warn("Дополнительные острова в пределах допуска не найдены")
            data.select_islands(matches, context.tool_settings)
        except ValueError as error:
            return self.warn(str(error))
        self.report({"INFO"}, f"Добавлено островов к выделению: {len(matches)}")
        return {"FINISHED"}


def _snap_order(group):
    island = group.representative
    return not bool(group.anchors), not island.active, -island.area, island.state.mesh.name_full, island.faces[0]


class UVIT_OT_snap(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_snap"
    bl_label = "Snap"
    bl_description = "Совместить выделенные острова и сохранить их как Snap-группу"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            snapshot = data.read_snapshot(context)
            tolerance = context.scene.uvit_settings.tolerance / 100
            selected = [group for group in snapshot.groups if group.selected]
            pending = sorted((group for group in selected if group.available), key=_snap_order)
            if len(pending) < 2:
                return self.warn("Выделите хотя бы два доступных острова из разных групп")
            transforms, memberships = {}, {}
            merged = 0
            participants = set()
            locked = set()
            while pending:
                target = pending.pop(0)
                reference = target.representative.contour
                if reference is None:
                    continue
                remaining = []
                aligned = []
                for source in pending:
                    contour = source.representative.contour
                    best = find_match(contour, reference, tolerance, source.flags, source.anchors)
                    if best is None:
                        if (source.flags or source.anchors) and find_match(contour, reference, tolerance) is not None:
                            locked.add(source.key)
                        remaining.append(source)
                        continue
                    aligned.append((source, best[1]))
                pending = remaining
                if not aligned:
                    continue
                group_id = target.key if isinstance(target.key, bytes) else data.group_token()
                for island in target.islands:
                    memberships[island.key] = data.membership(group_id, island)
                for source, transform in aligned:
                    for island in source.islands:
                        transforms[island.key] = transform
                        memberships[island.key] = data.membership(group_id, island)
                    participants.add(source.key)
                participants.add(target.key)
                merged += 1
            details = f"Пропущено групп: {len(selected) - len(participants)}"
            if locked - participants:
                details += f" (из-за фиксаций: {len(locked - participants)})"
            if not merged:
                return self.warn(f"Допустимых совпадений нет. {details}")
            data.apply_changes(snapshot.islands, transforms=transforms, memberships=memberships)
        except ValueError as error:
            return self.warn(str(error))
        self.report({"INFO"}, f"Snap-групп: {merged}. {details}")
        return {"FINISHED"}


class UVIT_OT_unsnap(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_unsnap"
    bl_label = "Снять Snap"
    bl_description = "Расформировать выбранные Snap-группы"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        try:
            snapshot = data.read_snapshot(context)
            selected = [g for g in snapshot.groups if g.selected and isinstance(g.key, bytes)]
            available = [g for g in selected if g.available]
            memberships = {island.key: b"" for group in available for island in group.islands}
            if not memberships:
                return self.warn("Нет доступных Snap-групп. Для снятия Snap откройте все части группы")
            data.apply_changes(snapshot.islands, memberships=memberships)
        except ValueError as error:
            return self.warn(str(error))
        self.report({"INFO"}, f"Расформировано групп: {len(available)}. Пропущено: {len(selected) - len(available)}")
        return {"FINISHED"}


class UVIT_OT_lock(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_lock"
    bl_label = "Переключить фиксацию"
    bl_options = {"REGISTER", "UNDO"}

    component: EnumProperty(
        name="Фиксация", default="ROTATION",
        items=[("ROTATION", "Поворот", "Фиксировать или освободить текущий угол"),
               ("SCALE", "Размер", "Фиксировать или освободить текущий размер"),
               ("POSITION", "Положение", "Фиксировать или освободить геометрический центр")],
    )

    @classmethod
    def description(cls, _context, properties):
        descriptions = {
            "ROTATION": "Переключить фиксацию поворота выделенных островов",
            "SCALE": "Переключить фиксацию размера выделенных островов",
            "POSITION": "Переключить фиксацию центра выделенных островов",
        }
        return descriptions[properties.component]

    def execute(self, context):
        try:
            snapshot = data.read_snapshot(context)
            selected = [island for island in snapshot.islands if island.selected and island.editable]
            if not selected:
                return self.warn("Выделите доступный UV-остров")
            bit = {"ROTATION": ROTATION, "SCALE": SCALE, "POSITION": POSITION}[self.component]
            enable = not all(island.flags & bit for island in selected)
            locks = {island.key: (island.flags | bit if enable else island.flags & ~bit) for island in selected}
            data.apply_changes(selected, locks=locks)
        except ValueError as error:
            return self.warn(str(error))
        status = "Установлена" if enable else "Снята"
        self.report({"INFO"}, f"{status} фиксация. Островов: {len(selected)}")
        return {"FINISHED"}


class UVIT_OT_pack(_UVOperator, bpy.types.Operator):
    bl_idname = "uv.uvit_pack"
    bl_label = "Упаковать острова"
    bl_description = "Найти лучшую раскладку в тайле 0–1 с учётом отступов и фиксаций"
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
        for group in self.snapshot.groups:
            wanted = group.selected if settings.scope == "SELECTED" else group.visible
            unit = group.unit()
            if wanted and group.available and unit.area > 0:
                self.target_groups.append(group)
                self.units.append(unit)
            else:
                self.obstacles.append(unit)
                self.skipped += int(wanted)
        if not self.units:
            raise ValueError("Нет доступных UV-островов для упаковки. Проверьте выделение и Snap-группы")
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
        self.runtime.current = "Подготовка раскладки"
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
        self.runtime.current = "Повтор на CPU"

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
                self.runtime.current = f"{self.backend.label} · уплотнение"
            else:
                current_pass = int(progress) + 1
                self.runtime.current = f"{self.backend.label} · проход {current_pass}/{self.config.passes}"
        return None

    def _finish(self, context, result):
        if result is None:
            suffix = f" Переход на CPU: {self.fallback}." if self.fallback else ""
            reason = "Раскладка не найдена. Проверьте фиксации и минимальные отступы." + suffix
            return self._abort(context, reason)
        if not packing.validate_layout(self.units, self.obstacles, result.transforms, self.config):
            if not isinstance(self.backend, packing.CPUBackend):
                self._retry_cpu(GPUUnavailable("раскладка ускоренного режима не прошла итоговую проверку"))
                return None
            return self._abort(context, "Раскладка не прошла проверку границ, зазоров и фиксаций")
        latest = data.read_snapshot(context)
        if latest.signature() != self.snapshot.signature():
            return self._abort(context, "UV-данные изменились во время поиска. Запустите упаковку снова")
        transforms = {island.key: result.transforms[group.key] for group in self.target_groups for island in group.islands}
        data.apply_changes(latest.islands, transforms=transforms)
        elapsed = time.perf_counter() - self.start_time
        self.runtime.last_result = (
            f"{self.backend.label} · {result.passes} пр. · {elapsed:.2f} с\n"
            f"Заполнение ≈ {result.coverage:.1%} · масштаб ×{result.scale:.3g}"
        )
        if self.skipped:
            self.runtime.last_result += f"\nПропущено групп: {self.skipped}"
        if self.fallback:
            self.runtime.last_result += f"\nПереход на CPU: {self.fallback}"
        self.report({"INFO"}, self.runtime.last_result.replace("\n", ". "))
        self._cleanup(context)
        return {"FINISHED"}

    def _abort(self, context, message):
        self.runtime.last_result = message
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
        self.runtime.last_result = "Упаковка отменена"
        self._cleanup(context)


class UVIT_PT_tools(bpy.types.Panel):
    bl_label = "UV Island Tools"
    bl_space_type = "IMAGE_EDITOR"
    bl_region_type = "UI"
    bl_category = "UV Island Tools"

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
        pack.prop(settings, "scope")
        pack.prop(settings, "backend")
        pack.prop(settings, "passes")
        pack.prop(settings, "resolution")
        if settings.resolution == "CUSTOM":
            pack.prop(settings, "texture_width")
            pack.prop(settings, "texture_height")
        pack.prop(settings, "gap")
        pack.prop(settings, "border")
        pack.prop(settings, "allow_scale")
        pack.operator_context = "INVOKE_DEFAULT"
        pack.operator(UVIT_OT_pack.bl_idname, icon="UV")

        snap = controls.box()
        snap.prop(settings, "tolerance")
        snap.operator(UVIT_OT_select_similar.bl_idname)
        row = snap.row(align=True)
        row.operator(UVIT_OT_snap.bl_idname)
        row.operator(UVIT_OT_unsnap.bl_idname)

        locks = controls.box()
        locks.label(text="Фиксации")
        flags = 0 if runtime.running else data.selection_locks(context)
        for which, text, bit in (("ROTATION", "Поворот", ROTATION), ("SCALE", "Размер", SCALE),
                                 ("POSITION", "Положение", POSITION)):
            locked = bool(flags & bit)
            locks.operator(UVIT_OT_lock.bl_idname, text=text, icon="LOCKED" if locked else "UNLOCKED",
                           depress=locked).component = which

        if runtime.running:
            layout.progress(factor=runtime.progress, type="BAR", text=runtime.current)
            layout.label(text="Esc — отменить")
        elif runtime.last_result:
            for line in runtime.last_result.splitlines():
                layout.label(text=line)


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
