#!/usr/bin/env python3
"""Keeps the add-on's Qt translations in step with its code.

    python3 tools/update_translations.py [--check] [--add LANGUAGE]

collects every translatable text -- literal _tr("...") calls and N_("...") marks in the add-on's
modules, and the English messages in common.TRANSLATIONS (disambiguated by their key) -- and
writes freecad/EasyPDM/translations/EasyPDM_<language>.ts for each language already there (or
given with --add, e.g. --add fr): new texts are added unfinished, texts no longer in the code
are dropped, translations already made are kept. It then compiles each .ts into the .qm FreeCAD
loads, with Qt's lrelease (found on PATH, in /usr/lib/qt6/bin, or given as $LRELEASE); without
it the .qm files are left as they are and the script says so.

Translate a .ts with Qt Linguist or any text editor, then rerun this script and commit both
files. --check changes nothing and fails when a .ts is out of date, as CI runs it.

Why not lupdate: most texts reach Qt through a variable (common.t looks its English text up by
key), which lupdate cannot follow; reading the code's own tables is exact.
"""

import argparse
import ast
import glob
import os
import shutil
import subprocess
import sys
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "freecad", "EasyPDM")
DIRECTORY = os.path.join(PACKAGE, "translations")
CONTEXT = "EasyPDM"
# Modules whose _tr("...") / N_("...") texts are translated.
UI_MODULES = ("easypdm_addon.py", "panel.py", "preferences.py")


def _call_name(node):
    f = node.func
    return f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None


def ui_texts():
    """[(source, None)] in order of appearance."""
    out = []
    for name in UI_MODULES:
        path = os.path.join(PACKAGE, name)
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _call_name(node) in ("_tr", "N_") and node.args:
                first = node.args[0]
                # _tr("a" if x else "b") translates either text
                for c in (first.body, first.orelse) if isinstance(first, ast.IfExp) else (first,):
                    if isinstance(c, ast.Constant) and isinstance(c.value, str):
                        found.append((c.lineno, c.col_offset, c.value))
        out += [(text, None) for _, _, text in sorted(found)]
    return out


def message_texts():
    """[(English text, key)] from common.TRANSLATIONS."""
    path = os.path.join(PACKAGE, "common.py")
    with open(path, encoding="utf-8") as f:
        tree = ast.parse(f.read(), path)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == "TRANSLATIONS":
            return [(text, key) for key, text in ast.literal_eval(node.value).items()]
    raise SystemExit("common.py has no TRANSLATIONS table")


def sources():
    seen, out = set(), []
    for entry in ui_texts() + message_texts():
        if entry not in seen:
            seen.add(entry)
            out.append(entry)
    return out


def read_ts(path):
    """{(source, comment): translation} of the finished and unfinished-but-filled entries."""
    done = {}
    for message in ET.parse(path).getroot().iter("message"):
        source = message.findtext("source") or ""
        comment = message.findtext("comment")
        translation = message.find("translation")
        if translation is not None and (translation.text or ""):
            done[(source, comment)] = (translation.text, translation.get("type"))
    return done


def render_ts(language, entries, done):
    lines = ['<?xml version="1.0" encoding="utf-8"?>', "<!DOCTYPE TS>",
             '<TS version="2.1" language="%s">' % language, "<context>",
             "    <name>%s</name>" % CONTEXT]
    for source, comment in entries:
        text, kind = done.get((source, comment), ("", "unfinished"))
        lines.append("    <message>")
        lines.append("        <source>%s</source>" % escape(source))
        if comment is not None:
            lines.append("        <comment>%s</comment>" % escape(comment))
        attr = ' type="%s"' % kind if kind else ""
        lines.append("        <translation%s>%s</translation>" % (attr, escape(text)))
        lines.append("    </message>")
    lines += ["</context>", "</TS>", ""]
    return "\n".join(lines)


def lrelease():
    for candidate in (os.environ.get("LRELEASE"), shutil.which("lrelease"), shutil.which("lrelease-qt6"),
                      "/usr/lib/qt6/bin/lrelease", "/usr/lib/x86_64-linux-gnu/qt6/bin/lrelease"):
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def main():
    args = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    args.add_argument("--check", action="store_true", help="fail if a .ts is out of date; change nothing")
    args.add_argument("--add", metavar="LANGUAGE", action="append", default=[],
                      help="start a translation into LANGUAGE (FreeCAD's code: de, pl, fr, pt-BR...)")
    options = args.parse_args()

    entries = sources()
    languages = sorted({os.path.basename(p)[len(CONTEXT) + 1:-3] for p in glob.glob(os.path.join(DIRECTORY, CONTEXT + "_*.ts"))}
                       | set(options.add))
    stale, written = [], []
    for language in languages:
        path = os.path.join(DIRECTORY, "%s_%s.ts" % (CONTEXT, language))
        done = read_ts(path) if os.path.exists(path) else {}
        new = render_ts(language, entries, done)
        old = None
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                old = f.read()
        missing = sum(1 for e in entries if e not in done)
        print("%s: %d texts, %d untranslated" % (language, len(entries), missing))
        if new != old:
            stale.append(path)
            if not options.check:
                os.makedirs(DIRECTORY, exist_ok=True)
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new)
        written.append(path)
    if options.check:
        if stale:
            print("out of date (run tools/update_translations.py):", *stale, sep="\n  ")
            return 1
        return 0
    tool = lrelease()
    if tool is None:
        print("lrelease not found: the .qm files were not rebuilt (install Qt's linguist tools or set LRELEASE)")
        return 0
    for path in written:
        subprocess.run([tool, "-silent", "-nounfinished", path, "-qm", path[:-3] + ".qm"], check=True)
        print("compiled", path[:-3] + ".qm")
    return 0


if __name__ == "__main__":
    sys.exit(main())
