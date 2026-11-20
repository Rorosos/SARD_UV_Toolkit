"""Blender entry point for UV Island Tools."""


def register():
    from . import operators

    operators.register()


def unregister():
    from . import operators

    operators.unregister()
