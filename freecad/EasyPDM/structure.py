# Are the components an assembly is built from the newest files in EasyPDM?
#
# While an assembly is being worked on, someone else may upload a newer file of one of its
# components -- a new revision, or the same revision overwritten. The document panel shows the
# state of every component (and of the document itself), and Upload refuses to send an assembly
# built on an older file than the one in EasyPDM: the newer one has to be downloaded first.
#
# Which file a local copy is, the server tells (POST /api/items/cad-versions, EasyPDM 0.9):
#   - by the version stamp Upload writes into the document's Meta before saving and sending it
#     (stamp() below). It travels with the file through Download and stays the same when
#     FreeCAD saves the file again unchanged -- which it does to components whenever the
#     assembly is saved, so a hash alone would call every one of them changed;
#   - for files without a stamp (uploaded before 0.9, or by another CAD program), by the
#     SHA-256 of the file on disk.
# The revision letter in the document's label ("71(Bracket).B") settles what neither can: a
# copy of an older revision is outdated even when the server has never seen its exact bytes.

import hashlib
import os
import re
import uuid

META_KEY = "EasyPDM_ContentVersion"

# States of one document, most serious first.
OUTDATED = "outdated"      # an older file than the current one in EasyPDM
UNKNOWN = "unknown"        # a file EasyPDM has not seen: changed here, or never uploaded
NOT_IN_PDM = "not_in_pdm"  # not an EasyPDM item yet (it is created on upload)
NO_FILE = "no_file"        # an item without a CAD file in EasyPDM
CURRENT = "current"

_REVISION_SUFFIX = re.compile(r"\.([A-Za-z]+)$")


class ServerTooOld(Exception):
    """The server has no POST /api/items/cad-versions (older than 0.9)."""


def content_version(doc):
    try:
        return (doc.Meta or {}).get(META_KEY) or None
    except Exception:
        return None


def stamp(doc):
    """Writes a new version stamp into `doc` (saved with the document) and returns it."""
    version = str(uuid.uuid4())
    meta = dict(doc.Meta or {})
    meta[META_KEY] = version
    doc.Meta = meta
    return version


def file_hash(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def when(iso):
    """An ISO time from the server as local "YYYY-MM-DD HH:MM", or "?"."""
    if not iso:
        return "?"
    try:
        from datetime import datetime

        stamp_ = datetime.fromisoformat(re.sub(r"\.(\d{6})\d+", r".\1", iso.replace("Z", "+00:00")))
        return stamp_.astimezone().strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


def _revision_number(letters):
    """A -> 1, Z -> 26, AA -> 27 (the inverse of common.revision_label)."""
    n = 0
    for ch in letters.upper():
        n = n * 26 + (ord(ch) - ord("A") + 1)
    return n


def local_revision(doc):
    m = _REVISION_SUFFIX.search(doc.Label or "")
    return m.group(1).upper() if m else None


class Row:
    """One document of the tree as the panel and Upload show it."""

    def __init__(self, doc, depth, quantity=1):
        self.doc = doc
        self.depth = depth
        self.quantity = quantity
        self.item = None
        self.server = None
        self.state = NOT_IN_PDM

    @property
    def label(self):
        return self.doc.Label

    @property
    def locked_by(self):
        s = self.server or {}
        return s.get("ownerDisplayName") if s.get("ownerLocked") else None


def _classify(doc, server):
    if not server or not server.get("found"):
        return NOT_IN_PDM
    local = server.get("local")
    if local == "none":
        return NO_FILE
    if local == "older":
        return OUTDATED
    current = server.get("current") or {}
    mine = local_revision(doc)
    if mine and current.get("revisionNumber") and _revision_number(mine) < current["revisionNumber"]:
        return OUTDATED
    return CURRENT if local == "current" else UNKNOWN


def check(top_doc, api_get, api_post_json, discover_component_tree, match_existing_item):
    """The rows of `top_doc` and every component it links to (depth-first, as in its tree),
    each with its state. The helpers come from common/upload, so this module stays free of
    imports that would tie it to one of them. Raises ServerTooOld on servers before 0.9."""
    order, docs, edges = discover_component_tree(top_doc)
    docs = dict(docs)
    docs[top_doc.FileName] = top_doc
    children = {}
    for parent, child, qty in edges:
        children.setdefault(parent, []).append((child, qty))

    rows = []

    def walk(path, depth, qty, seen):
        rows.append(Row(docs[path], depth, qty))
        if path in seen:
            return
        for child, child_qty in children.get(path, []):
            walk(child, depth + 1, child_qty, seen | {path})

    walk(top_doc.FileName, 0, 1, frozenset())

    try:
        existing = api_get("/items") or []
    except Exception:
        existing = []
    unique = {}
    for row in rows:
        unique.setdefault(row.doc.FileName, row.doc)
    items = {path: match_existing_item(doc, existing) for path, doc in unique.items()}

    request = []
    for path, item in items.items():
        if item:
            doc = unique[path]
            version = content_version(doc)
            entry = {"itemId": item["id"], "contentVersion": version}
            if not version and doc.FileName and os.path.exists(doc.FileName):
                entry["fileHash"] = file_hash(doc.FileName)
            request.append(entry)
    answers = {}
    if request:
        try:
            for answer in api_post_json("/items/cad-versions", {"components": request}) or []:
                answers[answer["itemId"]] = answer
        except Exception as e:
            if any(code in str(e) for code in ("404", "405", "Not Found", "Method Not Allowed")):
                raise ServerTooOld() from e
            raise

    for row in rows:
        row.item = items.get(row.doc.FileName)
        row.server = answers.get(row.item["id"]) if row.item else None
        row.state = _classify(row.doc, row.server) if row.item else NOT_IN_PDM
    return rows


def outdated(rows):
    """The rows Upload refuses to send over, each document once."""
    seen, out = set(), []
    for row in rows:
        if row.state == OUTDATED and row.doc.FileName not in seen:
            seen.add(row.doc.FileName)
            out.append(row)
    return out
