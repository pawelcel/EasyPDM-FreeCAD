# -*- coding: utf-8 -*-
"""
OTWIERANIE Części/Złożeń z EasyPDM (pobiera z serwera i od razu otwiera w FreeCAD):
polecenie Download dodatku EasyPDM (dawniej makro EasyPDMDownload.FCMacro, stąd "makro" w
opisach niżej).

Logowanie i adres API są WSPÓLNE z upload.py (te same preferencje FreeCAD,
User parameter:BaseApp/EasyPDM) — zalogowanie się w jednym makrze starcza dla obu. Makro
potrzebuje własnej sesji, mimo że wybór elementu zapada w przeglądarce — to ono odpytuje,
czy przeglądarka już skończyła (GET /api/create-tickets/{ticket}), i to ono ściąga same
pliki (GET /api/attachments/{id}/file) — przeglądarka tylko WSKAZUJE co pobrać, nie
przesyła żadnych bajtów. Ta sama sesja loguje przeglądarkę automatycznie (GET
/api/auth/browser-login) — jedno logowanie w makrze, nie dwa osobne.

Co robi:
    1. Natywne okno pyta TYLKO o folder docelowy (domyślnie podpowiada ostatnio użyty,
       zapamiętany w preferencjach FreeCAD, z przyciskiem "..." do zmiany) i pokazuje
       konto/Wyloguj — dokładnie jak "Wyślij do PDM" w upload.py. WYBÓR,
       KTÓRĄ Część/Złożenie pobrać, zapada w PRZEGLĄDARCE SYSTEMOWEJ, nie tutaj: po
       zatwierdzeniu folderu makro od razu otwiera przeglądarkę, już zalogowaną (jednorazowy
       bilet logowania, nie sam token sesji makra), na pasku "oczekuje żądanie pobrania z makra CAD" (widoczny na
       każdym ekranie aplikacji webowej) z wyszukiwarką Części/Złożenia z CAŁEJ bazy (po
       numerze albo nazwie) — ten sam mechanizm co dogrywanie pliku do istniejącego
       elementu w upload.py, tu użyty do wskazania "co pobrać". Po zatwierdzeniu
       w przeglądarce, FreeCAD (okno "Czekam na przeglądarkę", odpytujące co ~2s, limit
       10 minut) samo wykrywa wybór i pobieranie zaczyna się automatycznie — nie trzeba
       wracać do FreeCAD ręcznie. Anulowanie w przeglądarce/oknie oczekiwania kończy makro
       bez pobierania niczego.
    2. Dla Złożenia: pobiera też WSZYSTKIE jego składniki rekurencyjnie (bezpośrednie dzieci,
       potem ich dzieci, i tak dalej — cały BOM), do TEGO SAMEGO folderu co plik główny.
       Bez tego złożenie zbudowane na odnośnikach App::Link do zewnętrznych, zapisanych
       plików (standard w workbenchu Assembly/Assembly4) nie miałoby czym się otworzyć —
       FreeCAD rozwiązuje te odnośniki dopiero przy otwieraniu dokumentu, więc pliki
       składników muszą już leżeć na dysku PRZED otwarciem pliku głównego.
    3. Dla każdego pliku: jeśli w folderze docelowym jest już plik o DOKŁADNIE tej samej
       nazwie (czyli tej samej rewizji) i tym samym rozmiarze co na serwerze — pomija
       (nie pobiera drugi raz).
    4. Jeśli w folderze jest już plik tego samego elementu, ale w INNEJ (starszej) rewizji,
       a na serwerze jest nowsza — pyta, czy pobrać nowszą, zamiast cicho nadpisywać albo
       cicho zostawiać nieaktualny plik.
    5. Na końcu otwiera główny (wybrany) plik w FreeCAD (App.openDocument) — pliki składników
       zostają tylko na dysku, nie są automatycznie otwierane jako osobne dokumenty (dokładnie
       tak, jak FreeCAD sam otwiera złożenie: linkowane pliki wczytuje w tle, bez oddzielnych
       okien).

Skąd bierze pliki do pobrania:
    EasyPDM przechowuje AKTUALNY plik CAD Części/Złożenia jako załącznik (nie ma osobnego
    mechanizmu "plik elementu") — a przy KAŻDEJ wysyłce nowej rewizji poprzednia kopia
    ZOSTAJE (nowy załącznik obok starego, różne nazwy: "numer (nazwa).REWIZJA.rozszerzenie",
    ta sama konwencja co upload.py), więc historia rewizji jest w praktyce
    odtwarzalna z listy załączników. To makro rozpoznaje tę konwencję, żeby trafić w
    załącznik odpowiadający AKTUALNEJ rewizji elementu (item["revisionNumber"]) — jeśli
    element nigdy nie przeszedł przez żadne makro CAD (np. dograny ręcznie w aplikacji
    webowej, więc załączniki mają dowolne, oryginalne nazwy), bierze po prostu najnowiej
    wgrany załącznik jako najlepsze przybliżenie.

Ograniczenia (świadomie poza zakresem pierwszej wersji):
    - Wybór elementu (punkt 1) wymaga, żeby domyślna przeglądarka systemowa umiała otworzyć
      adres serwera PDM (ten sam, co adres API w preferencjach makra) — na typowej
      instalacji (klient i serwer w tej samej sieci) działa to bez dodatkowej konfiguracji.
      Okno oczekiwania w FreeCAD ma limit 10 minut — po przekroczeniu (albo Anuluj) makro
      kończy się bez pobierania niczego.
    - Nie próbuje pobierać KONKRETNEJ starszej rewizji — zawsze celuje w aktualną, a starsze
      lokalne kopie służą tylko do wykrycia "masz nieaktualną wersję" (patrz punkt 4).
    - Wszystkie pliki (główny + składniki) lądują płasko w JEDNYM folderze, bez odtwarzania
      struktury BOM jako podfolderów — to najbezpieczniejszy wybór dla odnośników App::Link
      zapisanych jako ścieżki WZGLĘDEM folderu dokumentu (typowe dla Assembly4), ale jeśli
      oryginalny model był budowany z plikami w osobnych podfolderach, odnośniki mogą mimo
      to nie rozwiązać się automatycznie — wtedy trzeba je poprawić ręcznie w FreeCAD
      (Assembly4 ma do tego narzędzie "Make link relative"/zmianę ścieżki).
    - Współdzielony komponent (użyty w kilku miejscach drzewa) pobierany jest tylko raz
      (rozpoznawany po ID elementu), tak samo jak w upload.py.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import uuid
import webbrowser
from urllib import error, request
from urllib.parse import urlencode
import FreeCAD as App
try:
    from PySide6 import QtCore, QtWidgets
except ImportError:
    try:
        from PySide2 import QtCore, QtWidgets
    except ImportError:
        from PySide import QtCore
        from PySide import QtGui as QtWidgets  # bardzo stare FreeCAD (Qt4)

from .common import (  # noqa: F401
    _auth_headers,
    _focus_browser_window,
    _show_on_top,
    api_get,
    api_get_binary,
    api_logout,
    api_post_json,
    ensure_logged_in,
    get_base_url,
    get_download_folder,
    get_saved_username,
    open_in_browser,
    revision_label,
    sanitize_filename,
    set_download_folder,
    t,
)
from .sheet import (  # noqa: F401
    refresh_sheets,
)


def build_browser_download_url(ticket):
    """Adres, pod którym otwiera się przeglądarka systemowa zamiast natywnej wyszukiwarki
    Części/Złożenia (zob. wait_for_ticket/main) — most logowania bilet->ciasteczko
    (GET /api/auth/browser-login) plus deep-link "?ticket=&mode=download"
    (pending-create-ticket.ts w aplikacji webowej) — "mode=download" mówi PendingTicketBanner,
    żeby od razu pokazać samą wyszukiwarkę (bez opcji "nowy element", nieistotnej przy
    pobieraniu) i pominąć checkbox STEP (dotyczy tylko wysyłania). Element wskazuje się przez
    POST /create-tickets/{ticket}/attach-existing — ten sam endpoint co przy dogrywaniu pliku
    w upload.py, tu użyty do czystego wskazania "co pobrać", bez tworzenia ani
    zmieniania niczego. "ticket" w query stringu /auth/browser-login (bilet logowania,
    jednorazowy, świeżo pobrany z POST /auth/browser-bridge-ticket -- NIGDY sam token sesji,
    żeby ten nie lądował w historii przeglądarki) to inny byt niż "ticket" wewnątrz
    zakodowanego "redirect" (bilet korelacji wyboru elementu, argument tej funkcji). Frontend
    i API dzielą jeden origin, więc "redirect" to zawsze ścieżka względna zaczynająca się od
    "/" — dokładnie to, co GET /auth/browser-login akceptuje."""
    redirect_path = "/?" + urlencode({"ticket": ticket, "mode": "download"})
    login_ticket = api_post_json("/auth/browser-bridge-ticket", {})["ticket"]
    login_params = {"ticket": login_ticket, "redirect": redirect_path}
    return f"{get_base_url()}/auth/browser-login?{urlencode(login_params)}"

# ============================================================================
# Postęp pobierania pokazywany w aplikacji webowej jako lista plików odhaczana w trakcie
# (zob. TransferProgressStore.cs / TransferProgressPanel.tsx). Bliźniacze do tych samych
# funkcji w upload.py.
#
# CELOWO nie korzysta z api_get: tamto rzuca wyjątkiem przy błędzie HTTP, a raportowanie
# postępu NIE MOŻE przerwać pobierania.
# ============================================================================

def _progress_send(method, path, payload):
    try:
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        headers.update(_auth_headers())
        req = request.Request(get_base_url() + path, data=data, method=method, headers=headers)
        with request.urlopen(req, timeout=10):
            pass
    except Exception:
        pass

def progress_start(kind, entries):
    if not entries:
        return
    _progress_send("PUT", "/progress", {
        "kind": kind,
        "entries": [{"key": k, "label": l} for k, l in entries],
    })

def progress_mark(key, status):
    if key:
        _progress_send("PATCH", "/progress", {"key": key, "status": status})

# Użytkownik kliknął „Anuluj" w panelu postępu — zob. transfer_cancelled. Słownik, nie
# zwykła zmienna, żeby funkcje mogły go zmieniać bez `global`; przypisanie na poziomie modułu
# wykonuje się przy każdym uruchomieniu makra, więc stan nie przechodzi na kolejny bieg.
_CANCEL = {"requested": False}

def transfer_cancelled():
    """Czy użytkownik kliknął „Anuluj" w panelu postępu w przeglądarce.

    Serwer niczego sam nie przerywa — tylko zapisuje prośbę (POST /api/progress/cancel) — więc
    to makro pyta o nią przy każdym odpytaniu o formularz i przed każdym kolejnym plikiem. Plik,
    który akurat leci, zostaje dokończony: przerwanie w połowie zostawiłoby go uszkodzonego.

    Pierwsze „tak" jest zapamiętywane, żeby nie pytać serwera za każdym razem. Każdy błąd
    (brak połączenia, starszy serwer bez tego endpointu) znaczy „nie anulowano" — to wygoda,
    która nie ma prawa zatrzymać przesyłania."""
    if not _CANCEL["requested"]:
        try:
            probe = api_get("/progress/cancelled")
            if probe and probe.get("cancelled") == 1:
                _CANCEL["requested"] = True
                App.Console.PrintMessage(
                    "EasyPDM: anulowano w przegladarce -- zatrzymuje sie przed kolejnym plikiem\n"
                )
        except Exception:
            pass
    return _CANCEL["requested"]

def progress_finish():
    _progress_send("POST", "/progress/finish", {})

def _revision_attachment_pattern(item_number, name):
    """Regex dopasowujący własną konwencję nazewnictwa makr PDM: "numer (nazwa).REWIZJA."
    — grupa 1 to litera rewizji. Ta sama nazwa co nada upload.py (zob. tam
    _rename_and_upload) — dzięki temu pobieranie i wysyłanie zawsze się zgadzają."""
    # [A-Za-z]*0* przed numerem: nazwa moze miec literowy prefiks rodzaju i zera wiodace
    # (Ustawienia -> Nazewnictwo), a zalaczniki wgrane przed wlaczeniem tych ustawien maja
    # sam numer -- oba warianty musza pasowac, inaczej pobieranie przestaloby widziec
    # wlasne starsze pliki.
    return re.compile(
        rf"^[A-Za-z]*0*{item_number}\s*(?:\({re.escape(sanitize_filename(name))}\))?\.([A-Za-z]+)\.",
        re.IGNORECASE,
    )

def _find_current_attachment(item, attachments):
    """Wybiera załącznik odpowiadający AKTUALNEJ rewizji elementu.

    Preferowana ścieżka: dokładne dopasowanie po item_attachments.revision_number --
    serwer oznacza nim każdy załącznik "cad"/"drawing" numerem rewizji elementu z chwili
    wgrania (migracja 049), więc to jest autorytatywne, bez zgadywania z nazwy pliku.
    Fallback (dla załączników wgranych PRZED istnieniem tej kolumny): dopasowanie po
    konwencji nazw makr PDM. Jeśli i to nie znajdzie nic (np. element dograny ręcznie w
    aplikacji webowej), bierze po prostu najnowiej wgrany załącznik (lista jest posortowana
    rosnąco po dacie) jako najlepsze przybliżenie.

    Rozważane są TYLKO załączniki z rolą "cad" (albo bez roli w ogóle -- starsze/ręcznie
    dograne pliki sprzed wprowadzenia ról, traktowane jako CAD dla wstecznej zgodności).
    Załączniki "step"/"pdf" to osobne eksporty do podglądu, nigdy pliki do otwarcia w CAD
    -- bez tego filtra powyższy fallback "najnowiej wgrany" mógł (i realnie potrafił, po
    dodaniu eksportu PDF, który wgrywa się na końcu) wybrać PDF zamiast właściwego pliku
    CAD, co kończyło się błędem przy próbie otwarcia go jako dokumentu FreeCAD."""
    attachments = [a for a in attachments if a.get("role") in (None, "cad")]
    if not attachments:
        return None

    wanted_revision = item.get("revisionNumber")
    if wanted_revision:
        for a in attachments:
            if a.get("revisionNumber") == wanted_revision:
                return a

    number = item.get("itemNumber")
    name = item.get("fileName", "")
    if number is not None:
        pattern = _revision_attachment_pattern(number, name)
        matches = []
        for a in attachments:
            m = pattern.match(a["fileName"])
            if m:
                matches.append((m.group(1), a))
        if matches:
            # Serwer wysyła gotowe "revisionLabel" obok "revisionNumber" (zob.
            # RevisionLabeling.cs) -- wolimy je od lokalnego przeliczenia, revision_label()
            # zostaje tylko jako fallback dla starszego serwera bez tego pola.
            wanted = (item.get("revisionLabel") or revision_label(item["revisionNumber"])).upper() if item.get("revisionNumber") else None
            for label, a in matches:
                if wanted and label.upper() == wanted:
                    return a
            return matches[-1][1]
    return attachments[-1]

def _local_revision_files(target_dir, item_number, name):
    """Lokalne pliki w target_dir pasujące do konwencji nazw TEGO elementu (dowolna
    rewizja) — do wykrycia "mam już starszą rewizję" (patrz _download_item)."""
    if item_number is None:
        return []
    pattern = _revision_attachment_pattern(item_number, name)
    result = []
    try:
        for fname in os.listdir(target_dir):
            m = pattern.match(fname)
            if m:
                result.append((m.group(1), os.path.join(target_dir, fname)))
    except OSError:
        pass
    return result

def _download_item(item, target_dir, log, downloaded=None):
    """Cienka nakładka na właściwe pobieranie, pilnująca wyłącznie listy postępu.

    Kluczem pozycji jest ID elementu — to samo, które zwrócił serwer w /descendants.
    Nakładka zamiast wstawek w środku, bo _download_item_inner ma pięć punktów wyjścia i
    może rzucić wyjątkiem; tutaj każda z tych ścieżek odhacza pozycję dokładnie raz, a
    nieudane pobranie zostaje na liście oznaczone jako błąd zamiast wisieć jako "w toku"."""
    progress_mark(item["id"], "active")
    try:
        result = _download_item_inner(item, target_dir, log)
        if result and downloaded is not None:
            downloaded.append(result)
    except Exception:
        progress_mark(item["id"], "failed")
        raise
    progress_mark(item["id"], "done" if result else "failed")
    return result

def _download_item_inner(item, target_dir, log):
    """Pobiera aktualny plik CAD Części/Złożenia `item` do target_dir (patrz reguły 3 i 4
    w docstringu modułu). Zwraca ścieżkę do pliku, który finalnie jest/zostaje w folderze
    (świeżo pobrany, już tam był, albo — gdy użytkownik odmówił pobrania nowszej rewizji —
    ta stara, którą i tak ma), albo None, jeśli nic nie udało się ustalić."""
    number = item.get("itemNumber")
    name = item.get("fileName", "")
    label = f"{item.get('itemNumberLabel') or number}({name})"

    try:
        attachments = api_get(f"/items/{item['id']}/attachments") or []
    except Exception as e:
        log(t("log_no_attachments_list", label=label, error=e))
        return None

    current = _find_current_attachment(item, attachments)
    if current is None:
        log(t("log_no_cad_files", label=label))
        return None

    # Dodatkowe zabezpieczenie NIEZALEŻNE od filtrowania po roli w _find_current_attachment
    # -- gdyby jednak trafił się załącznik z rolą "cad" (albo bez roli) o nieoczekiwanym
    # rozszerzeniu (np. ręcznie podmieniony w aplikacji webowej), makro odmawia otwarcia
    # go jako dokumentu FreeCAD zamiast wywalać się z niejasnym błędem natywnym.
    current_ext = os.path.splitext(current["fileName"])[1].lower()
    if current_ext != ".fcstd":
        log(t("log_wrong_format", label=label, ext=current_ext, fileName=current["fileName"]))
        return None

    target_path = os.path.join(target_dir, current["fileName"])

    if os.path.exists(target_path):
        try:
            same_size = os.path.getsize(target_path) == current.get("fileSize")
        except OSError:
            same_size = False
        if same_size:
            log(t("log_already_present", label=label))
            return target_path

    older = [
        (rev, path)
        for rev, path in _local_revision_files(target_dir, number, name)
        if path != target_path
    ]
    if older:
        rev_list = ", ".join(sorted({rev for rev, _ in older}))
        wanted = (item.get("revisionLabel") or revision_label(item["revisionNumber"])) if item.get("revisionNumber") else "?"
        answer = QtWidgets.QMessageBox.question(
            None,
            t("newer_revision_title"),
            t("newer_revision_body", label=label, rev_list=rev_list, wanted=wanted),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            log(t("log_keeping_local_revision", label=label, rev_list=rev_list))
            return older[0][1] if len(older) == 1 else None

    log(t("log_downloading", file=current["fileName"]))
    try:
        content = api_get_binary(f"/attachments/{current['id']}/file")
    except Exception as e:
        log(t("log_download_error", label=label, file=current["fileName"], error=e))
        return None

    os.makedirs(target_dir, exist_ok=True)
    with open(target_path, "wb") as f:
        f.write(content)
    log(t("log_saved", file=current["fileName"]))
    return target_path

def _flatten_xlinks(file_paths, log):
    """Przepina odnośniki App::Link na pliki leżące OBOK, w tym samym folderze.

    Pobieranie kładzie wszystko płasko w jednym folderze, ale złożenie pamięta ścieżkę
    sprzed wysyłki — jeśli komponenty były wtedy w podfolderze, w pliku zostaje
    `<XLink file="test/8(1ddd).A.FCStd" .../>`. FreeCAD rozwiązuje to WZGLĘDEM folderu
    złożenia, czyli szuka w `.../test/test/...` i zgłasza "Link not restored" oraz
    "Link broken!". Zgłoszone z praktyki: pobrane złożenie otwierało się bez komponentów.

    .FCStd to archiwum ZIP, a ścieżki odnośników to atrybut `file` elementów `<XLink>`
    w Document.xml. Obcinamy z nich katalog — i TYLKO wtedy, gdy plik o tej nazwie
    faktycznie leży w tym samym folderze. Dzięki temu odnośnik, którego nie pobraliśmy
    (coś spoza tego drzewa), zostaje nietknięty zamiast zostać wskazany w próżnię.

    Zapis idzie przez plik tymczasowy i dopiero potem podmianę, żeby przerwanie w trakcie
    nie zostawiło uszkodzonego dokumentu. Każdy błąd jest połykany: to naprawa wygody, a nie
    część pobierania — nieudana nie może wywrócić tego, co już się udało ściągnąć."""
    pattern = re.compile(rb'(<XLink\b[^>]*?\bfile=")([^"]+)(")')
    repaired_total = 0

    for path in file_paths:
        if not path or not path.lower().endswith(".fcstd") or not os.path.exists(path):
            continue
        folder = os.path.dirname(path)
        try:
            with zipfile.ZipFile(path, "r") as zf:
                entries = [(i, zf.read(i.filename)) for i in zf.infolist()]
        except Exception as e:
            log(t("log_relink_failed", file=os.path.basename(path), error=e))
            continue

        changed = 0

        def fix(m):
            nonlocal changed
            stored = m.group(2).decode("utf-8", "replace")
            base = os.path.basename(stored.replace("\\", "/"))
            # Już płaski albo nie mamy takiego pliku obok -- nie ruszamy.
            if stored == base or not os.path.exists(os.path.join(folder, base)):
                return m.group(0)
            changed += 1
            return m.group(1) + base.encode("utf-8") + m.group(3)

        new_entries = []
        for info, data in entries:
            if info.filename.lower().endswith(".xml"):
                data = pattern.sub(fix, data)
            new_entries.append((info, data))

        if changed == 0:
            continue

        try:
            tmp = path + ".easypdm-relink"
            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
                for info, data in new_entries:
                    zf.writestr(info.filename, data)
            os.replace(tmp, path)
            repaired_total += changed
            log(t("log_relinked", file=os.path.basename(path), count=changed))
        except Exception as e:
            try:
                os.remove(tmp)
            except Exception:
                pass
            log(t("log_relink_failed", file=os.path.basename(path), error=e))

    return repaired_total

def _download_children_recursive(item, target_dir, log, seen, downloaded=None):
    """Rekurencyjnie pobiera CAŁE drzewo składników Złożenia (bezpośrednie dzieci, potem
    ich dzieci, itd.) do target_dir — patrz punkt 2 w docstringu modułu. `seen` (zbiór ID
    elementów) chroni przed podwójnym pobraniem tego samego, współdzielonego komponentu."""
    try:
        rows = api_get(f"/items/{item['id']}/children") or []
    except Exception as e:
        label = f"{item.get('itemNumberLabel') or item.get('itemNumber')}({item.get('fileName')})"
        log(t("log_no_children_list", label=label, error=e))
        return
    # UWAGA: odpowiedź to lista {"item": {...}, "quantity": ..., "position": ...} — sam
    # element jest ZAGNIEŻDŻONY pod kluczem "item" (ta sama konwencja co childEntries
    # w item-detail-panel.tsx), NIE płaski obiekt jak w GET /api/items.
    for row in rows:
        # Anulowanie z przeglądarki: stop PRZED kolejnym plikiem. Powrót z rekurencji trafia
        # w pętli rodzica znowu tutaj i dostaje zapamiętaną odpowiedź — tak schodzi całość.
        if transfer_cancelled():
            return
        child = row["item"]
        if child["id"] in seen:
            continue
        seen.add(child["id"])
        _download_item(child, target_dir, log, downloaded)
        if child["itemType"] == "assembly":
            _download_children_recursive(child, target_dir, log, seen, downloaded)

class DownloadFolderDialog(QtWidgets.QDialog):
    """Jedyne natywne okno w całym przebiegu main() — pyta o folder docelowy (gdzie mają
    wylądować pobrane pliki) i pokazuje konto/Wyloguj. Wybór KTÓREGO elementu pobrać zapada
    w przeglądarce (zob. build_browser_download_url/main) — folder to jedyna rzecz, której
    przeglądarka nie może sama ustalić (wybór lokalnego miejsca zapisu wymaga natywnego
    okna systemowego)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result_folder = None

        self.setWindowTitle(t("download_folder_dialog_title"))
        self.setMinimumWidth(440)

        outer = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        outer.addLayout(form)

        account_row = QtWidgets.QHBoxLayout()
        self.account_label = QtWidgets.QLabel(t("logged_in_as", name=get_saved_username() or "?"))
        account_row.addWidget(self.account_label)
        logout_btn = QtWidgets.QPushButton(t("logout_button"))
        logout_btn.clicked.connect(self.on_logout)
        account_row.addWidget(logout_btn)
        account_row.addStretch(1)
        form.addRow(t("account_label"), account_row)

        folder_row = QtWidgets.QHBoxLayout()
        self.folder_edit = QtWidgets.QLineEdit(get_download_folder() or "")
        folder_row.addWidget(self.folder_edit)
        browse_btn = QtWidgets.QPushButton("...")
        browse_btn.setMaximumWidth(32)
        browse_btn.clicked.connect(self.on_browse)
        folder_row.addWidget(browse_btn)
        form.addRow(t("target_dir_label"), folder_row)

        self.error_label = QtWidgets.QLabel("")
        self.error_label.setStyleSheet("color: #c0392b;")
        self.error_label.setWordWrap(True)
        outer.addWidget(self.error_label)

        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.on_submit)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

    def on_logout(self):
        api_logout()
        QtWidgets.QMessageBox.information(
            self, t("pdm_title"), t("logged_out_message")
        )
        self.reject()

    def on_browse(self):
        start = self.folder_edit.text().strip() or os.path.expanduser("~")
        chosen = QtWidgets.QFileDialog.getExistingDirectory(self, t("choose_download_folder_caption"), start)
        if chosen:
            self.folder_edit.setText(chosen)

    def on_submit(self):
        self.error_label.setText("")
        folder = self.folder_edit.text().strip()
        if not folder:
            self.error_label.setText(t("indicate_target_folder"))
            return
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            self.error_label.setText(t("cannot_use_folder", error=e))
            return
        set_download_folder(folder)
        self.result_folder = folder
        self.accept()

def wait_for_ticket(ticket, timeout_seconds=600, raise_browser=False):
    """Czeka, aż element zostanie wskazany w przeglądarce — BEZ własnego okna. Odpowiednik
    (celowo zduplikowany, zob. LoginDialog wyżej) funkcji o tej samej nazwie w
    upload.py, gdzie stoi też pełne wyjaśnienie.

    W skrócie: okno „Czekam na przeglądarkę" powstawało zaraz po tym, jak przeglądarka
    dostała fokus, i Qt odbierało jej go z powrotem, przez co lista elementów lądowała ZA
    FreeCAD-em. Makra SolidWorks i Inventor nie mają tu żadnego okna — czekają, pisząc na
    pasku stanu, i tak jest teraz również tutaj.

    Zwraca dane biletu albo None, gdy upłynął czas oczekiwania."""
    import time

    status_bar = None
    try:
        import FreeCADGui as Gui

        status_bar = Gui.getMainWindow().statusBar()
        status_bar.showMessage(t("wait_ticket_status_download"))
    except Exception:
        status_bar = None

    try:
        deadline = time.time() + timeout_seconds
        polls = 0
        while time.time() < deadline:
            try:
                data = api_get(f"/create-tickets/{ticket}")
                if data and data.get("itemId"):
                    return data
            except Exception:
                # Chwilowy błąd sieci nie przerywa czekania — kolejny obieg spróbuje ponownie.
                pass

            # Przeglądarka otwarta przed chwilą przez open_in_browser: gdy już działała, nowa
            # karta mogła wylądować w tle (zob. _raise_via_kwin). Wyciągamy ją przy pierwszych
            # trzech odpytaniach — strona potrzebuje chwili, żeby załadować się i ustawić tytuł,
            # po którym okno jest rozpoznawane. Tylko trzy, żeby nie wyrywać fokusu komuś, kto
            # świadomie wrócił do FreeCAD-a.
            if raise_browser and polls < 3 and sys.platform.startswith("linux"):
                _focus_browser_window()
            polls += 1

            # Interfejs odświeżany dziesięć razy częściej niż odpytywanie serwera, żeby
            # FreeCAD nie stał zamrożony przez cały czas czekania.
            for _ in range(20):
                try:
                    QtWidgets.QApplication.processEvents()
                except Exception:
                    pass
                time.sleep(0.1)

        App.Console.PrintMessage(f"EasyPDM: {t('wait_timeout')}\n")
        return None
    finally:
        if status_bar is not None:
            try:
                status_bar.clearMessage()
            except Exception:
                pass

def _run_download(top_item, target_dir, log):
    """Faktyczne pobieranie + otwarcie, wydzielone z main() wyłącznie po to, żeby dało się
    je owinąć w jeden szeroki try/except (zob. main()) — błąd, którego nie przewidzieliśmy
    (np. nieoczekiwany kształt odpowiedzi API), ma się skończyć CZYTELNYM komunikatem
    z pełnym tracebackiem, a nie cichym zniknięciem makra bez żadnego okna na końcu
    (dokładnie to przydarzyło się w praktyce, zanim doszło to zabezpieczenie — zob. też
    poprawiony _download_children_recursive, gdzie leżała PIERWOTNA przyczyna)."""
    log(t("log_downloading_top", number=top_item["itemNumber"], name=top_item["fileName"], dir=target_dir))

    seen = {top_item["id"]}

    # Lista do panelu postępu. W odróżnieniu od wysyłki makro NIE zna jej z góry —
    # _download_children_recursive schodzi poziom po poziomie i w tym momencie nie wie, ile
    # plików będzie. Dlatego pytamy serwer o całe poddrzewo jednym zapytaniem; deduplikacja
    # po jego stronie odpowiada tej po "seen" tutaj, więc liczby się zgadzają.
    try:
        rows = api_get(f"/items/{top_item['id']}/descendants") or []
        progress_start("download",
                       [(r["id"], r.get("recordName") or r.get("fileName", "")) for r in rows])
    except Exception:
        pass

    downloaded = []
    top_path = _download_item(top_item, target_dir, log, downloaded)
    if top_item["itemType"] == "assembly":
        _download_children_recursive(top_item, target_dir, log, seen, downloaded)

    progress_finish()

    # Odnośniki muszą wskazywać na pliki leżące OBOK — wszystko pobraliśmy do jednego
    # folderu, więc ścieżka z podfolderem sprzed wysyłki rozwiązałaby się w próżnię.
    # Robione PRZED otwarciem dokumentu: po otwarciu FreeCAD ma już zepsute odnośniki
    # wczytane i samo przepisanie pliku na dysku niczego by nie naprawiło.
    _flatten_xlinks(downloaded, log)

    # Anulowane z przeglądarki: pobrane pliki zostają na dysku, ale dokumentu NIE otwieramy —
    # bez reszty komponentów złożenie otworzyłoby się z brakującymi odnośnikami.
    if _CANCEL["requested"]:
        log(t("log_cancelled_not_opened"))
        return

    if top_path and os.path.exists(top_path):
        try:
            opened = App.openDocument(top_path)
            log(t("log_opened", path=top_path))
        except Exception as e:
            opened = None
            log(t("log_open_failed", path=top_path, error=e))
        # The drawing sheet shows what EasyPDM knows now -- e.g. who approved the item after
        # it was released, which the file sent before release cannot carry. Only pages that
        # already use the EasyPDM sheet; nothing is added or asked here, and the file on disk
        # is left as downloaded (the document is just marked modified when the sheet changed).
        if opened is not None:
            try:
                if refresh_sheets(opened, top_item["id"]):
                    log(t("log_sheet_refreshed"))
            except Exception as e:
                App.Console.PrintMessage("EasyPDM: could not refresh the drawing sheet: %s\n" % e)
    else:
        log(t("log_no_main_file"))

def main():
    if not ensure_logged_in():
        return

    # Jedyne natywne okno w całym przebiegu — folder docelowy + konto. KTÓRY element
    # pobrać wybiera się w przeglądarce (zob. build_browser_download_url), nie tutaj.
    folder_dialog = DownloadFolderDialog()
    if folder_dialog.exec() != QtWidgets.QDialog.Accepted:
        return
    target_dir = folder_dialog.result_folder

    ticket = str(uuid.uuid4())
    try:
        url = build_browser_download_url(ticket)
        open_in_browser(url)
    except Exception as e:
        QtWidgets.QMessageBox.critical(None, t("pdm_title"), t("open_browser_failed", error=e))
        return

    ticket_data = wait_for_ticket(ticket, raise_browser=True)
    if ticket_data is None:
        # Upłynął czas oczekiwania — nic do pobrania.
        return

    try:
        top_item = api_get(f"/items/{ticket_data['itemId']}")
    except Exception as e:
        _show_on_top(QtWidgets.QMessageBox.Critical, t("pdm_title"), t("fetch_selected_item_failed", error=e))
        return
    if top_item is None:
        _show_on_top(QtWidgets.QMessageBox.Critical, t("pdm_title"), t("item_no_longer_exists"))
        return

    log_lines = []

    def log(msg):
        log_lines.append(msg)
        App.Console.PrintMessage(msg + "\n")

    try:
        _run_download(top_item, target_dir, log)
    except Exception:
        import traceback

        tb = traceback.format_exc()
        App.Console.PrintError(tb + "\n")
        _show_on_top(
            QtWidgets.QMessageBox.Critical,
            t("easypdm_error_title"),
            t("download_interrupted")
            + tb
            + t("log_so_far")
            + "\n".join(log_lines[-15:]),
        )
        return

    # Po „Anuluj" w przeglądarce bez okna na koniec — raport z biegu jest już w powiadomieniach,
    # tam, gdzie kliknięto. Zapis przebiegu został w Report View.
    if _CANCEL["requested"]:
        return
    _show_on_top(QtWidgets.QMessageBox.Information, t("easypdm_title"), "\n".join(log_lines[-25:]))
