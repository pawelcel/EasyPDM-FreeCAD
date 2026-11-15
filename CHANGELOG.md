# Changelog

All notable changes to EasyPDM for FreeCAD are documented in this file. Until 0.9 the add-on and
the macros were released with EasyPDM itself; see the
[EasyPDM changelog](https://github.com/pawelcel/EasyPDM/blob/main/CHANGELOG.md) for that history.

## [Unreleased]

### Added
- **Document panel.** EasyPDM → Document panel opens a dock beside the model tree showing the active document's item — record name, name, revision, status and who holds the lock — with buttons for Refresh, Open in browser (the item's project), Lock, Release, Upload and Refresh drawing sheet. It follows the active document and asks the server only while it is open.
- **Lock for editing and Release lock** for the active document's item, the same lock as in the browser; a refusal from the server (for example on a released item) is shown in words.
- **Refresh drawing sheet** fills the EasyPDM sheet with the item's current data without uploading the document.
- **Edit → Preferences → EasyPDM**: server address, download folder, the menu in every workbench, where the login is kept, and Log out.
- **The EasyPDM menu shows who is signed in, and to which server,** at its top.
- **An icon for each command** on the toolbar and in the menus.

### Security
- **The login token is kept in the system's secret storage.** DPAPI on Windows, the keychain on macOS and the Secret Service (KWallet, GNOME Keyring…) through `secret-tool` on Linux, per server, instead of FreeCAD's plain-text preferences. Without one it stays in the preferences, and the Report view says so once. A token left there by an earlier version is moved on first use, so nobody has to log in again. The macros the add-on runs use the same storage.

### Changed
- **This repository is now the home of EasyPDM for FreeCAD.** The add-on and the macros it runs moved here from `EasyPDM.FreeCad/` in the EasyPDM repository, with their history, and this repository stopped being a generated copy: issues and changes belong here, and the add-on is released from here. It is laid out as FreeCAD's Addon Manager installs it (package.xml at the top, the code in `freecad/EasyPDM/`), so nothing has to be built.
- **The macros are no longer offered on their own.** They stay as the add-on's engine, in `freecad/EasyPDM/`, run unchanged by its Upload and Download; install the add-on instead of the macro files.
