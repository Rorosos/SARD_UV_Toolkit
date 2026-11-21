"""Blender entry point for UV Island Tools."""


def register():
    from . import island_ui, operators

    operators.register()
    island_ui.register()


def unregister():
    from . import island_ui, operators

    island_ui.unregister()
    operators.unregister()
