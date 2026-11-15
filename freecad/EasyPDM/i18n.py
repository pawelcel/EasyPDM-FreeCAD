# Translations through Qt, as FreeCAD itself and its add-ons do them: the English text in the code
# is the source, and translations/EasyPDM_<language>.qm (compiled from the .ts next to it by
# tools/update_translations.py) are loaded by FreeCAD for its own language, Preferences > General
# > Language. A text without a translation shows in English.
#
# Two kinds of text go through here: the add-on's own menus, panel and dialogs (_tr in
# easypdm_addon.py, marked N_ where the text is not a literal at the call), and the messages of
# upload and download (common.t), which carry their key as Qt's disambiguation so two keys with
# the same English text can still be translated differently.

import os

import FreeCADGui as Gui

try:
    from PySide6 import QtCore
except ImportError:
    try:
        from PySide2 import QtCore
    except ImportError:
        from PySide import QtCore

CONTEXT = "EasyPDM"
DIRECTORY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "translations")


def register():
    """Adds translations/ to the places FreeCAD looks for .qm files and reloads the language."""
    Gui.addLanguagePath(DIRECTORY)
    Gui.updateLocale()


def translate(text, disambiguation=None):
    return QtCore.QCoreApplication.translate(CONTEXT, text, disambiguation)


def N_(text):
    """Marks a text for tools/update_translations.py where it is translated later, not here."""
    return text
