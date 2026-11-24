# SARD UV Toolkit

A Blender extension for dense UV packing, island diagnostics, and UV cluster management.

AI-assisted coding

**[Download SARD UV Toolkit 1.5.0 (ZIP)](https://raw.githubusercontent.com/Rorosos/SARD_UV_Toolkit/main/downloads/sard_uv_toolkit-1.5.0.zip)**

## Installation

1. Download the ZIP.
2. In Blender, open **Edit → Preferences → Get Extensions**.
3. Open the menu in the upper-right corner, choose **Install from Disk…**, and select the ZIP.
4. Open a mesh with a UV map in **Edit Mode**. Press `N` in the **UV Editor** and open **SARD UV Toolkit**.

Use the language selector in the sidebar or the extension preferences. Available languages are English, Simplified Chinese, Hindi, Spanish, Arabic, French, Armenian, Brazilian Portuguese, and Russian.

## UV diagnostics

Open **UV Diagnostics** in the toolkit sidebar and run either check on visible UVs.

| Tool | What it selects |
| --- | --- |
| **Find Stray Vertices** | Redundant vertices on straight mesh edges of N-gons. A candidate connects exactly two mesh edges. **Angle tolerance** controls how far the two edges may deviate from a straight line. |
| **Find UV Self-Intersections** | UV islands containing crossed polygon edges or overlapping triangle interiors within the same island. |

On the separate **UV Stretch** tab, set **Threshold** and choose **Find Stretched Islands**. The table lists visible islands at or above that percentage. Use the eye button to exclude an island from automatic selection while keeping it in the table. The ignore flag is saved per UV map.

Stretch is the largest directional scale difference on any triangle in the island, accounting for texture aspect ratio. A value of `0%` indicates equal scale in every direction. A collapsed UV triangle can report `∞`.

## Packing, Snap, and clusters

- **Pack Islands** evaluates different positions, angles, and island orders. It defaults to 100 passes and supports 1–1000. If the current placement is unsuitable, the packer tries randomized starts while honoring locks and padding. Press `Esc` to stop the search or `Ctrl+Z` to undo an applied layout.
- **Select Similar** compares the number, positions, and connections of UV vertices, including those inside the outline. **Snap** aligns matching vertices to the reference and keeps the islands stacked during packing.
- **Merge into Cluster** creates a cluster, adds islands, or merges selected clusters. The **UV Clusters** table lets you select or disband a cluster. **Remove Selected** takes specific islands out of it. Packing transforms the cluster as a unit, preserving the relative placement of its members. Apply Snap before clustering if you want islands to overlap exactly.
- **Rotation**, **Size**, and **Position** are independent locks. Unlocked sizes are normalized by 3D surface area. **Overall scale** lets the packer adjust the shared scale to improve tile usage. A member's locks constrain its cluster.

### Texture sizes and padding

| Preset | Gap between islands | Border |
| --- | ---: | ---: |
| 512 × 512 | 4 px | 2 px |
| 1024 × 1024 | 8 px | 4 px |
| 2048 × 2048 | 16 px | 8 px |
| 4096 × 4096 | 32 px | 16 px |
| 8192 × 8192 | 64 px | 32 px |

Both margins are editable in pixels. Choose **Custom resolution** for rectangular textures.

## Hive packing example

<img src="docs/images/hive-models.jpg" width="400" alt="Two copies of the Hive model in Blender">

The UV layouts use the same view scale. The toolkit capture is from version 1.3.0, when the extension was called UV Island Tools.

| Blender Smart UV Project | Toolkit packing (1.3.0) |
| --- | --- |
| <img src="docs/images/hive-smart-uv.jpg" width="420" alt="Hive UV layout after Blender Smart UV Project"> | <img src="docs/images/hive-plugin-uv.jpg" width="420" alt="Hive UV layout packed by the toolkit"> |

## Requirements

- **Blender 5.3.0 or newer.** Version 1.5.0 was tested with Blender 5.3.0 on Windows x64.
- **CPU.** A native Windows x64 module is included, with a Python fallback.
- **GPU.** Blender compute shaders support OpenGL or Vulkan. CPU + GPU hybrid mode and direct CUDA are also available. CUDA requires a compatible NVIDIA GPU and driver.

## Source and feedback

See the [extension source and build instructions](uv_island_tools/) or [open an issue](https://github.com/Rorosos/SARD_UV_Toolkit/issues).

[GNU GPL-3.0-or-later](LICENSE)
