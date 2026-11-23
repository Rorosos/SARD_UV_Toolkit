"""Blender entry point for SARD UV Toolkit."""


def register():
    from . import diagnostics, i18n, island_ui, operators

    i18n.register()
    operators.register()
    island_ui.register()
    diagnostics.register()


def unregister():
    from . import diagnostics, i18n, island_ui, operators

    diagnostics.unregister()
    island_ui.unregister()
    operators.unregister()
    i18n.unregister()
