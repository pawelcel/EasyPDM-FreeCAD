# Keeps the SCALE field of an EasyPDM drawing sheet equal to its page's scale.
#
# FreeCAD fills a template's autofill fields only once, when the template is inserted, so
# changing Page > Scale later left "1:1" in the title block until the next Upload, Download or
# Refresh drawing sheet. This observer rewrites pdm_scale whenever a page's Scale (or its
# template) changes -- offline, also for a drawing that is not in EasyPDM yet.
#
# Kept deliberately light, as FreeCAD's Addon Index asks of anything that starts with FreeCAD:
# registering it does nothing else, and each notification only compares two strings unless it
# is about a TechDraw page using the EasyPDM sheet.

import FreeCAD as App

# FreeCAD's own Qt wrapper (Ext/PySide), as the Addon Index asks.
from PySide import QtCore

_observer = None


def _scale_text(scale):
    from . import sheet  # the same formatting Upload and Refresh drawing sheet use
    return sheet._sh_scale_text(scale)


def update_page(page):
    """Writes the page's scale into its EasyPDM sheet; returns True when the field changed."""
    try:
        tpl = page.Template
        texts = dict(tpl.EditableTexts) if tpl is not None else {}
    except Exception:  # page or template deleted meanwhile, or not a template with texts
        return False
    if "pdm_scale" not in texts:
        return False
    value = _scale_text(page.Scale)
    if texts["pdm_scale"] == value:
        return False
    texts["pdm_scale"] = value
    tpl.EditableTexts = texts
    return True


class _ScaleObserver:
    def slotChangedObject(self, obj, prop):
        if prop not in ("Scale", "Template"):
            return
        if getattr(obj, "TypeId", "") != "TechDraw::DrawPage":
            return
        # Not from inside FreeCAD's change notification: change the template once it is done.
        name, doc = obj.Name, obj.Document.Name
        QtCore.QTimer.singleShot(0, lambda: _deferred(doc, name))


def _deferred(doc_name, page_name):
    try:
        doc = App.getDocument(doc_name)
        page = doc.getObject(page_name) if doc is not None else None
        if page is not None:
            update_page(page)
    except Exception as e:  # a closed document, a removed page: nothing to update
        App.Console.PrintLog("EasyPDM: sheet scale not updated: %s\n" % e)


def register():
    global _observer
    if _observer is None:
        _observer = _ScaleObserver()
        App.addDocumentObserver(_observer)
