# -*- coding: utf-8 -*-
"""QGIS entry point for the interactive educational neutral-line plugin."""


def classFactory(iface):
    from .plugin import EducationalNeutralLinePlugin
    return EducationalNeutralLinePlugin(iface)
