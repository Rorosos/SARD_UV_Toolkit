// CUDA port of the exact triangle candidate checks in gpu_backend.py.
// Build PTX with NVRTC for compute_75 or with nvcc -ptx -arch=compute_75.

#ifndef __CUDACC__
#include <cmath>
#define __device__ inline
#endif

struct Vec2 { float x, y; };
struct alignas(16) Vec4 { float x, y, z, w; };
struct Triangle { Vec2 a, b, c; bool solid; };

__device__ Vec2 xy(Vec4 a) { return {a.x, a.y}; }
__device__ Vec2 zw(Vec4 a) { return {a.z, a.w}; }
__device__ Vec2 operator+(Vec2 a, Vec2 b) { return {a.x + b.x, a.y + b.y}; }
__device__ Vec2 operator-(Vec2 a, Vec2 b) { return {a.x - b.x, a.y - b.y}; }
__device__ Vec2 operator*(Vec2 a, float b) { return {a.x * b, a.y * b}; }
__device__ float dot(Vec2 a, Vec2 b) { return a.x * b.x + a.y * b.y; }
__device__ float cross2(Vec2 a, Vec2 b) { return a.x * b.y - a.y * b.x; }

__device__ bool close_boxes(Vec4 a, Vec4 b, float gap_sq) {
    const float dx = fmaxf(0.f, fmaxf(a.x - b.z, b.x - a.z));
    const float dy = fmaxf(0.f, fmaxf(a.y - b.w, b.y - a.w));
    return dx * dx + dy * dy <= gap_sq;
}

__device__ bool behind(Vec2 a, Vec2 b, Triangle other) {
    Vec2 edge = b - a;
    float side = fmaxf(cross2(edge, other.a - a), fmaxf(cross2(edge, other.b - a), cross2(edge, other.c - a)));
    return dot(edge, edge) > 0.f && side <= 0.f;
}

__device__ bool separated(Triangle a, Triangle b) {
    return behind(a.a, a.b, b) || behind(a.b, a.c, b) || behind(a.c, a.a, b);
}

__device__ float point_edge_sq(Vec2 p, Vec2 a, Vec2 b) {
    Vec2 edge = b - a, delta = p - a;
    float len_sq = dot(edge, edge);
    if (len_sq > 0.f) {
        delta = delta - edge * fmaxf(0.f, fminf(1.f, dot(delta, edge) / len_sq));
    }
    return dot(delta, delta);
}

__device__ bool point_close(Vec2 p, Triangle t, float gap_sq) {
    return point_edge_sq(p, t.a, t.b) < gap_sq || point_edge_sq(p, t.b, t.c) < gap_sq ||
           point_edge_sq(p, t.c, t.a) < gap_sq;
}

__device__ bool crosses(Vec2 a, Vec2 b, Vec2 c, Vec2 d) {
    return cross2(b - a, c - a) * cross2(b - a, d - a) < 0.f &&
           cross2(d - c, a - c) * cross2(d - c, b - c) < 0.f;
}

__device__ bool crosses_triangle(Vec2 a, Vec2 b, Triangle t) {
    return crosses(a, b, t.a, t.b) || crosses(a, b, t.b, t.c) || crosses(a, b, t.c, t.a);
}

__device__ bool conflicts(Triangle a, Triangle b, float gap_sq) {
    if (a.solid && b.solid && !separated(a, b) && !separated(b, a)) return true;
    if (gap_sq == 0.f) return false;
    if (a.solid != b.solid) {
        if (a.solid && !separated(a, b)) return true;
        if (b.solid && !separated(b, a)) return true;
    } else if (!a.solid) {
        if (crosses_triangle(a.a, a.b, b) || crosses_triangle(a.b, a.c, b) ||
            crosses_triangle(a.c, a.a, b)) return true;
    }
    return point_close(a.a, b, gap_sq) || point_close(a.b, b, gap_sq) || point_close(a.c, b, gap_sq) ||
           point_close(b.a, a, gap_sq) || point_close(b.b, a, gap_sq) || point_close(b.c, a, gap_sq);
}

__device__ bool can_place(Vec4 box, Vec4 candidate, const Vec4 *board, const Vec4 *shapes,
                          int board_count, float gap_sq) {
    const Vec4 *geometry = board + board_count * 2;
    for (int i = 0; i < board_count; ++i) {
        if (!close_boxes(box, board[i * 2], gap_sq)) continue;
        Vec4 info = board[i * 2 + 1];
        Vec2 shift = xy(candidate) - xy(info);
        const Vec4 *nodes = geometry + int(info.z);
        for (int moving = int(candidate.z); moving < int(candidate.w); moving += 3) {
            Vec4 ab = shapes[moving], c_lo = shapes[moving + 1], hi = shapes[moving + 2];
            Vec4 moving_box = {c_lo.z + shift.x, c_lo.w + shift.y, hi.x + shift.x, hi.y + shift.y};
            Triangle a = {xy(ab) + shift, zw(ab) + shift, xy(c_lo) + shift, hi.z != 0.f};
            int node = 0;
            while (node < int(info.w)) {
                Vec4 node_data = nodes[node * 2 + 1];
                if (!close_boxes(moving_box, nodes[node * 2], gap_sq)) {
                    node = int(node_data.x);
                    continue;
                }
                if (node_data.y >= 0.f) {
                    const Vec4 *tri = geometry + int(node_data.y);
                    Triangle b = {xy(tri[0]), zw(tri[0]), xy(tri[1]), tri[2].z != 0.f};
                    if (conflicts(a, b, gap_sq)) return false;
                }
                ++node;
            }
        }
    }
    return true;
}

#ifdef __CUDACC__
extern "C" __global__ void uvit_candidates(const Vec4 *board, const Vec4 *shapes, const Vec4 *poses,
                                          float *valid, int board_count, int count, float gap_sq) {
    int index = blockIdx.x * blockDim.x + threadIdx.x;
    if (index < count) {
        valid[index] = can_place(poses[index * 2], poses[index * 2 + 1], board, shapes, board_count, gap_sq) ? 1.f : 0.f;
    }
}
#else
extern "C" __declspec(dllexport) int uvit_cpu_first(const Vec4 *board, const Vec4 *shapes, const Vec4 *poses,
                                                   int board_count, int count, float gap_sq) {
    for (int index = 0; index < count; ++index) {
        if (can_place(poses[index * 2], poses[index * 2 + 1], board, shapes, board_count, gap_sq)) return index;
    }
    return -1;
}
#endif
