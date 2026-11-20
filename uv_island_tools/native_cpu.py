"""Optional Windows x64 native CPU candidate checks, with exact Python verification."""

import ctypes as C
import os
from pathlib import Path
import platform

from .gpu_backend import BatchedBackend, GPUUnavailable


class NativeCPUBackend(BatchedBackend):
    def __init__(self):
        super().__init__("CPU (native)")
        if os.name != "nt" or platform.machine().lower() not in {"amd64", "x86_64"}:
            raise GPUUnavailable("нативный CPU доступен на Windows x64")
        try:
            path = Path(__file__).with_name("uvit_cpu_win64.dll")
            self.lib = C.CDLL(str(path))
            self.first = self.lib.uvit_cpu_first
            self.first.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_int, C.c_int, C.c_float]
            self.first.restype = C.c_int
        except (OSError, AttributeError) as error:
            raise GPUUnavailable("не удалось загрузить нативный CPU-модуль") from error

    def upload(self, _name, rows):
        return rows

    def eligible_indices(self, board, shapes, positions, board_count, count, gap_sq):
        start = 0
        pose_bytes = positions.strides[0] * 2
        while start < count:
            index = self.first(board.ctypes.data, shapes.ctypes.data, positions.ctypes.data + start * pose_bytes,
                               board_count, count - start, gap_sq)
            if index < 0:
                return
            if index >= count - start:
                raise GPUUnavailable("нативный CPU вернул недопустимый индекс позиции")
            yield start + index
            start += index + 1
