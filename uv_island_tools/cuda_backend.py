"""CUDA Driver API backend. The installed extension needs the driver and bundled PTX."""

from contextlib import contextmanager
import ctypes as C
import os
from pathlib import Path

import numpy as np

from .gpu_backend import BatchedBackend, GPUUnavailable


_HANDLE = C.c_void_p
_DEVICE = C.c_int
_PTR = C.c_uint64
_UINT = C.c_uint
_SIZE = C.c_size_t
_REF = C.POINTER


class CudaDriver:
    def __init__(self):
        if os.name == "nt":
            self.lib = C.WinDLL("nvcuda.dll")
        else:
            self.lib = C.CDLL("libcuda.so.1")
        self._bind("cuInit", _UINT)
        self._bind("cuDeviceGet", _REF(_DEVICE), C.c_int)
        self._bind("cuDeviceGetName", _HANDLE, C.c_int, _DEVICE)
        self._bind("cuDevicePrimaryCtxRetain", _REF(_HANDLE), _DEVICE)
        self._bind("cuDevicePrimaryCtxRelease_v2", _DEVICE)
        self._bind("cuCtxPushCurrent_v2", _HANDLE)
        self._bind("cuCtxPopCurrent_v2", _REF(_HANDLE))
        self._bind("cuModuleLoadData", _REF(_HANDLE), C.c_char_p)
        self._bind("cuModuleGetFunction", _REF(_HANDLE), _HANDLE, C.c_char_p)
        self._bind("cuModuleUnload", _HANDLE)
        self._bind("cuMemAlloc_v2", _REF(_PTR), _SIZE)
        self._bind("cuMemFree_v2", _PTR)
        self._bind("cuMemcpyHtoD_v2", _PTR, _HANDLE, _SIZE)
        self._bind("cuMemcpyDtoH_v2", _HANDLE, _PTR, _SIZE)
        self._bind("cuLaunchKernel", _HANDLE, _UINT, _UINT, _UINT, _UINT, _UINT, _UINT,
                   _UINT, _HANDLE, _REF(_HANDLE), _HANDLE)
        self.call(self.cuInit, 0)

    def _bind(self, name, *arguments):
        function = getattr(self.lib, name)
        function.argtypes = arguments
        function.restype = C.c_int
        setattr(self, name, function)

    @staticmethod
    def call(function, *args):
        result = function(*args)
        if result:
            raise GPUUnavailable(f"CUDA {function.__name__}: код {result}")

    @contextmanager
    def context(self, handle):
        self.call(self.cuCtxPushCurrent_v2, handle)
        try:
            yield
        finally:
            previous = _HANDLE()
            self.call(self.cuCtxPopCurrent_v2, C.byref(previous))


class CudaBackend(BatchedBackend):
    def __init__(self):
        super().__init__("CUDA")
        self.driver = None
        self.device = _DEVICE()
        self.context = _HANDLE()
        self.module = _HANDLE()
        self.kernel = _HANDLE()
        self.buffers = {}
        try:
            ptx = Path(__file__).with_name("cuda_geometry.ptx").read_bytes()
            self.driver = driver = CudaDriver()
            driver.call(driver.cuDeviceGet, C.byref(self.device), 0)
            driver.call(driver.cuDevicePrimaryCtxRetain, C.byref(self.context), self.device)
            with driver.context(self.context):
                driver.call(driver.cuModuleLoadData, C.byref(self.module), ptx)
                driver.call(driver.cuModuleGetFunction, C.byref(self.kernel), self.module, b"uvit_candidates")
        except (OSError, AttributeError, GPUUnavailable) as error:
            self.close()
            raise GPUUnavailable(f"CUDA недоступна: {error}") from error

    def find(self, board, candidates):
        if not candidates:
            return None
        with self.driver.context(self.context):
            return super().find(board, candidates)

    def _storage(self, name, bytes_needed):
        allocation, capacity = self.buffers.get(name, (_PTR(), 0))
        if capacity < bytes_needed:
            if allocation.value:
                self.driver.call(self.driver.cuMemFree_v2, allocation)
                del self.buffers[name]
            allocation = _PTR()
            capacity = max(256, 1 << (bytes_needed - 1).bit_length())
            self.driver.call(self.driver.cuMemAlloc_v2, C.byref(allocation), capacity)
            self.buffers[name] = allocation, capacity
        return allocation

    def upload(self, name, rows):
        rows = np.ascontiguousarray(rows, dtype=np.float32)
        target = self._storage(name, rows.nbytes)
        self.driver.call(self.driver.cuMemcpyHtoD_v2, target, rows.ctypes.data, rows.nbytes)
        return target

    def _launch(self, board, shapes, positions, board_count, count, gap_sq):
        source = self.upload("positions", positions)
        result = self._storage("result", count * 4)
        arguments = (board, shapes, source, result, C.c_int(board_count), C.c_int(count), C.c_float(gap_sq))
        pointers = (_HANDLE * len(arguments))(*(C.addressof(argument) for argument in arguments))
        driver = self.driver
        driver.call(driver.cuLaunchKernel, self.kernel, (count + 63) // 64, 1, 1, 64, 1, 1, 0, None, pointers, None)
        return result

    def _read(self, result, count):
        output = np.empty(count, dtype=np.float32)
        self.driver.call(self.driver.cuMemcpyDtoH_v2, output.ctypes.data, result, output.nbytes)
        return output

    def dispatch(self, board, shapes, positions, board_count, count, gap_sq):
        return self._read(self._launch(board, shapes, positions, board_count, count, gap_sq), count)

    def close(self):
        super().close()
        if self.context.value and self.driver is not None:
            driver = self.driver
            try:
                if driver.cuCtxPushCurrent_v2(self.context) == 0:
                    try:
                        for allocation, _ in self.buffers.values():
                            driver.cuMemFree_v2(allocation)
                        if self.module.value:
                            driver.cuModuleUnload(self.module)
                    finally:
                        driver.cuCtxPopCurrent_v2(C.byref(_HANDLE()))
            finally:
                driver.cuDevicePrimaryCtxRelease_v2(self.device)
                self.context = _HANDLE()
                self.buffers.clear()
