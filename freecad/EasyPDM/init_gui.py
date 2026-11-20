# EasyPDM add-on: loaded by FreeCAD at start-up with the GUI. The add-on uses FreeCAD's
# namespaced layout (freecad/EasyPDM/), so FreeCAD imports this module
# itself -- no InitGui.py and no changes to sys.path. See easypdm_addon.py.
import FreeCAD as App
import FreeCADGui as Gui

try:
    from . import i18n

    i18n.register()  # before anything asks for a translated text

    from . import easypdm_addon

    easypdm_addon.register_commands()
    Gui.addWorkbench(easypdm_addon.EasyPDMWorkbench())
    easypdm_addon.install_menu()

    from . import preferences

    preferences.register()

    from . import scale_watch

    scale_watch.register()  # the SCALE field of an EasyPDM sheet follows Page > Scale
except Exception as e:  # an add-on must never stop FreeCAD from starting
    App.Console.PrintError("EasyPDM add-on failed to load: %s\n" % e)
