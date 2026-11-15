# Where the add-on keeps its EasyPDM login token: the system's own secret storage when there is
# one, so the token does not sit in FreeCAD's plain-text user.cfg.
#
#   Windows  DPAPI (CryptProtectData through ctypes): encrypted with the user's Windows login,
#            the ciphertext kept in FreeCAD's parameters -- readable only by that user.
#   macOS    the login keychain, through the `security` command.
#   Linux    the Secret Service (KWallet, GNOME Keyring, KeePassXC...) through `secret-tool`
#            from libsecret, when it is installed.
#   else     FreeCAD's parameters, as before, and the add-on says so once.
#
# FreeCAD's Addon Index allows no `keyring` package, so each backend uses what the system ships.
# The token is an EasyPDM macro token -- revocable under Settings > Users, never the password --
# kept per server address. A token left in the parameters by an earlier version is moved into
# the secret storage the first time it is read, so nobody has to log in again.

import base64
import ctypes
import os
import shutil
import subprocess
import sys

import FreeCAD as App

PARAM_GROUP = "User parameter:BaseApp/EasyPDM"
SERVICE = "EasyPDM"
_TIMEOUT = 15

_cache = {}          # server -> token (None for "known to be absent"), for this FreeCAD session
_warned = False


def _params():
    return App.ParamGet(PARAM_GROUP)


# --- Windows: DPAPI -----------------------------------------------------------------------------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_char))]


def _dpapi(data, protect):
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in = _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    # No UI, no extra entropy: bound to the current Windows user.
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):
        raise OSError("DPAPI failed (%d)" % kernel32.GetLastError())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)


def _param_key(server):
    # Parameter names allow letters, digits and a few signs only.
    return "ProtectedToken_" + base64.urlsafe_b64encode(server.encode("utf-8")).decode("ascii").rstrip("=")


class _Windows:
    name = "Windows (DPAPI)"

    def get(self, server):
        raw = _params().GetString(_param_key(server), "")
        if not raw:
            return None
        return _dpapi(base64.b64decode(raw), protect=False).decode("utf-8")

    def set(self, server, token):
        _params().SetString(_param_key(server), base64.b64encode(_dpapi(token.encode("utf-8"), protect=True)).decode("ascii"))

    def clear(self, server):
        _params().RemString(_param_key(server))


# --- macOS: keychain ----------------------------------------------------------------------------

class _MacKeychain:
    name = "macOS keychain"

    def get(self, server):
        r = subprocess.run(["security", "find-generic-password", "-s", SERVICE, "-a", server, "-w"],
                           capture_output=True, text=True, timeout=_TIMEOUT)
        return r.stdout.strip() or None if r.returncode == 0 else None

    def set(self, server, token):
        # -w with the value on the command line is how `security` takes it; the process is
        # the user's own and lives a few milliseconds.
        subprocess.run(["security", "add-generic-password", "-U", "-s", SERVICE, "-a", server, "-w", token],
                       check=True, capture_output=True, timeout=_TIMEOUT)

    def clear(self, server):
        subprocess.run(["security", "delete-generic-password", "-s", SERVICE, "-a", server],
                       capture_output=True, timeout=_TIMEOUT)


# --- Linux: Secret Service through secret-tool --------------------------------------------------

class _SecretTool:
    name = "Secret Service (secret-tool)"

    def get(self, server):
        r = subprocess.run(["secret-tool", "lookup", "service", SERVICE, "server", server],
                           capture_output=True, text=True, timeout=_TIMEOUT)
        return r.stdout.strip() or None if r.returncode == 0 else None

    def set(self, server, token):
        # The secret goes through stdin, never the command line.
        subprocess.run(["secret-tool", "store", "--label", "EasyPDM (%s)" % server,
                        "service", SERVICE, "server", server],
                       input=token, text=True, check=True, capture_output=True, timeout=_TIMEOUT)

    def clear(self, server):
        subprocess.run(["secret-tool", "clear", "service", SERVICE, "server", server],
                       capture_output=True, timeout=_TIMEOUT)


def _backend():
    if os.environ.get("EASYPDM_TOKEN_STORE") == "params":
        return None
    if sys.platform == "win32":
        return _Windows()
    if sys.platform == "darwin" and shutil.which("security"):
        return _MacKeychain()
    if shutil.which("secret-tool"):
        return _SecretTool()
    return None


def backend_name():
    b = _backend()
    return b.name if b else "FreeCAD's parameters"


def _warn_plain():
    global _warned
    if not _warned:
        _warned = True
        App.Console.PrintWarning(
            "EasyPDM: no system secret storage found (secret-tool on Linux); the login token is kept "
            "in FreeCAD's parameters. It is a revocable EasyPDM token, not your password.\n")


def get(server):
    """The token for `server`, or None."""
    if server in _cache:
        return _cache[server]
    token = None
    backend = _backend()
    legacy = _params().GetString("SessionToken", "") or None
    if backend is None:
        token = legacy
        if token:
            _warn_plain()
    else:
        try:
            token = backend.get(server)
            if token is None and legacy:
                # Left by an earlier version in plain text: move it, then forget the copy.
                backend.set(server, legacy)
                _params().SetString("SessionToken", "")
                token = legacy
        except Exception as e:
            App.Console.PrintWarning("EasyPDM: could not read the login from %s: %s\n" % (backend.name, e))
            token = legacy
    _cache[server] = token
    return token


def set(server, token):
    """Keeps `token` for `server`; None or "" forgets it."""
    _cache.pop(server, None)
    backend = _backend()
    if not token:
        if backend is not None:
            try:
                backend.clear(server)
            except Exception:
                pass
        _params().SetString("SessionToken", "")
        _cache[server] = None
        return
    if backend is not None:
        try:
            backend.set(server, token)
            _params().SetString("SessionToken", "")
            _cache[server] = token
            return
        except Exception as e:
            App.Console.PrintWarning("EasyPDM: could not store the login in %s (%s); "
                                     "keeping it in FreeCAD's parameters.\n" % (backend.name, e))
    _warn_plain()
    _params().SetString("SessionToken", token)
    _cache[server] = token
