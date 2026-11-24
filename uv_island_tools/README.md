# SARD UV Toolkit

SARD UV Toolkit is a Blender 5.3+ extension for packing, inspecting, and organizing UV islands. Install the ZIP from **Edit → Preferences → Get Extensions → Install from Disk…**. In the UV Editor's `N` sidebar, open **SARD UV Toolkit** or **UV Stretch**.

The [project README](https://github.com/Rorosos/SARD_UV_Toolkit) explains the tools, shows a Hive packing example, and links to the current installer. The extension ID `uv_island_tools` is used for upgrades from the earlier UV Island Tools builds.

## Source layout

- `__init__.py` registers the extension.
- `operators.py` contains the main panel, packing controls, Snap, and locks.
- `blender_data.py` reads UV topology and persists island metadata on mesh faces.
- `geometry.py` matches island topology and measures directional UV stretch.
- `diagnostics.py` finds redundant N-gon vertices and self-intersecting UV islands.
- `island_ui.py` provides cluster tools and the stretch report.
- `i18n.py` contains the extension preferences and interface translations.
- `packing.py` generates candidate layouts and validates exact UV clearance. `gpu_backend.py`, `cuda_backend.py`, and `native_cpu.py` provide optional acceleration.

## Build the extension

Run these commands from the directory containing `blender_manifest.toml`.

```powershell
blender --command extension validate
blender --command extension build --output-filepath sard_uv_toolkit-1.5.0.zip
```

To rebuild the native modules, open the Visual Studio x64 developer shell with the CUDA Toolkit installed. The packaged runtime modules are included in the ZIP.

```powershell
nvcc -ptx -arch=compute_75 --fmad=false cuda_geometry.cu -o cuda_geometry.ptx
cl /O2 /fp:precise /std:c++17 /EHsc /MT /LD /TP cuda_geometry.cu /link /OUT:uvit_cpu_win64.dll
```
