# EasyPDM for FreeCAD

An **EasyPDM workbench** for FreeCAD: **Upload** the active document to an
[EasyPDM](https://github.com/pawelcel/EasyPDM) server, **Download** an item with its whole
assembly, **Log in** (approved in the browser, so FreeCAD never sees your password) and
**Log out**, from its menu and toolbar. The same menu can be shown in every workbench: tick
**EasyPDM menu in every workbench** in the EasyPDM menu (off by default). EasyPDM is a free, self-hosted PDM for small engineering firms: numbering,
revisions, statuses, BOM and drawing title blocks filled in from the PDM.

This is the home of EasyPDM's FreeCAD integration: report problems and send changes here. The
EasyPDM server, web app and the other CAD integrations live in
[pawelcel/EasyPDM](https://github.com/pawelcel/EasyPDM). **Log in through the browser** needs an
EasyPDM server from 0.9; everything else works with 0.8.

## Installing

1. FreeCAD → **Edit → Preferences → Addon Manager** → **Custom repositories**: add
   `https://github.com/pawelcel/EasyPDM-FreeCAD` with branch `main`.
2. **Tools → Addon manager**: install **EasyPDM** from the list and restart FreeCAD.

Updates arrive the same way.

Or unpack `EasyPDM_FreeCad_Addon_vX.zip` from a [release](https://github.com/pawelcel/EasyPDM-FreeCAD/releases) into FreeCAD's `Mod` folder (it holds an `EasyPDM` folder) (Linux usually
`~/.local/share/FreeCAD/v1-1/Mod`, Windows `%APPDATA%\FreeCAD\v1-1\Mod`).

## What works

- **Upload** of parts, assemblies (FreeCAD's native Assembly workbench, with their components as
  BOM positions) and TechDraw drawings: the item is created or picked in the browser, the file is
  renamed to the EasyPDM record name, STEP, PDF and a preview go along, mass and material are
  stored, and the EasyPDM drawing sheet is filled in.
- **Download** of an item with its whole component tree into one folder, opened in FreeCAD.
- **Log in** through the browser (EasyPDM servers from 0.9; "Log in with password…" for older
  ones) and **Log out**.
- **Document panel** (EasyPDM → Document panel): beside the model tree, the active document's
  item — record name, name, revision, status, who holds the lock — with buttons for the commands
  below and "Open in browser" (opens the item in EasyPDM; with a server older than 0.9, the
  whole-database view).
- **Lock for editing / Release lock** on the active document's item, as the lock in the browser.
- **Refresh drawing sheet**: fills the EasyPDM sheet with the item's current data without
  uploading.
- **Who is signed in, and to which server**, at the top of the EasyPDM menu.
- **Edit → Preferences → EasyPDM**: server address, download folder, the menu in every
  workbench, where the login is kept, and Log out.
- Menu texts in English, Polish and German, following FreeCAD's language.

Upload and Download are the EasyPDM FreeCAD macros, live-tested on FreeCAD 1.1; the add-on runs
them unchanged.

Not supported: other assembly workbenches (A2plus, Assembly3, Assembly4), and downloading an
older revision (Download always fetches the current one).

## What it connects to

Only the EasyPDM server whose address you enter when logging in, over HTTP(S). Nothing is sent
anywhere else, and nothing is contacted until you use a command.

The login is a revocable EasyPDM token (never your password), kept per server in the system's
secret storage: DPAPI on Windows, the keychain on macOS, the Secret Service (KWallet, GNOME
Keyring…) through `secret-tool` on Linux. Without one — on Linux when `secret-tool` (package
`libsecret`) is missing — it stays in FreeCAD's preferences and the Report view says so. A token
an earlier version left in FreeCAD's preferences is moved into the secret storage on first use.
The server address and your name are kept in FreeCAD's preferences
(`User parameter:BaseApp/EasyPDM`).

## Documentation

- [CAD Integrations](https://github.com/pawelcel/EasyPDM/wiki/CAD-Integrations) on the EasyPDM wiki
- [How Upload and Download work](docs/README.md) ([polski](docs/README.pl.md),
  [Deutsch](docs/README.de.md)): assemblies, drawings, drawing sheets, limitations

FreeCAD 1.0 or newer. MIT licence.

## Developing

- The add-on is FreeCAD's namespaced layout: everything in `freecad/EasyPDM/`, imported by
  FreeCAD as `freecad.EasyPDM.init_gui`. To try a change, link or copy this repository into
  FreeCAD's `Mod` folder as `EasyPDM`.
- The drawing sheets come from `tools/build_templates.py` (see its docstring); never edit the
  SVG templates or the shared block in the macros by hand.
- A release is a `vX.Y.Z` tag matching `<version>` in `package.xml`; the workflow makes a draft
  GitHub release with the zip. See [CLAUDE.md](CLAUDE.md) for the conventions.

