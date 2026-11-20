# Working on EasyPDM for FreeCAD

Conventions that are easy to miss. The EasyPDM server, web app and the Inventor macros live in
[pawelcel/EasyPDM](https://github.com/pawelcel/EasyPDM), the SolidWorks add-in and macros in
[pawelcel/EasyPDM-SolidWorks-Addon](https://github.com/pawelcel/EasyPDM-SolidWorks-Addon); each has its own CLAUDE.md.

## Layout

FreeCAD's namespaced add-on layout, installed as it is by the Addon Manager — nothing is built:
`package.xml`, `LICENSE` and `README.md` at the top, the code in `freecad/EasyPDM/`
(`init_gui.py`, imported by FreeCAD itself; `easypdm_addon.py`, the workbench and commands;
`upload.py` / `download.py`, the upload and download the commands run, reloaded before each run
so per-run state starts fresh; `common.py`, what both use: settings, HTTP, login, translations;
`sheet.py`, the drawing sheet, generated). They were the EasyPDMUpload/EasyPDMDownload macros
until 0.9, which is why their comments still say "makro". Never manipulate `sys.path`; FreeCAD's
Addon Index forbids it.

The login token lives in `secure_store.py` (system secret storage, plain parameters only as a
fallback). Upload and download read and write it only through `common.get_session_token`/
`set_session_token`. Test the
Linux backend with a stand-in `secret-tool` on `PATH`, not the user's real wallet (it can pop up
an unlock window).

## Drawing sheets are generated

`tools/build_templates.py` is the single source of the EasyPDM drawing sheet. It writes the SVG
templates in `freecad/EasyPDM/templates/`, writes the shared block between the BEGIN/END SHARED
markers out as `freecad/EasyPDM/sheet.py` and, with `--solidworks PATH`, writes
`EasyPDMSheetFormat.bas` in a checkout of pawelcel/EasyPDM-SolidWorks-Addon. Edit the script, never its
outputs. After a layout change, run it with `--solidworks`, commit the `.bas` there too, and
rebuild the SolidWorks sheet formats in that repository's `templates/` on a live SolidWorks.
CI fails when the committed templates or `sheet.py` differ from what the script writes.

## Translations

Texts are translated through Qt (`i18n.py`): the English text in the code is the source, and
`freecad/EasyPDM/translations/EasyPDM_<lang>.ts` / `.qm` hold the translations, loaded by FreeCAD
for its own language. After adding or changing a text (`_tr("...")`, `N_("...")`, or an entry
in `common.TRANSLATIONS`), run `python3 tools/update_translations.py`, translate what it marks
unfinished, run it again so it compiles the `.qm` (needs Qt's `lrelease`, on the host at
`/usr/lib/qt6/bin/lrelease`), and commit both files. CI fails when a `.ts` misses a text. A
translation must keep every `{placeholder}` of its source.

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
