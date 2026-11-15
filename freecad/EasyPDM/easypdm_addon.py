# EasyPDM add-on for FreeCAD: an EasyPDM workbench with Upload, Download, Log in and Log out,
# instead of running the macros by hand. The same menu can also be shown in every workbench,
# off by default (FreeCAD's Addon Index asks add-ons to keep to their own workbench unless the
# user asks otherwise): "EasyPDM menu in every workbench" in the workbench's menu.
#
# Upload and Download are the macros themselves (EasyPDMUpload.FCMacro, EasyPDMDownload.FCMacro
# next to this file): each menu click loads the macro afresh into its own namespace and calls its
# entry point, exactly as Macro > Execute runs it, so the add-on and the macros can never drift
# apart and nothing of the live-tested upload/download logic is copied here. They share the
# settings in User parameter:BaseApp/EasyPDM (ApiBaseUrl, SavedDisplayName); the login token
# itself is kept in the system's secret storage (secure_store.py), and the macros loaded here
# are handed the add-on's token functions in place of their own plain-parameter ones.
#
# Log in approves the sign-in in the browser (POST /api/auth/device/start, DeviceLoginEndpoints
# on the server): FreeCAD never sees the password, and gets its own macro token, listed and
# revocable under Settings > Users. "Log in with password" falls back to the macros' own login
# dialog, for servers older than 0.9.

import json
import os
import urllib.error
import urllib.request
import webbrowser

import FreeCAD as App
import FreeCADGui as Gui

from . import secure_store

try:
    from PySide import QtCore, QtGui
    QtWidgets = QtGui
except ImportError:  # pragma: no cover
    from PySide6 import QtCore, QtGui, QtWidgets  # type: ignore

if not hasattr(QtWidgets, "QDialog"):
    from PySide import QtWidgets  # FreeCAD's PySide shim keeps widgets there on Qt 6

PARAM_GROUP = "User parameter:BaseApp/EasyPDM"
HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT_NAME = "EasyPDM for FreeCAD"


# Menu texts in FreeCAD's own language (Preferences > General > Language), as the macros do.
_TEXTS = {
    "pl": {"Upload": "Wyślij (Upload)", "Download": "Pobierz (Download)", "Log in…": "Zaloguj…", "Log out": "Wyloguj",
           "EasyPDM menu in every workbench": "Menu EasyPDM w każdym środowisku pracy",
           "Document panel": "Panel dokumentu", "Lock for editing": "Zablokuj do edycji", "Release lock": "Zwolnij blokadę",
           "Refresh drawing sheet": "Odśwież arkusz rysunku",
           "Signed in: {name} ({server})": "Zalogowany: {name} ({server})", "Not signed in": "Niezalogowany",
           "This document is not in EasyPDM yet (upload it first).": "Tego dokumentu nie ma jeszcze w EasyPDM (najpierw go wyślij).",
           "No document open.": "Brak otwartego dokumentu.",
           "Locked for you: {item}": "Zablokowano dla Ciebie: {item}", "Lock released: {item}": "Zwolniono blokadę: {item}",
           "Drawing sheet refreshed on {pages}.": "Odświeżono arkusz rysunku: {pages}.",
           "No page uses the EasyPDM sheet.": "Żadna strona nie używa arkusza EasyPDM.",
           "Record": "Rekord", "Name": "Nazwa", "Revision": "Rewizja", "Status": "Status", "Locked by": "Blokada",
           "nobody": "nikt", "Refresh": "Odśwież", "Open in browser": "Otwórz w przeglądarce",
           "Server address": "Adres serwera", "Download folder": "Folder pobierania", "Browse…": "Wybierz…",
           "Login kept in": "Logowanie zapisane w",
           "w_pracy": "w pracy", "sprawdzany": "sprawdzany", "wydany": "wydany", "anulowana": "anulowany"},
    "de": {"Upload": "Hochladen", "Download": "Herunterladen", "Log in…": "Anmelden…", "Log out": "Abmelden",
           "EasyPDM menu in every workbench": "EasyPDM-Menü in jedem Arbeitsbereich",
           "Document panel": "Dokumentfenster", "Lock for editing": "Zum Bearbeiten sperren", "Release lock": "Sperre aufheben",
           "Refresh drawing sheet": "Zeichnungsblatt aktualisieren",
           "Signed in: {name} ({server})": "Angemeldet: {name} ({server})", "Not signed in": "Nicht angemeldet",
           "This document is not in EasyPDM yet (upload it first).": "Dieses Dokument ist noch nicht in EasyPDM (zuerst hochladen).",
           "No document open.": "Kein Dokument geöffnet.",
           "Locked for you: {item}": "Für Sie gesperrt: {item}", "Lock released: {item}": "Sperre aufgehoben: {item}",
           "Drawing sheet refreshed on {pages}.": "Zeichnungsblatt aktualisiert: {pages}.",
           "No page uses the EasyPDM sheet.": "Keine Seite verwendet das EasyPDM-Blatt.",
           "Record": "Datensatz", "Name": "Benennung", "Revision": "Revision", "Status": "Status", "Locked by": "Gesperrt von",
           "nobody": "niemand", "Refresh": "Aktualisieren", "Open in browser": "Im Browser öffnen",
           "Server address": "Serveradresse", "Download folder": "Download-Ordner", "Browse…": "Durchsuchen…",
           "Login kept in": "Anmeldung gespeichert in",
           "w_pracy": "in Arbeit", "sprawdzany": "in Prüfung", "wydany": "freigegeben", "anulowana": "storniert"},
}


_STATUS_EN = {"w_pracy": "in progress", "sprawdzany": "in review", "wydany": "released", "anulowana": "cancelled"}


def _tr(text, **values):
    lang = App.ParamGet("User parameter:BaseApp/Preferences/General").GetString("Language", "")
    # Empty means FreeCAD follows the system language.
    code = {"Polish": "pl", "German": "de"}.get(lang, lang[:2].lower()) if lang else QtCore.QLocale.system().name()[:2]
    out = _TEXTS.get(code, {}).get(text) or _STATUS_EN.get(text, text)
    return out.format(**values) if values else out


def _params():
    return App.ParamGet(PARAM_GROUP)


def _base_url():
    return _params().GetString("ApiBaseUrl", "http://localhost:5000/api").rstrip("/")


def _server_url():
    base = _base_url()
    return base[:-4] if base.endswith("/api") else base


def _token():
    return secure_store.get(_base_url())


def _signed_in_as():
    return _params().GetString("SavedDisplayName", "") or None


def _post(url, body, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Cookie"] = "pdm_session=" + token
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw) if raw else None
        except ValueError:
            return e.code, {"detail": raw.decode("utf-8", "replace")}


def api(method, path, body=None):
    """A call to the EasyPDM API with the stored login: (status, parsed JSON or None)."""
    headers = {"Content-Type": "application/json"}
    token = _token()
    if token:
        headers["Cookie"] = "pdm_session=" + token
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(_base_url() + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {"detail": raw}


class CommandError(Exception):
    """A message for the person, shown as it is."""


def api_error(status, body):
    """The server's reason in words: it answers refusals with a JSON string, a ProblemDetails
    object or plain text, depending on the endpoint."""
    if isinstance(body, str) and body:
        return body
    if isinstance(body, dict):
        return body.get("detail") or body.get("title") or json.dumps(body)
    return "HTTP %s" % status


_resolver = None


def item_for(doc):
    """The EasyPDM item of `doc` (as GET /items/{id} returns it), or None when it has none.

    The same match the Upload macro makes before an upload: the document's label is the record
    name and revision it was saved under ("C0012(Bracket).B"), and number and name must both
    agree with the item -- so a file merely named like one is not taken for it."""
    global _resolver
    if doc is None:
        return None
    if _resolver is None:
        _resolver = load_macro("EasyPDMUpload.FCMacro")
    return _resolver["match_existing_item_single"](doc)


def require_item(doc):
    if doc is None:
        raise CommandError(_tr("No document open."))
    if not _token():
        raise CommandError(_tr("Not signed in"))
    item = item_for(doc)
    if item is None:
        raise CommandError(_tr("This document is not in EasyPDM yet (upload it first)."))
    return item


def item_label(item):
    return item.get("recordName") or "%s(%s)" % (item.get("itemNumber"), item.get("name") or item.get("fileName"))


def load_macro(file_name):
    """The macro as a module: its globals, without running it (its guard needs __main__)."""
    path = os.path.join(HERE, file_name)
    with open(path, encoding="utf-8") as f:
        source = f.read()
    namespace = {"__name__": "easypdm_" + os.path.splitext(file_name)[0].lower(), "__file__": path}
    exec(compile(source, path, "exec"), namespace)
    # The macros keep the token in FreeCAD's plain parameters; inside the add-on it lives in the
    # system's secret storage instead. They read and write it only through these two functions,
    # which they look up as globals at call time, so replacing them here covers every use.
    base_url = namespace["get_base_url"]
    namespace["get_session_token"] = lambda: secure_store.get(base_url())
    namespace["set_session_token"] = lambda token: secure_store.set(base_url(), token)
    return namespace


class DeviceLoginDialog(QtWidgets.QDialog):
    """Server address, then the browser: shows the code, polls until the person allows it."""

    def __init__(self, parent=None):
        super().__init__(parent or Gui.getMainWindow())
        self.setWindowTitle("EasyPDM – Log in")
        self.setMinimumWidth(460)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("EasyPDM server address:"))
        self.server = QtWidgets.QLineEdit(_server_url())
        layout.addWidget(self.server)
        self.info = QtWidgets.QLabel(
            "EasyPDM opens in the browser. Check that it shows the same code as here and click Allow.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.code = QtWidgets.QLabel("")
        font = self.code.font()
        font.setPointSize(font.pointSize() + 6)
        font.setBold(True)
        self.code.setFont(font)
        self.code.setAlignment(QtCore.Qt.AlignCenter)
        layout.addWidget(self.code)
        buttons = QtWidgets.QHBoxLayout()
        self.password_button = QtWidgets.QPushButton("Log in with password…")
        self.start_button = QtWidgets.QPushButton("Log in in the browser")
        self.start_button.setDefault(True)
        cancel = QtWidgets.QPushButton("Cancel")
        buttons.addWidget(self.password_button)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self.start_button)
        layout.addLayout(buttons)
        self.start_button.clicked.connect(self.start)
        self.password_button.clicked.connect(self.with_password)
        cancel.clicked.connect(self.reject)
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.device_code = None
        self.ticks = 0

    def _server(self):
        url = self.server.text().strip().rstrip("/")
        if url and "://" not in url:
            url = "http://" + url
        return url[:-4] if url.endswith("/api") else url

    def start(self):
        server = self._server()
        if not server:
            return
        try:
            status, body = _post(server + "/api/auth/device/start", {"client": CLIENT_NAME})
        except Exception as e:
            self.info.setText("No connection to %s: %s" % (server, e))
            return
        if status == 404:
            self.info.setText("This EasyPDM server is older than 0.9. Use “Log in with password…”.")
            return
        if status != 200 or not body:
            self.info.setText("The server refused the sign-in (%s)." % status)
            return
        self.device_code = body["deviceCode"]
        self.code.setText(body["userCode"])
        self.info.setText("Waiting for you to allow the sign-in in the browser…")
        self.start_button.setEnabled(False)
        self.server.setEnabled(False)
        self.ticks = 0
        webbrowser.open(server + body["verificationPath"])
        self.timer.start(2000)

    def poll(self):
        self.ticks += 1
        if self.ticks > 300:
            self.timer.stop()
            self.info.setText("The sign-in was not allowed in time. Try again.")
            self.start_button.setEnabled(True)
            self.server.setEnabled(True)
            return
        server = self._server()
        try:
            status, body = _post(server + "/api/auth/device/token", {"deviceCode": self.device_code})
        except Exception:
            return  # a passing network hiccup; the next tick tries again
        if status == 202:
            return
        self.timer.stop()
        if status == 200 and body and body.get("sessionToken"):
            p = _params()
            p.SetString("ApiBaseUrl", server + "/api")
            secure_store.set(server + "/api", body["sessionToken"])
            p.SetString("SavedDisplayName", body.get("displayName") or body.get("username") or "")
            self.accept()
            return
        self.info.setText((body or {}).get("detail") or "The sign-in did not go through (%s)." % status)
        self.start_button.setEnabled(True)
        self.server.setEnabled(True)

    def with_password(self):
        server = self._server()
        if server:
            _params().SetString("ApiBaseUrl", server + "/api")
        self.timer.stop()
        macro = load_macro("EasyPDMUpload.FCMacro")
        if macro["LoginDialog"]().exec() == QtWidgets.QDialog.Accepted:
            self.accept()


def log_in():
    dialog = DeviceLoginDialog()
    if dialog.exec() == QtWidgets.QDialog.Accepted:
        App.Console.PrintMessage("EasyPDM: logged in as %s\n" % (_signed_in_as() or "?"))
        QtWidgets.QMessageBox.information(Gui.getMainWindow(), "EasyPDM",
                                          "Logged in to %s as %s." % (_server_url(), _signed_in_as() or "?"))
        _refresh_panel()


def log_out():
    token = _token()
    if token:
        try:
            _post(_base_url() + "/auth/logout", {}, token)
        except Exception:
            pass  # signed out here anyway; the token can be revoked under Settings > Users
    secure_store.set(_base_url(), None)
    _params().SetString("SavedDisplayName", "")
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), "EasyPDM", "Logged out of EasyPDM.")
    _refresh_panel()


def _notify(message):
    App.Console.PrintMessage("EasyPDM: %s\n" % message)
    QtWidgets.QMessageBox.information(Gui.getMainWindow(), "EasyPDM", message)
    _refresh_panel()


def _set_lock(lock):
    doc = App.ActiveDocument
    item = require_item(doc)
    status, body = api("POST", "/items/%s/%s" % (item["id"], "lock" if lock else "release"))
    if status != 200:
        raise CommandError(api_error(status, body))
    _notify(_tr("Locked for you: {item}" if lock else "Lock released: {item}", item=item_label(item)))


def lock_item():
    _set_lock(True)


def release_item():
    _set_lock(False)


def refresh_sheet():
    """Fills the EasyPDM drawing sheet of the active document with the item's current data,
    without uploading anything -- the same refresh Upload and Download do (refresh_sheets in the
    macros' shared block); pages without the EasyPDM sheet are left alone and nothing is saved."""
    doc = App.ActiveDocument
    item = require_item(doc)
    changed = load_macro("EasyPDMUpload.FCMacro")["refresh_sheets"](doc, item["id"], None, True)
    if changed:
        doc.recompute()
        _notify(_tr("Drawing sheet refreshed on {pages}.", pages=", ".join(p.Label for p in changed)))
    else:
        _notify(_tr("No page uses the EasyPDM sheet."))


def toggle_panel():
    from . import panel
    panel.toggle()


def _refresh_panel():
    try:
        from . import panel
        panel.refresh_if_open()
    except Exception:
        pass


def _icon(name):
    return os.path.join(HERE, "icons", name + ".svg")


class _Command:
    def __init__(self, text, tip, action, icon, needs_document=False):
        self.text, self.tip, self.action, self.icon, self.needs_document = text, tip, action, icon, needs_document

    def GetResources(self):
        return {"MenuText": _tr(self.text), "ToolTip": self.tip, "Pixmap": _icon(self.icon)}

    def IsActive(self):
        return App.ActiveDocument is not None if self.needs_document else True

    def Activated(self):
        try:
            self.action()
        except CommandError as e:
            QtWidgets.QMessageBox.warning(Gui.getMainWindow(), "EasyPDM", str(e))
        except Exception as e:  # never let a click take FreeCAD down
            App.Console.PrintError("EasyPDM: %s\n" % e)
            QtWidgets.QMessageBox.critical(Gui.getMainWindow(), "EasyPDM", str(e))


COMMANDS = [
    ("EasyPDM_Upload", _Command("Upload", "Send the active document to EasyPDM",
                                lambda: load_macro("EasyPDMUpload.FCMacro")["run"](), "Upload", needs_document=True)),
    ("EasyPDM_Download", _Command("Download", "Download an item from EasyPDM with its components",
                                  lambda: load_macro("EasyPDMDownload.FCMacro")["main"](), "Download")),
    ("EasyPDM_Panel", _Command("Document panel", "Show the active document's item in EasyPDM", toggle_panel, "Panel")),
    ("EasyPDM_Lock", _Command("Lock for editing", "Lock the active document's item so only you can change it",
                              lock_item, "Lock", needs_document=True)),
    ("EasyPDM_Release", _Command("Release lock", "Release your lock on the active document's item",
                                 release_item, "Release", needs_document=True)),
    ("EasyPDM_RefreshSheet", _Command("Refresh drawing sheet", "Fill the EasyPDM drawing sheet with the item's current data, without uploading",
                                      refresh_sheet, "RefreshSheet", needs_document=True)),
    ("EasyPDM_LogIn", _Command("Log in…", "Sign in to EasyPDM by approving it in the browser", log_in, "LogIn")),
    ("EasyPDM_LogOut", _Command("Log out", "Sign out of EasyPDM", log_out, "LogOut")),
]
# Where the menus put separators: before these commands.
_GROUP_STARTS = {"EasyPDM_Panel", "EasyPDM_LogIn"}
_TOOLBAR = ["EasyPDM_Upload", "EasyPDM_Download", "EasyPDM_Panel", "EasyPDM_Lock", "EasyPDM_Release"]


ICON = _icon("EasyPDM")
MENU_EVERYWHERE = "MenuInEveryWorkbench"


def menu_everywhere():
    return _params().GetBool(MENU_EVERYWHERE, False)


class _MenuEverywhereCommand:
    """The opt-in for the EasyPDM menu in every workbench, a tick in the workbench's own menu."""

    def GetResources(self):
        return {"MenuText": _tr("EasyPDM menu in every workbench"),
                "ToolTip": "Show the EasyPDM menu in every workbench, not only in EasyPDM",
                "Checkable": menu_everywhere()}

    def IsActive(self):
        return True

    def Activated(self, checked=None):
        on = (not menu_everywhere()) if checked is None else bool(checked)
        _params().SetBool(MENU_EVERYWHERE, on)
        _sync_menu()


def register_commands():
    for name, command in COMMANDS:
        Gui.addCommand(name, command)
    Gui.addCommand("EasyPDM_MenuEverywhere", _MenuEverywhereCommand())


def _global_menu_action(bar):
    return next((a for a in bar.actions() if a.objectName() == "EasyPDM_Menu"), None)


# The menu in every workbench, when the user turned it on. FreeCAD rebuilds the menu bar whenever
# the workbench changes, so it is put back after every switch, at the end of the bar, before Help
# when there is one. In the EasyPDM workbench its own menu is there already.
def status_text():
    if not _token():
        return _tr("Not signed in")
    return _tr("Signed in: {name} ({server})", name=_signed_in_as() or "?", server=_server_url())


def _show_status(menu):
    """Puts who is signed in, and to which server, at the top of an EasyPDM menu, freshly each
    time it opens (a disabled entry: information, not a command)."""
    status = next((a for a in menu.actions() if a.objectName() == "EasyPDM_Status"), None)
    if status is None:
        first = menu.actions()[0] if menu.actions() else None
        status = QtGui.QAction(menu) if hasattr(QtGui, "QAction") else QtWidgets.QAction(menu)
        status.setObjectName("EasyPDM_Status")
        status.setEnabled(False)
        menu.insertAction(first, status)
        menu.insertSeparator(first)
    status.setText(status_text())


def _decorate_menus(bar):
    for action in bar.actions():
        menu = action.menu()
        if menu is None or action.text().replace("&", "") != "EasyPDM" or menu.property("easypdm_status"):
            continue
        menu.setProperty("easypdm_status", True)
        menu.aboutToShow.connect(lambda m=menu: _show_status(m))


def _sync_menu(*_):
    mw = Gui.getMainWindow()
    bar = mw.menuBar()
    ours = _global_menu_action(bar)
    if not menu_everywhere():
        if ours is not None:
            bar.removeAction(ours)
        _decorate_menus(bar)
        return
    for action in bar.actions():
        if action is ours or action.text().replace("&", "") == "EasyPDM":
            _decorate_menus(bar)
            return
    menu = QtWidgets.QMenu("&EasyPDM", mw)
    menu.menuAction().setObjectName("EasyPDM_Menu")
    for name, command in COMMANDS:
        if name in _GROUP_STARTS:
            menu.addSeparator()
        action = menu.addAction(QtGui.QIcon(_icon(command.icon)), _tr(command.text))
        action.setToolTip(command.tip)
        action.triggered.connect(lambda checked=False, n=name: Gui.runCommand(n))
    help_action = next((a for a in bar.actions() if a.text().replace("&", "").lower() in ("help", "pomoc", "hilfe")), None)
    if help_action is not None:
        bar.insertMenu(help_action, menu)
    else:
        bar.addMenu(menu)
    _decorate_menus(bar)


def install_menu():
    mw = Gui.getMainWindow()
    mw.workbenchActivated.connect(lambda *_: QtCore.QTimer.singleShot(0, _sync_menu))
    QtCore.QTimer.singleShot(0, _sync_menu)


class EasyPDMWorkbench(Gui.Workbench):
    """The EasyPDM workbench: its menu and toolbar hold the add-on's commands."""

    MenuText = "EasyPDM"
    ToolTip = "Upload to and download from an EasyPDM server"
    Icon = ICON

    def Initialize(self):
        menu = []
        for name, _ in COMMANDS:
            if name in _GROUP_STARTS:
                menu.append("Separator")
            menu.append(name)
        self.appendToolbar("EasyPDM", _TOOLBAR)
        self.appendMenu("EasyPDM", menu + ["Separator", "EasyPDM_MenuEverywhere"])

    def GetClassName(self):
        return "Gui::PythonWorkbench"
