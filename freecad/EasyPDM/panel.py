# The EasyPDM document panel: a dock beside the model tree showing the active document's item --
# record name, name, revision, status and who holds the lock -- with buttons for the commands that
# act on it. It asks the server only when the panel is open and the active document changes (or
# on Refresh), never in the background otherwise.

import webbrowser

import FreeCAD as App
import FreeCADGui as Gui

from . import easypdm_addon as ea
from .easypdm_addon import QtCore, QtGui, QtWidgets, _tr

_dock = None


class _Panel(QtWidgets.QDockWidget):
    def __init__(self):
        super().__init__("EasyPDM", Gui.getMainWindow())
        self.setObjectName("EasyPDM_DocumentPanel")
        body = QtWidgets.QWidget(self)
        layout = QtWidgets.QVBoxLayout(body)
        self.status_line = QtWidgets.QLabel()
        self.status_line.setWordWrap(True)
        layout.addWidget(self.status_line)
        form = QtWidgets.QFormLayout()
        self.fields = {}
        for key in ("Record", "Name", "Revision", "Status", "Locked by"):
            value = QtWidgets.QLabel("–")
            value.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            value.setWordWrap(True)
            self.fields[key] = value
            form.addRow(_tr(key) + ":", value)
        layout.addLayout(form)
        self.message = QtWidgets.QLabel()
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        buttons = QtWidgets.QGridLayout()
        self.buttons = {}
        for i, (key, command, icon) in enumerate([
            ("Refresh", None, "Panel"),
            ("Open in browser", None, "EasyPDM"),
            ("Lock for editing", "EasyPDM_Lock", "Lock"),
            ("Release lock", "EasyPDM_Release", "Release"),
            ("Upload", "EasyPDM_Upload", "Upload"),
            ("Refresh drawing sheet", "EasyPDM_RefreshSheet", "RefreshSheet"),
        ]):
            b = QtWidgets.QPushButton(QtGui.QIcon(ea._icon(icon)), _tr(key))
            buttons.addWidget(b, i // 2, i % 2)
            self.buttons[key] = b
            if command:
                b.clicked.connect(lambda checked=False, c=command: Gui.runCommand(c))
        self.buttons["Refresh"].clicked.connect(self.refresh)
        self.buttons["Open in browser"].clicked.connect(self.open_in_browser)
        layout.addLayout(buttons)
        layout.addStretch(1)
        self.setWidget(body)
        self.item = None
        self._shown_for = None
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._follow_active_document)
        self.timer.start(1500)

    def _key(self):
        doc = App.ActiveDocument
        return (doc.Name, doc.Label) if doc is not None else None

    def _follow_active_document(self):
        if self.isVisible() and self._key() != self._shown_for:
            self.refresh()

    def _show(self, item, message=""):
        self.item = item
        self.status_line.setText("<i>%s</i>" % ea.status_text())
        if item:
            self.fields["Record"].setText(ea.item_label(item))
            self.fields["Name"].setText(item.get("name") or item.get("fileName") or "")
            self.fields["Revision"].setText(item.get("revisionLabel") or str(item.get("revisionNumber") or ""))
            self.fields["Status"].setText(_tr(item.get("status") or ""))
            locked = item.get("ownerLocked") and item.get("ownerDisplayName")
            self.fields["Locked by"].setText(item.get("ownerDisplayName") if locked else _tr("nobody"))
        else:
            for value in self.fields.values():
                value.setText("–")
        self.message.setText(message)
        for key in ("Open in browser", "Lock for editing", "Release lock", "Refresh drawing sheet"):
            self.buttons[key].setEnabled(item is not None)
        released = item is not None and item.get("status") in ("wydany", "anulowana")
        self.buttons["Lock for editing"].setEnabled(item is not None and not released)
        self.buttons["Release lock"].setEnabled(item is not None and bool(item.get("ownerLocked")))

    def refresh(self):
        self._shown_for = self._key()
        doc = App.ActiveDocument
        if doc is None:
            self._show(None, _tr("No document open."))
            return
        if not ea._token():
            self._show(None, _tr("Not signed in"))
            return
        try:
            found = ea.item_for(doc)
            if found is None:
                self._show(None, _tr("This document is not in EasyPDM yet (upload it first)."))
                return
            status, item = ea.api("GET", "/items/%s" % found["id"])
            self._show(item if status == 200 else found)
        except Exception as e:
            self._show(None, str(e))

    def open_in_browser(self):
        # The web app opens a project from its address; the item is then a click away in the tree.
        if not self.item:
            return
        project = self.item.get("projectId")
        query = "?view=projects&projectId=%s" % project if project else "?view=database"
        webbrowser.open(ea._server_url() + "/" + query)


def toggle():
    global _dock
    mw = Gui.getMainWindow()
    if _dock is None:
        _dock = _Panel()
        mw.addDockWidget(QtCore.Qt.RightDockWidgetArea, _dock)
        _dock.refresh()
        return
    _dock.setVisible(not _dock.isVisible())
    if _dock.isVisible():
        _dock.refresh()


def refresh_if_open():
    if _dock is not None and _dock.isVisible():
        _dock.refresh()
