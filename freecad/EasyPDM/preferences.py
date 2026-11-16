# Edit > Preferences > EasyPDM: the server address, the download folder, the menu in every
# workbench, and where the login is kept, with Log out. FreeCAD calls loadSettings when the page
# opens and saveSettings on OK/Apply.

import os

import FreeCAD as App
import FreeCADGui as Gui

from . import easypdm_addon as ea
from . import secure_store
from .easypdm_addon import QtWidgets, _tr


class EasyPDMPreferencePage:
    def __init__(self, parent=None):
        self.form = QtWidgets.QWidget(parent)
        self.form.setWindowTitle("EasyPDM")
        layout = QtWidgets.QFormLayout(self.form)

        self.server = QtWidgets.QLineEdit()
        self.server.setPlaceholderText("http://192.168.1.10:5000")
        layout.addRow(_tr("Server address") + ":", self.server)

        folder_row = QtWidgets.QHBoxLayout()
        self.folder = QtWidgets.QLineEdit()
        browse = QtWidgets.QPushButton(_tr("Browse…"))
        browse.clicked.connect(self._browse)
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        layout.addRow(_tr("Download folder") + ":", folder_row)

        self.everywhere = QtWidgets.QCheckBox(_tr("EasyPDM menu in every workbench"))
        layout.addRow("", self.everywhere)

        self.login = QtWidgets.QLabel()
        self.login.setWordWrap(True)
        layout.addRow(_tr("Login kept in") + ":", self.login)
        account_row = QtWidgets.QHBoxLayout()
        self.signed_in = QtWidgets.QLabel()
        self.signed_in.setWordWrap(True)
        self.logout = QtWidgets.QPushButton(_tr("Log out"))
        self.logout.clicked.connect(self._log_out)
        account_row.addWidget(self.signed_in, 1)
        account_row.addWidget(self.logout)
        layout.addRow("", account_row)

    def _browse(self):
        folder = QtWidgets.QFileDialog.getExistingDirectory(self.form, _tr("Download folder"), self.folder.text())
        if folder:
            self.folder.setText(folder)

    def _show_account(self):
        self.login.setText(secure_store.backend_name())
        self.signed_in.setText(ea.status_text())
        self.logout.setEnabled(bool(ea._token()))

    def _log_out(self):
        ea.log_out()
        self._show_account()

    def loadSettings(self):
        self.server.setText(ea._server_url())
        self.folder.setText(ea._params().GetString("DownloadFolder", ""))
        self.everywhere.setChecked(ea.menu_everywhere())
        self._show_account()

    def saveSettings(self):
        server = self.server.text().strip().rstrip("/")
        if server and "://" not in server:
            server = "http://" + server
        if server.endswith("/api"):
            server = server[:-4]
        p = ea._params()
        if server:
            # The login belongs to a server: another address starts signed out of it.
            p.SetString("ApiBaseUrl", server + "/api")
        p.SetString("DownloadFolder", self.folder.text().strip())
        p.SetBool(ea.MENU_EVERYWHERE, self.everywhere.isChecked())
        ea._sync_menu()
        ea._refresh_panel()


def register():
    # FreeCAD shows a preference group with the icon "preferences-<group in lower case>" from its
    # icon paths, and a question mark without one: icons/preferences-easypdm.svg.
    Gui.addIconPath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons"))
    Gui.addPreferencePage(EasyPDMPreferencePage, "EasyPDM")
