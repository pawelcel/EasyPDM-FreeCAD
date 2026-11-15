# Changelog

All notable changes to EasyPDM for FreeCAD are documented in this file. Until 0.9 the add-on and
the macros were released with EasyPDM itself; see the
[EasyPDM changelog](https://github.com/pawelcel/EasyPDM/blob/main/CHANGELOG.md) for that history.

## [Unreleased]

### Changed
- **This repository is now the home of EasyPDM for FreeCAD.** The add-on and the macros it runs moved here from `EasyPDM.FreeCad/` in the EasyPDM repository, with their history, and this repository stopped being a generated copy: issues and changes belong here, and the add-on is released from here. It is laid out as FreeCAD's Addon Manager installs it (package.xml at the top, the code in `freecad/EasyPDM/`), so nothing has to be built.
- **The macros are no longer offered on their own.** They stay as the add-on's engine, in `freecad/EasyPDM/`, run unchanged by its Upload and Download; install the add-on instead of the macro files.
