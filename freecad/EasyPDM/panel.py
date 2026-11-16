# The EasyPDM document panel: a dock beside the model tree showing the active document's item --
# record name, name, revision, status and who holds the lock -- with buttons for the commands that
# act on it, and for an assembly the tree of its components, each marked whether it is the newest
# file in EasyPDM (structure.py). It asks the server only when the panel is open and the active document changes (or
# on Refresh), never in the background otherwise.

import webbrowser

import FreeCAD as App
import FreeCADGui as Gui

from . import easypdm_addon as ea
from .easypdm_addon import QtCore, QtGui, QtWidgets, _tr
from . import structure
from .i18n import N_

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
        for key in (N_("Record"), N_("Name"), N_("Revision"), N_("Status"), N_("Locked by")):
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
            (N_("Refresh"), None, "Panel"),
            (N_("Open in browser"), None, "EasyPDM"),
            # One button for the lock: Lock for editing or Release lock, by who holds it (_show).
            (N_("Lock for editing"), None, "Lock"),
            (N_("Upload"), "EasyPDM_Upload", "Upload"),
            (N_("Refresh drawing sheet"), "EasyPDM_RefreshSheet", "RefreshSheet"),
        ]):
            b = QtWidgets.QPushButton(QtGui.QIcon(ea._icon(icon)), _tr(key))
            buttons.addWidget(b, i // 2, i % 2)
            self.buttons[key] = b
            if command:
                b.clicked.connect(lambda checked=False, c=command: Gui.runCommand(c))
        self.buttons["Refresh"].clicked.connect(self.refresh)
        self.buttons["Open in browser"].clicked.connect(self.open_in_browser)
        self.buttons["Lock for editing"].clicked.connect(self.toggle_lock)
        layout.addLayout(buttons)
        self.structure_summary = QtWidgets.QLabel()
        self.structure_summary.setWordWrap(True)
        layout.addWidget(self.structure_summary)
        self.structure = QtWidgets.QTreeWidget()
        self.structure.setHeaderLabels([_tr("Document"), _tr("Here"), _tr("EasyPDM"), _tr("State")])
        self.structure.setRootIsDecorated(True)
        self.structure.setUniformRowHeights(True)
        layout.addWidget(self.structure, 1)
        # Takes the spare height while there is no component tree, so a part's panel stays
        # packed at the top instead of Qt spreading the labels over the whole dock.
        self.filler = layout.count()
        layout.addStretch(1)
        self._layout = layout
        self.structure_summary.hide()
        self.structure.hide()
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
        for key in ("Open in browser", "Refresh drawing sheet"):
            self.buttons[key].setEnabled(item is not None)
        self._show_lock(item)

    def _show_lock(self, item):
        """The one lock button, as easypdm_addon.lock_choice decides; the toolbar and menus
        follow (show_lock)."""
        action, text, icon, why = ea.show_lock(item) if item is not None else ea.lock_choice(None)
        button = self.buttons["Lock for editing"]
        button.setText(_tr(text))
        button.setIcon(QtGui.QIcon(ea._icon(icon)))
        button.setToolTip(why)
        button.setEnabled(action is not None)

    def toggle_lock(self):
        Gui.runCommand("EasyPDM_Lock")
        self.refresh()

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
            else:
                status, item = ea.api("GET", "/items/%s" % found["id"])
                self._show(item if status == 200 else found)
        except Exception as e:
            self._show(None, str(e))
        # Also for a document not in EasyPDM yet: its components may well be.
        self._show_structure(doc)

    _STATE_TEXT = {
        structure.CURRENT: N_("✓ newest"),
        structure.OUTDATED: N_("⚠ newer file in EasyPDM"),
        structure.UNKNOWN: N_("• changed here, not uploaded"),
        structure.NOT_IN_PDM: N_("– not in EasyPDM yet"),
        structure.NO_FILE: N_("– no file in EasyPDM"),
    }

    def _show_structure(self, doc):
        """The document and its components with their state; hidden for a document without
        components that is up to date, shown with just a line when it is not."""
        self.structure.clear()
        self.structure_summary.hide()
        self.structure.hide()
        self._layout.setStretch(self.filler, 1)
        try:
            upload = ea.module("upload")
            common = ea.module("common")
            rows = structure.check(doc, common.api_get, common.api_post_json,
                                   upload.discover_component_tree, upload.match_existing_item)
        except structure.ServerTooOld:
            return
        except Exception as e:
            self.structure_summary.setText(_tr("Could not check the components: {error}", error=e))
            self.structure_summary.show()
            return
        stale = structure.outdated(rows)
        if stale:
            self.structure_summary.setText("<b>%s</b>" % _tr(
                "Older than in EasyPDM: {count}. Download the newest before uploading.", count=len(stale)))
        elif len(rows) > 1:
            self.structure_summary.setText(_tr("All components are the newest files in EasyPDM."))
        if stale or len(rows) > 1:
            self.structure_summary.show()
        if len(rows) < 2:
            return
        parents = []
        for row in rows:
            server = row.server or {}
            current = server.get("current") or {}
            local = server.get("localVersion") or {}
            here = local.get("revisionLabel") or structure.local_revision(row.doc) or ""
            state = _tr(self._STATE_TEXT[row.state])
            if row.locked_by:
                state += "  🔒 " + row.locked_by
            label = row.label if row.quantity == 1 else "%s ×%s" % (row.label, row.quantity)
            node = QtWidgets.QTreeWidgetItem([label, here, current.get("revisionLabel") or "", state])
            if row.state == structure.OUTDATED:
                for column in range(4):
                    node.setForeground(column, QtGui.QBrush(QtGui.QColor("#d35400")))
            if current:
                node.setToolTip(3, _tr("In EasyPDM: {file}, uploaded by {who} on {when}",
                                       file=current.get("fileName") or "", who=current.get("uploadedBy") or "?",
                                       when=structure.when(current.get("uploadedAt"))))
            del parents[row.depth:]
            if parents:
                parents[-1].addChild(node)
            else:
                self.structure.addTopLevelItem(node)
            parents.append(node)
        self._layout.setStretch(self.filler, 0)
        self.structure.expandAll()
        for column in range(4):
            self.structure.resizeColumnToContents(column)
        self.structure.show()

    def open_in_browser(self):
        # /?item=<id> opens the item itself (EasyPDM servers from 0.9; older ones show the
        # whole-database view instead).
        if self.item:
            webbrowser.open("%s/?item=%s" % (ea._server_url(), self.item["id"]))


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
