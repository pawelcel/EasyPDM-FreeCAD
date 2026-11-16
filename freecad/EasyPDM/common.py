# Shared by the add-on's upload and download: settings, the HTTP calls to the EasyPDM API, the
# login (dialogs, tokens in secure_store), the browser hand-over, language and translations,
# window helpers. Split out of the former EasyPDMUpload/EasyPDMDownload macros, where these were
# two copies of the same code.

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import webbrowser
from urllib import error, request
from urllib.parse import quote, urlencode
import FreeCAD as App
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtWidgets
    except ImportError:
        from PySide import QtCore
        from PySide import QtGui as QtWidgets  # bardzo stare FreeCAD (Qt4)

from . import secure_store
from .i18n import translate


PARAM_GROUP = "User parameter:BaseApp/EasyPDM"

DEFAULT_BASE_URL = "http://localhost:5000/api"

SESSION_COOKIE_NAME = "pdm_session"

class AuthError(RuntimeError):
    """Brak sesji albo sesja wygasła/została unieważniona — trzeba się (ponownie) zalogować.
    Odróżniona od zwykłego RuntimeError, żeby ensure_logged_in() wiedziało kiedy pokazać
    okno logowania, zamiast tylko wyświetlić czerwony komunikat błędu."""
    pass

def get_base_url():
    return App.ParamGet(PARAM_GROUP).GetString("ApiBaseUrl", DEFAULT_BASE_URL).rstrip("/")

def set_base_url(url):
    App.ParamGet(PARAM_GROUP).SetString("ApiBaseUrl", url.rstrip("/"))

def set_saved_username(name):
    App.ParamGet(PARAM_GROUP).SetString("SavedDisplayName", name or "")

def get_download_folder():
    """Ostatnio użyty folder docelowy — WSPÓLNA preferencja z download.py
    (ten sam klucz w tej samej grupie), więc oba makra mogą celować w to samo miejsce:
    pobrane pliki i lokalne kopie (Save As) wysyłanych dokumentów lądują razem."""
    folder = App.ParamGet(PARAM_GROUP).GetString("DownloadFolder", "")
    return folder or None

def set_download_folder(folder):
    App.ParamGet(PARAM_GROUP).SetString("DownloadFolder", folder or "")

def working_folder(start=None):
    """The folder uploaded documents are saved into under their PDM name and downloads go to:
    Download folder in Edit > Preferences > EasyPDM. Asked once, with the system's folder
    picker, while it is not set yet. None when the person cancels or it cannot be used."""
    folder = get_download_folder()
    if not folder:
        folder = QtWidgets.QFileDialog.getExistingDirectory(
            _main_window(), t("choose_working_folder_caption"), start or os.path.expanduser("~"))
        if not folder:
            return None
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as e:
        QtWidgets.QMessageBox.critical(_main_window(), t("pdm_title"), t("cannot_use_folder", error=e))
        return None
    set_download_folder(folder)
    return folder

def _auth_headers():
    token = get_session_token()
    return {"Cookie": f"{SESSION_COOKIE_NAME}={token}"} if token else {}

def _read_error_body(http_error):
    try:
        return http_error.read().decode("utf-8") or str(http_error)
    except Exception:
        return str(http_error)

def _raise_for_http_error(e):
    if e.code == 401:
        raise AuthError(_read_error_body(e))
    raise RuntimeError(_read_error_body(e))

def api_post_json(path, payload):
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    headers.update(_auth_headers())
    req = request.Request(get_base_url() + path, data=data, method="POST", headers=headers)
    try:
        with request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as e:
        _raise_for_http_error(e)
    except error.URLError as e:
        raise RuntimeError(t("no_connection", url=get_base_url(), reason=e.reason))

def api_logout():
    """Unieważnia sesję po stronie serwera (POST /api/auth/logout) i zawsze czyści też
    lokalnie zapisany token — nawet jeśli wywołanie się nie powiedzie (np. brak połączenia),
    użytkownik i tak przestaje być "zalogowany" z punktu widzenia tego makra, więc kolejne
    uruchomienie poprosi o ponowne logowanie."""
    token = get_session_token()
    if token:
        req = request.Request(
            get_base_url() + "/auth/logout", method="POST", headers=_auth_headers()
        )
        try:
            request.urlopen(req, timeout=10)
        except Exception:
            pass
    set_session_token(None)
    set_saved_username(None)

def ensure_logged_in():
    """Sprawdza, czy zapisana sesja jest jeszcze ważna (GET /api/auth/me); jeśli jej nie ma
    albo wygasła/została unieważniona, pokazuje okno logowania. Zwraca True, jeśli po
    wywołaniu tej funkcji jest aktywna sesja (można kontynuować), False jeśli użytkownik
    anulował logowanie."""
    if get_session_token():
        try:
            me = api_get("/auth/me")
            # Odświeżamy zapisaną nazwę z /auth/me — bez tego, jeśli token pochodzi z sesji
            # zapisanej wcześniej BEZ przechodzenia przez api_login() w TEJ instalacji (np.
            # ustawiony ręcznie, albo zapisany przez starszą wersję makra), SavedDisplayName
            # zostawałoby puste na zawsze, mimo w pełni ważnej sesji — okno pokazywałoby
            # "Zalogowano jako: ?".
            if me:
                set_saved_username(me.get("displayName") or me.get("username"))
            return True
        except AuthError:
            set_session_token(None)  # token wygasł/nieważny — nie próbuj go już więcej
        except Exception:
            # Np. brak połączenia — nie blokujemy logowaniem na etapie samego sprawdzenia,
            # błąd i tak wypłynie czytelnie przy pierwszym realnym wywołaniu API.
            return True

    # Not signed in (or the token is no longer valid): the add-on's own sign-in, approved in the
    # browser, the same as EasyPDM > Log in -- with the password dialog as its fallback for
    # servers older than 0.9.
    from . import easypdm_addon

    easypdm_addon.log_in()
    return bool(get_session_token())

def sanitize_filename(name):
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", name).strip()
    return cleaned or t("unnamed_fallback")

def revision_label(n):
    """Rewizje jako wielkie litery zamiast cyfr: 1->A, 2->B, ..., 26->Z, 27->AA...
    (jak numeracja kolumn arkusza) — sama liczba w bazie (revisionNumber) się nie zmienia.
    Ta sama konwersja jest po stronie frontu w api/types.ts (revisionLabel)."""
    n = int(n)
    label = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        label = chr(65 + remainder) + label
    return label or "A"

def open_in_browser(url):
    """Otwiera adres w przeglądarce tak, żeby wyszła NA WIERZCH.

    Dotąd było to `webbrowser.open`, który uruchamia po prostu `xdg-open`. Pod Wayland nowy
    proces dostaje fokus tylko wtedy, gdy uruchamiający przekaże mu token aktywacji
    (xdg-activation) — a `webbrowser` żadnego nie przekazuje. KDE otwierało więc kartę w tle
    i jedynie podświetlało przeglądarkę na pasku zadań; trzeba było ją wyciągać ręcznie
    (zgłoszone z praktyki, KDE/Wayland).

    `QDesktopServices.openUrl` robi to samo, ale przez Qt, który od wersji 6.6 prosi
    kompozytor o token w imieniu FreeCAD-a i przekazuje go dalej. Token jest ważny, bo
    w tej chwili fokus ma FreeCAD — użytkownik właśnie uruchomił w nim makro.

    `webbrowser.open` zostaje jako zapas: gdy Qt nie ma tej funkcji albo odmówi (stare
    FreeCAD, brak środowiska graficznego), zachowanie jest dokładnie takie jak dotąd."""
    try:
        try:
            from PySide6 import QtGui
        except ImportError:
            try:
                from PySide2 import QtGui
            except ImportError:
                from PySide import QtGui
        if QtGui.QDesktopServices.openUrl(QtCore.QUrl(url)):
            return
    except Exception:
        pass
    webbrowser.open(url)

# Pełny <title> aplikacji (EasyPDM.Web/index.html — musi się z nim zgadzać co do znaku).
# Okno przeglądarki dopasowujemy po POCZĄTKU
# tytułu, bo przeglądarki doklejają swoją nazwę na końcu. NIE po samym "EasyPDM": u autora
# okno Shotcuta miało w tytule "EasyPDM2.mlt", więc takie dopasowanie wyciągnęłoby na
# wierzch montaż wideo zamiast przeglądarki (wyłapane sondą na żywej sesji KDE).
APP_WINDOW_TITLE = "EasyPDM — CAD item browser"

# Skrypt dla KWin. Szuka zwykłego okna, którego tytuł zaczyna się od tytułu aplikacji, i
# aktywuje je. Plasma 6 ma windowList/activeWindow, Plasma 5 clientList/activeClient.
_KWIN_RAISE_SCRIPT = """
const wins = workspace.windowList ? workspace.windowList() : workspace.clientList();
for (const w of wins) {
    if (w.normalWindow && (%(match)s)) {
        if (workspace.activeWindow !== undefined) workspace.activeWindow = w;
        else workspace.activeClient = w;
        break;
    }
}
"""

# Okno FreeCAD-a: najpierw po numerze procesu, a gdy nie pasuje (FreeCAD z Flatpaka ma w
# piaskownicy inny pid niż ten, który widzi KWin) -- po klasie okna. Kopia z
# download.py.
_KWIN_FREECAD_MATCH = (
    "w.pid === %(pid)d || !wins.some(function (x) { return x.normalWindow && x.pid === %(pid)d; })"
    " && (w.resourceClass || \"\").toLowerCase().indexOf(\"freecad\") >= 0"
)

def _raise_via_kwin(match_js=None):
    """Wyciąga okno przeglądarki na wierzch przez KWin — działa na KDE, także pod Wayland.

    Pod Wayland żadna aplikacja nie może sama aktywować okna innej. Może to jednak zrobić
    kompozytor, a KWin przyjmuje skrypty przez DBus (org.kde.KWin /Scripting) — tak samo
    działa `kdotool`. Skrypt jest zapisywany do pliku tymczasowego, wczytywany, uruchamiany i
    od razu zdejmowany.

    Potrzebne, bo token aktywacji (zob. open_in_browser) pomaga tylko przeglądarce
    URUCHAMIANEJ od zera. Gdy już działa, `xdg-open` startuje jedynie jej krótki proces
    pośredniczący, który przekazuje adres do działającego okna — a czy to okno skorzysta z
    tokenu, zależy od przeglądarki (zgłoszone z praktyki: zamknięta przeglądarka wychodziła na
    wierzch, otwarta — nie).

    `match_js` to warunek JS na oknie `w`; domyślnie okno przeglądarki z EasyPDM (po
    początku tytułu). Ten sam mechanizm wyciąga na wierzch sam FreeCAD -- zob. _show_on_top.

    Zwraca True, gdy skrypt udało się uruchomić — nie mówi, czy okno znalazł. Poza KDE (brak
    gdbus albo usługi org.kde.KWin) po prostu zwraca False."""
    if shutil.which("gdbus") is None:
        return False
    plugin = "easypdm-raise-browser"
    path = None

    def call(object_path, method, *args):
        return subprocess.run(
            ["gdbus", "call", "--session", "--dest", "org.kde.KWin",
             "--object-path", object_path, "--method", method, *args],
            capture_output=True, text=True, timeout=3,
        )

    try:
        fd, path = tempfile.mkstemp(prefix="easypdm-kwin-", suffix=".js")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            # json.dumps daje poprawny literał JS, z polskimi znakami jako \uXXXX.
            if match_js is None:
                match_js = '(w.caption || "").indexOf(%s) === 0' % json.dumps(APP_WINDOW_TITLE)
            f.write(_KWIN_RAISE_SCRIPT % {"match": match_js})
        # Gdyby poprzednie uruchomienie zostawiło skrypt wczytany, loadScript by odmówił.
        call("/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin)
        loaded = call("/Scripting", "org.kde.kwin.Scripting.loadScript", path, plugin)
        found = re.search(r"-?\d+", loaded.stdout or "")
        if loaded.returncode != 0 or not found or int(found.group()) < 0:
            return False
        ran = call(f"/Scripting/Script{found.group()}", "org.kde.kwin.Script.run")
        call("/Scripting", "org.kde.kwin.Scripting.unloadScript", plugin)
        return ran.returncode == 0
    except Exception:
        return False
    finally:
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

def _focus_browser_window():
    """Przenosi okno przeglądarki z EasyPDM na wierzch — odpowiednik `AppActivate "EasyPDM"`
    z makr SolidWorks/Inventor. Tylko dla Linuksa; na Windowsie nie ma tu czego naprawiać.

    Najpierw KWin (KDE, X11 i Wayland — zob. _raise_via_kwin), potem `wmctrl`/`xdotool`
    (inne środowiska pod X11). Poza tym — GNOME pod Wayland — nie zadziała nic, bo kompozytor
    na to nie pozwala; od strony przeglądarki czeka wtedy powiadomienie systemowe, którego
    kliknięcie przełącza na kartę."""
    if _raise_via_kwin():
        return True
    for command in (["wmctrl", "-a", APP_WINDOW_TITLE],
                    ["xdotool", "search", "--name", "^" + re.escape(APP_WINDOW_TITLE), "windowactivate"]):
        if shutil.which(command[0]) is None:
            continue
        try:
            done = subprocess.run(command, timeout=3,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if done.returncode == 0:
                return True
        except Exception:
            pass
    return False

class LoginDialog(QtWidgets.QDialog):
    """Logowanie do EasyPDM — pokazywane przez ensure_logged_in(), gdy nie ma jeszcze
    zapisanej sesji albo poprzednia wygasła/została unieważniona."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("login_dialog_title"))
        self.setMinimumWidth(360)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        self.server_edit = QtWidgets.QLineEdit(get_base_url())
        form.addRow(t("api_address_label"), self.server_edit)

        self.username_edit = QtWidgets.QLineEdit()
        form.addRow(t("username_label"), self.username_edit)

        self.password_edit = QtWidgets.QLineEdit()
        self.password_edit.setEchoMode(QtWidgets.QLineEdit.Password)
        form.addRow(t("password_label"), self.password_edit)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        layout.addWidget(self.error_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.button(QtWidgets.QDialogButtonBox.Ok).setText(t("login_button"))
        buttons.button(QtWidgets.QDialogButtonBox.Cancel).setText(t("cancel_button"))
        buttons.accepted.connect(self._try_login)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _try_login(self):
        self.error_label.setText("")
        set_base_url(self.server_edit.text().strip())
        username = self.username_edit.text().strip()
        password = self.password_edit.text()
        if not username or not password:
            self.error_label.setText(t("login_missing_fields"))
            return
        try:
            api_login(username, password)
        except Exception as e:
            self.error_label.setText(str(e))
            return
        self.accept()

def _main_window():
    """Główne okno FreeCAD jako rodzic dla pytań makra (None bez GUI)."""
    try:
        import FreeCADGui as Gui

        return Gui.getMainWindow()
    except Exception:
        return None

def _show_on_top(icon, title, text):
    """Komunikat, który wychodzi NA WIERZCH, także spod przeglądarki -- zob. tak samo nazwana
    funkcja w download.py. Błąd głównego pliku pada zaraz po wypełnieniu
    formularza, czyli gdy na wierzchu jest przeglądarka."""
    if sys.platform.startswith("linux"):
        _raise_via_kwin(_KWIN_FREECAD_MATCH % {"pid": os.getpid()})
    box = QtWidgets.QMessageBox(icon, title, text, QtWidgets.QMessageBox.Ok, _main_window())
    box.show()
    box.raise_()
    box.activateWindow()
    box.exec()

# --- The login token: kept in the system's secret storage (secure_store.py), per server ------

def get_session_token():
    return secure_store.get(get_base_url())


def set_session_token(token):
    secure_store.set(get_base_url(), token or None)


def get_saved_username():
    return App.ParamGet(PARAM_GROUP).GetString("SavedDisplayName", "") or None


CLIENT_NAME = "EasyPDM for FreeCAD"


def api_get(path):
    req = request.Request(get_base_url() + path, method="GET", headers=_auth_headers())
    try:
        with request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else None
    except error.HTTPError as e:
        _raise_for_http_error(e)
    except error.URLError as e:
        raise RuntimeError(t("no_connection", url=get_base_url(), reason=e.reason))


def api_get_binary(path):
    """Jak api_get, ale zwraca surowe bajty odpowiedzi — do pobierania zawartości plików
    (załączników), które nie są JSON-em."""
    req = request.Request(get_base_url() + path, method="GET", headers=_auth_headers())
    try:
        with request.urlopen(req, timeout=120) as resp:
            return resp.read()
    except error.HTTPError as e:
        _raise_for_http_error(e)
    except error.URLError as e:
        raise RuntimeError(t("no_connection", url=get_base_url(), reason=e.reason))


def api_login(username, password):
    """Loguje się (POST /api/auth/login) i zapisuje token sesji w preferencjach FreeCAD —
    ten sam mechanizm co ApiBaseUrl, więc logowanie przetrwa restart FreeCAD, dopóki sesja
    jest ważna po stronie serwera (30 dni, tak samo jak w aplikacji webowej). Zwraca dict
    użytkownika ({"username", "displayName", "role", ...}, tak jak POST /api/auth/login)."""
    # Logowanie makra (POST /api/auth/macro-login) daje osobny token makra — widoczny i
    # odwoływalny w Ustawienia -> Użytkownicy — zamiast sesji przeglądarki. Odpowiedź ma ten sam
    # kształt co /auth/login, więc reszta działa bez zmian. Serwer sprzed 0.8 nie zna tej ścieżki
    # (404) — wtedy zwykłe logowanie, jak dotąd.
    data = json.dumps({"username": username, "password": password, "client": CLIENT_NAME}).encode("utf-8")

    def _post_login(path):
        req = request.Request(
            get_base_url() + path, data=data, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return (json.loads(raw) if raw else {}), resp.headers.get("Set-Cookie", "")

    try:
        try:
            user, set_cookie_header = _post_login("/auth/macro-login")
        except error.HTTPError as e:
            if e.code != 404:
                raise
            user, set_cookie_header = _post_login("/auth/login")
    except error.HTTPError as e:
        raise RuntimeError(_read_error_body(e))
    except error.URLError as e:
        raise RuntimeError(t("no_connection", url=get_base_url(), reason=e.reason))

    # Token najpierw z treści odpowiedzi (pole "sessionToken" — także dla tokenu makra), potem
    # z ciasteczka, jak dotąd.
    token = user.get("sessionToken") or None
    for part in ([] if token else set_cookie_header.split(";")):
        part = part.strip()
        if part.startswith(f"{SESSION_COOKIE_NAME}="):
            token = part[len(SESSION_COOKIE_NAME) + 1:]
            break
    if not token:
        raise RuntimeError(t("login_failed_no_session"))

    set_session_token(token)
    set_saved_username(user.get("displayName") or user.get("username") or username)
    return user



# Messages of upload and download by key, in English; translated in t() (see i18n.py).
TRANSLATIONS = {
    "no_connection": "Could not connect to {url}: {reason}",
    "login_failed_no_session": "Login failed — the server did not return a session.",
    "pdm_title": "PDM",
    "unnamed_fallback": "unnamed",
    "login_dialog_title": "Log in to PDM",
    "api_address_label": "API address:",
    "username_label": "Username:",
    "password_label": "Password:",
    "login_button": "Log in",
    "cancel_button": "Cancel",
    "assembly_update_note": "Files already in the PDM with status \"In work\" will be updated (their CAD file replaces the same revision).",
    "update_step_checkbox": "Upload a fresh STEP (3D preview) for files already in the PDM",
    "update_pdf_checkbox": "Upload a fresh PDF for files already in the PDM",
    "not_sent_suffix": " — {status}, will not be sent",
    "locked_not_sent": "These files will not be sent — they are in the PDM with a status that blocks changes. To update them, create a new revision or take them out of review:\n\n{lines}",
    "yes_button": "Yes",
    "no_button": "No",
    "login_missing_fields": "Enter your username and password.",
    "sheet_ask_existing_page": "The document has the drawing page \"{page}\" without the EasyPDM sheet.\n\nPut the EasyPDM sheet on it, with the title block filled in from PDM? Its views stay.",
    "cannot_use_folder": "Cannot use this folder: {error}",
    "choose_working_folder_caption": "EasyPDM: folder for downloaded and uploaded files (Edit > Preferences > EasyPDM changes it later)",
    "new_revision_title": "New revision",
    "new_revision_body": "This item has the status \"Released\" — files cannot be added to it.\n\nDo you want to create a new revision (the status will change to \"In progress\")?",
    "revision_comment_label": "Revision comment (optional):",
    "revision_comment_placeholder": "What changed in this revision…",
    "create_revision_button": "Create revision",
    "assembly_detected_title": "Assembly detected",
    "assembly_detected_body": "This document links to {count} other files (parts/sub-assemblies):\n\n{summary}\n\nSend them automatically together with this document (parts/sub-assemblies first, this document last)?\n\n\"No\" will send ONLY this document, as before — without sub-items.",
    "already_in_pdm_as": " -> ALREADY in PDM as #{number} ({name})",
    "already_linked_confirm": "This document looks like an already-uploaded PDM item #{number} ({name}). Attach the current version as a new revision/update of THIS item?\n\n\"No\" opens the regular browser form (New item / Duplicate / Attach to existing).",
    "export_step_prompt": "Export and upload STEP model (3D preview)?",
    "export_pdf_prompt": "Export and upload a PDF file?",
    "new_component_browser_prompt": "New component in the tree: {name}. Click OK to open the browser and fill it in (it may open in the background — check the taskbar).",
    "fetch_items_failed": "Failed to fetch the list of items: {error}",
    "upload_component_failed": "Failed to send {file}: {error}",
    "link_child_failed": "Created {child}, but failed to link it under {parent}: {error}",
    "open_browser_failed": "Failed to open the browser: {error}",
    "wait_timeout": "The waiting time has expired.",
    "wait_ticket_status": "EasyPDM: waiting for the item details to be filled in in the browser...",
    "no_active_document": "No document is open.",
    "document_not_saved": "The document has not been saved yet — choose where to save it.",
    "save_failed": "Failed to save the document: {error}",
    "final_save_failed": "These files could not be saved locally. References to the new names exist only in the open document — save them by hand (Ctrl+S):\n{lines}",
    "cancelled_upload": "Cancelled — the upload was aborted.",
    "nothing_sent": "Cancelled — nothing was sent.",
    "link_subitem_failed": "Failed to link one of the sub-items under the main item: {error}",
    "local_renamed_line": "Local file saved under the PDM name (Save As); the old file under the original name was left untouched:\n{path}",
    "local_already_named_line": "The local file was already under the correct PDM name — nothing needed to be moved:\n{path}",
    "status_revision_mismatch": "The status/revision of item #{number} has already been changed on the server (revision {revision}, status 'w_pracy'), but uploading the file failed: {error}\n\nThe item in PDM now has a new revision, but still has the file from the previous version — fix this manually in the web application (upload the file again) or try the upload once more.",
    "upload_blocked_review": "Cannot upload — item #{number} has status \"Under review\". Wait until the review finishes (the item returns to \"In progress\"), or change the status manually in the web application.",
    "status_label_sprawdzany": "Under review",
    "status_label_wydany": "Released",
    "locked_components_tail": "\n\nNote: {count} already-linked component(s) in the assembly have a locked status — they were NOT updated (the assembly tree never re-sends already-existing components, but these are additionally locked by status, so if you changed them locally, upload them separately after moving the status back to \"In progress\"):\n{lines}",
    "stale_children_confirm": "{count} sub-item(s) of this item exist in PDM, but are no longer in the local assembly structure (removed from the FreeCAD tree since the last upload):\n{lines}\n\nRemove these links from PDM? (The items themselves will NOT be deleted, only their attachment under this assembly.)",
    "easypdm_title": "EasyPDM",
    "easypdm_error_title": "EasyPDM — Error",
    "log_cancelled_not_opened": "Cancelled in the browser — the files downloaded so far are in the folder; the document was not opened.",
    "wait_ticket_status_download": "EasyPDM: waiting for an item to be picked in the browser...",
    "log_no_attachments_list": "  {label}: failed to fetch the attachment list ({error}).",
    "log_no_cad_files": "  {label}: no CAD files to download (the item has no attachments).",
    "log_wrong_format": "  {label}: the attachment marked as the CAD file has an unexpected extension \"{ext}\" (expected .FCStd) — skipping it rather than trying to open the wrong file ({fileName}).",
    "log_already_present": "  {label}: already in the folder (current revision), skipping.",
    "log_relinked": "  {file}: links repointed to the files in this folder ({count}).",
    "log_relink_failed": "  {file}: could not repoint the links ({error}) — open and fix by hand.",
    "newer_revision_title": "Newer revision",
    "newer_revision_body": "The folder already has {label} in revision {rev_list}, and the current revision on the server is {wanted}.\n\nDownload the newest version?",
    "log_keeping_local_revision": "  {label}: keeping the existing local revision ({rev_list}).",
    "log_downloading": "  Downloading {file}...",
    "log_download_error": "  {label}: ERROR downloading {file} ({error}).",
    "log_saved": "  Saved: {file}",
    "log_no_children_list": "  {label}: failed to fetch the list of children ({error}).",
    "log_downloading_top": "Downloading {number} ({name}) to {dir}...",
    "log_opened": "Opened: {path}",
    "log_sheet_refreshed": "Drawing title block refreshed from EasyPDM.",
    "log_open_failed": "Failed to open {path} in FreeCAD: {error}",
    "log_no_main_file": "Failed to determine the main file to open.",
    "fetch_selected_item_failed": "Failed to fetch the selected item's data: {error}",
    "item_no_longer_exists": "The selected item no longer exists.",
    "download_interrupted": "Download interrupted by an unexpected error:\n\n",
    "log_so_far": "\n\nLog so far:\n"
}


def t(key, **kwargs):
    text = translate(TRANSLATIONS.get(key, key), key)
    return text.format(**kwargs) if kwargs else text