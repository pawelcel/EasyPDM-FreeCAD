# Working on EasyPDM for FreeCAD

Conventions that are easy to miss. The EasyPDM server, web app and the other CAD integrations
live in [pawelcel/EasyPDM](https://github.com/pawelcel/EasyPDM), which has its own CLAUDE.md.

## Layout

FreeCAD's namespaced add-on layout, installed as it is by the Addon Manager — nothing is built:
`package.xml`, `LICENSE` and `README.md` at the top, the code in `freecad/EasyPDM/`
(`init_gui.py`, imported by FreeCAD itself; `easypdm_addon.py`, the workbench and commands;
`EasyPDMUpload.FCMacro` / `EasyPDMDownload.FCMacro`, the upload and download engine the commands
load and run unchanged). Never manipulate `sys.path`; FreeCAD's Addon Index forbids it.

## Drawing sheets are generated

`tools/build_templates.py` is the single source of the EasyPDM drawing sheet. It writes the SVG
templates in `freecad/EasyPDM/templates/`, copies the shared block between the BEGIN/END SHARED
markers into both macros and, with `--solidworks PATH`, writes
`EasyPDM.SolidWorks/EasyPDMSheetFormat.bas` in a checkout of pawelcel/EasyPDM. Edit the script,
never its outputs. After a layout change, run it with `--solidworks`, commit the `.bas` there too,
and rebuild the SolidWorks sheet formats in `EasyPDM.SolidWorks/templates/` on a live SolidWorks.
CI fails when the committed templates or shared blocks differ from what the script writes.

## Testing

There is no automated test of FreeCAD behaviour. Check a change in FreeCAD itself (offscreen is
enough for most: `QT_QPA_PLATFORM=offscreen FreeCAD script.py`, but switching workbenches and
`QApplication.processEvents()` after menu changes hang there). Never open windows on the
user's desktop while testing.

## Commits, changelog, releases

- Commit messages in English, explaining why the change is right.
- CHANGELOG entries on one line each: the release workflow cuts the section into the GitHub
  release, which renders single newlines as line breaks.
- A release is a `vX.Y.Z` tag equal to `<version>` in `package.xml` (the workflow refuses
  otherwise); it opens a draft GitHub release with `EasyPDM_FreeCad_Addon_vX.Y.Z.zip`. Publishing
  stays manual. Bump `<version>` and `<date>` with each release.
- The add-on talks to the EasyPDM server's API; a change that needs a newer server says so in
  the README and the changelog.
