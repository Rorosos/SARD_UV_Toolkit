"""Compute-shader evaluation of continuous island poses on Blender 5.3."""

import bpy
import gpu
import numpy as np

from .packing import CPUBackend


class GPUUnavailable(RuntimeError):
    pass


_SHADER = """
struct Triangle {
    vec2 a;
    vec2 b;
    vec2 c;
    bool solid;
};

ivec2 address(int index) {
    return ivec2(index % 2048, index / 2048);
}

float cross2(vec2 a, vec2 b) {
    return a.x * b.y - a.y * b.x;
}

bool close_boxes(vec4 a, vec4 b) {
    vec2 distances = max(vec2(0.0), max(a.xy - b.zw, b.xy - a.zw));
    return dot(distances, distances) <= gap_sq;
}

bool behind(vec2 a, vec2 b, Triangle other) {
    vec2 edge = b - a;
    float side = max(cross2(edge, other.a - a), max(cross2(edge, other.b - a), cross2(edge, other.c - a)));
    return dot(edge, edge) > 0.0 && side <= 0.0;
}

bool separated(Triangle a, Triangle b) {
    return behind(a.a, a.b, b) || behind(a.b, a.c, b) || behind(a.c, a.a, b);
}

float point_edge_sq(vec2 point, vec2 a, vec2 b) {
    vec2 edge = b - a;
    vec2 delta = point - a;
    float len_sq = dot(edge, edge);
    if (len_sq > 0.0) {
        delta -= edge * clamp(dot(delta, edge) / len_sq, 0.0, 1.0);
    }
    return dot(delta, delta);
}

bool point_close(vec2 point, Triangle other) {
    return point_edge_sq(point, other.a, other.b) < gap_sq ||
           point_edge_sq(point, other.b, other.c) < gap_sq ||
           point_edge_sq(point, other.c, other.a) < gap_sq;
}

bool crosses(vec2 a, vec2 b, vec2 c, vec2 d) {
    return cross2(b - a, c - a) * cross2(b - a, d - a) < 0.0 &&
           cross2(d - c, a - c) * cross2(d - c, b - c) < 0.0;
}

bool crosses_triangle(vec2 a, vec2 b, Triangle other) {
    return crosses(a, b, other.a, other.b) || crosses(a, b, other.b, other.c) || crosses(a, b, other.c, other.a);
}

bool conflicts(Triangle a, Triangle b) {
    if (a.solid && b.solid && !separated(a, b) && !separated(b, a)) { return true; }
    if (gap_sq == 0.0) { return false; }
    if (a.solid != b.solid) {
        if (a.solid && !separated(a, b)) { return true; }
        if (b.solid && !separated(b, a)) { return true; }
    } else if (!a.solid) {
        if (crosses_triangle(a.a, a.b, b) || crosses_triangle(a.b, a.c, b) || crosses_triangle(a.c, a.a, b)) {
            return true;
        }
    }
    return point_close(a.a, b) || point_close(a.b, b) || point_close(a.c, b) ||
           point_close(b.a, a) || point_close(b.b, a) || point_close(b.c, a);
}

bool can_place(vec4 box, vec4 candidate) {
    int board_base = board_count * 2;
    for (int i = 0; i < board_count; ++i) {
        vec4 fixed_box = imageLoad(board_data, address(i * 2));
        if (!close_boxes(box, fixed_box)) { continue; }
        vec4 info = imageLoad(board_data, address(i * 2 + 1));
        vec2 shift = candidate.xy - info.xy;
        int first_node = board_base + int(info.z);
        int node_count = int(info.w);
        for (int moving = int(candidate.z); moving < int(candidate.w); moving += 3) {
            vec4 moving_ab = imageLoad(shape_data, address(moving));
            vec4 moving_c_lo = imageLoad(shape_data, address(moving + 1));
            vec4 moving_hi = imageLoad(shape_data, address(moving + 2));
            vec4 moving_box = vec4(moving_c_lo.zw + shift, moving_hi.xy + shift);
            Triangle a = Triangle(moving_ab.xy + shift, moving_ab.zw + shift, moving_c_lo.xy + shift, moving_hi.z != 0.0);
            int node = 0;
            while (node < node_count) {
                int index = first_node + node * 2;
                vec4 node_box = imageLoad(board_data, address(index));
                vec4 node_data = imageLoad(board_data, address(index + 1));
                if (!close_boxes(moving_box, node_box)) {
                    node = int(node_data.x);
                    continue;
                }
                if (node_data.y >= 0.0) {
                    int fixed_triangle = board_base + int(node_data.y);
                    vec4 fixed_ab = imageLoad(board_data, address(fixed_triangle));
                    vec4 fixed_c = imageLoad(board_data, address(fixed_triangle + 1));
                    vec4 fixed_hi = imageLoad(board_data, address(fixed_triangle + 2));
                    Triangle b = Triangle(fixed_ab.xy, fixed_ab.zw, fixed_c.xy, fixed_hi.z != 0.0);
                    if (conflicts(a, b)) { return false; }
                }
                ++node;
            }
        }
    }
    return true;
}

void main() {
    int index = int(gl_GlobalInvocationID.x);
    if (index >= candidate_count) { return; }
    vec4 box = imageLoad(candidates_data, address(index * 2));
    vec4 pose = imageLoad(candidates_data, address(index * 2 + 1));
    float valid = can_place(box, pose) ? 1.0 : 0.0;
    imageStore(result_data, ivec2(index, 0), vec4(valid));
}
"""


def _atlas(rows):
    max_width = 2048
    count = len(rows)
    width = max(1, min(max_width, count))
    height = max(1, (count + width - 1) // width)
    if height > 4096:
        raise GPUUnavailable("геометрия превышает размер буфера GPU")
    if count == width * height:
        values = np.ascontiguousarray(rows, dtype=np.float32)
    else:
        values = np.zeros((width * height, 4), dtype=np.float32)
        if count:
            values[:count] = rows
    return gpu.types.GPUTexture((width, height), format="RGBA32F",
                                data=gpu.types.Buffer("FLOAT", values.size, values))


def _triangle_data(shape):
    entries = np.empty((len(shape.triangles) * 3, 4), dtype=np.float32)
    for index, triangle in enumerate(shape.triangles):
        a, b, c = triangle.points
        x0, y0, x1, y1 = triangle.box
        entries[index * 3] = (a.real, a.imag, b.real, b.imag)
        entries[index * 3 + 1] = (c.real, c.imag, x0, y0)
        entries[index * 3 + 2] = (x1, y1, triangle.nondegenerate, 0.0)
    return entries


class BatchedBackend:
    """Shared candidate ordering, BVH serialization and exact CPU verification."""

    def __init__(self, label):
        self.device_label = label
        self.used = False
        self._reset_board(None)

    @property
    def label(self):
        return self.device_label if self.used else "CPU"

    def _reset_board(self, board):
        self.board = board
        self.board_header = []
        self.board_blocks = []
        self.board_length = 0
        self.board_resource = None

    def _board_data(self, board):
        if self.board is not board:
            self._reset_board(board)
        count = len(self.board_header) // 2
        if self.board_resource is None or count != len(board.poses):
            for pose in board.poses[count:]:
                base = self.board_length
                tree = pose.shape.tree
                child_data = np.empty((len(tree) * 2, 4), dtype=np.float32)
                triangle_base = base + len(child_data)
                for index, node in enumerate(tree):
                    child_data[index * 2] = node.box
                    triangle_index = triangle_base + node.triangle * 3 if node.triangle >= 0 else -1
                    child_data[index * 2 + 1] = (node.skip, triangle_index, 0.0, 0.0)
                triangles = _triangle_data(pose.shape)
                self.board_header.extend((pose.box, (pose.offset.real, pose.offset.imag, base, len(tree))))
                self.board_blocks.extend((child_data, triangles))
                self.board_length += len(child_data) + len(triangles)
            if self.board_header:
                header = np.asarray(self.board_header, dtype=np.float32)
                rows = np.concatenate((header, *self.board_blocks))
            else:
                rows = np.zeros((1, 4), dtype=np.float32)
            self.board_resource = self.upload("board", rows)
        return self.board_resource

    def find(self, board, candidates):
        if not candidates:
            return None
        try:
            board_data = self._board_data(board)
            candidate_rows = []
            geometry = []
            entries = {}
            length = 0
            for candidate in candidates:
                key = id(candidate.shape)
                if key not in entries:
                    triangles = _triangle_data(candidate.shape)
                    geometry.append(triangles)
                    entries[key] = length, length + len(triangles)
                    length += len(triangles)
                first, stop = entries[key]
                candidate_rows.append(candidate.box)
                candidate_rows.append((candidate.offset.real, candidate.offset.imag, first, stop))
            shape_data = self.upload("shapes", np.concatenate(geometry) if len(geometry) > 1 else geometry[0])
            max_triangles = max((stop - first) // 3 for first, stop in entries.values())
            chunk_size = min(512, max(8, 131072 // max_triangles))
            gap = max(0.0, board.gap - 2e-7)
            for start in range(0, len(candidates), chunk_size):
                end = min(start + chunk_size, len(candidates))
                count = end - start
                positions = np.asarray(candidate_rows[2 * start:2 * end], dtype=np.float32)
                self.used = True
                for index in self.eligible_indices(board_data, shape_data, positions, len(board.poses), count, gap * gap):
                    candidate = candidates[start + int(index)]
                    if board.fits(candidate):
                        return candidate
            return None
        except GPUUnavailable:
            raise
        except Exception as error:
            raise GPUUnavailable("сбой при проверке геометрии на GPU") from error

    def eligible_indices(self, board, shapes, positions, board_count, count, gap_sq):
        valid = self.dispatch(board, shapes, positions, board_count, count, gap_sq)
        if len(valid) != count or not np.all((valid == 0) | (valid == 1)):
            raise GPUUnavailable("GPU вернул недопустимый результат проверки")
        return np.flatnonzero(valid)

    def close(self):
        self._reset_board(None)


class GPUBackend(BatchedBackend):
    def __init__(self):
        try:
            if bpy.app.background:
                gpu.init()
            info = gpu.types.GPUShaderCreateInfo()
            info.local_group_size(64, 1, 1)
            for binding, name in enumerate(("board_data", "shape_data", "candidates_data", "result_data")):
                if name == "result_data":
                    info.image(binding, "R32F", "FLOAT_2D", name, qualifiers={"WRITE"})
                else:
                    info.image(binding, "RGBA32F", "FLOAT_2D", name, qualifiers={"READ"})
            for name in ("board_count", "candidate_count"):
                info.push_constant("INT", name)
            info.push_constant("FLOAT", "gap_sq")
            info.compute_source(_SHADER)
            self.shader = gpu.shader.create_from_info(info)
            super().__init__(f"GPU ({gpu.platform.backend_type_get()})")
        except Exception as error:
            raise GPUUnavailable("не удалось создать вычислительный шейдер") from error

    def upload(self, _name, rows):
        return _atlas(rows)

    def dispatch(self, board, shapes, positions, board_count, count, gap_sq):
        input_texture = _atlas(positions)
        output = gpu.types.GPUTexture((count, 1), format="R32F")
        shader = self.shader
        try:
            shader.bind()
            for name, resource in (("board_data", board), ("shape_data", shapes),
                                   ("candidates_data", input_texture), ("result_data", output)):
                shader.image(name, resource)
            shader.uniform_int("board_count", board_count)
            shader.uniform_int("candidate_count", count)
            shader.uniform_float("gap_sq", gap_sq)
            gpu.compute.dispatch(shader, (count + 63) // 64, 1, 1)
            return np.frombuffer(output.read(), dtype=np.float32)
        finally:
            gpu.shader.unbind()

    def close(self):
        super().close()
        self.shader = None


class HybridBackend:
    """Check quick high-ranked poses on CPU and send remaining batches to a device."""

    def __init__(self, accelerator_factory=GPUBackend, prefix=12):
        self.cpu = CPUBackend()
        self.accelerator = None
        self.factory = accelerator_factory
        self.prefix = prefix

    @property
    def label(self):
        if self.accelerator is not None and self.accelerator.used:
            return "CPU + " + self.accelerator.label
        return "CPU"

    def find(self, board, candidates):
        if len(candidates) <= self.prefix or not board.poses:
            return self.cpu.find(board, candidates)
        first = self.cpu.find(board, candidates[:self.prefix])
        if first is not None:
            return first
        if self.accelerator is None:
            self.accelerator = self.factory()
        return self.accelerator.find(board, candidates[self.prefix:])

    def close(self):
        if self.accelerator is not None:
            self.accelerator.close()


class AutoBackend:
    def __init__(self, workload=0, triangles=0):
        from .cuda_backend import CudaBackend
        from .native_cpu import NativeCPUBackend

        prefer_cpu = workload < 128 and triangles < 1024
        order = (NativeCPUBackend, CudaBackend) if prefer_cpu else (CudaBackend, NativeCPUBackend)
        self.factories = iter((*order, HybridBackend, CPUBackend))
        self.backend = None

    @property
    def label(self):
        return self.backend.label if self.backend is not None else "CPU"

    def find(self, board, candidates):
        while True:
            try:
                if self.backend is None:
                    factory = next(self.factories)
                    self.backend = factory()
                return self.backend.find(board, candidates)
            except GPUUnavailable:
                self.close()

    def close(self):
        if self.backend is not None:
            backend, self.backend = self.backend, None
            backend.close()
