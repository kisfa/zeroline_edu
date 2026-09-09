# -*- coding: utf-8 -*-

def classFactory(iface):
    from .semlegesvonal_plugin import SemlegesvonalPlugin
    return SemlegesvonalPlugin(iface)
