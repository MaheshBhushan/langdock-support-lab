from datetime import datetime, timedelta
import hashlib
import json
import os
import re
import tempfile
from .safety import sensitive, strict_json

IDS = {"RB-AUTH": "auth", "RB-PERMISSION": "permission", "RB-THROTTLE": "throttle", "RB-TIMEOUT": "timeout", "RB-SUCCESS": "success"}
HEADINGS = ["Symptoms", "What the evidence proves", "L1 checks", "L2 escalation", "Verification", "Limits"]
CHECKS = ("source_checked", "steps_exercised", "secret_safe", "limits_stated")


def document(root, book_id, secrets=()):
    if book_id not in IDS:
        raise ValueError("UNKNOWN_ID")
    path = root / "runbooks" / (book_id + ".md")
    if path.is_symlink():
        raise ValueError("INVALID_DOCUMENT")
    data = path.read_bytes()
    if len(data) > 65536:
        raise ValueError("INVALID_DOCUMENT")
    text = data.decode("utf-8")
    match = re.search(r"```json\n(.*?)\n```", text, re.S)
    if not match:
        raise ValueError("INVALID_METADATA")
    meta = strict_json(match[1])
    if set(meta) != {"schema_version", "id", "title", "category", "aliases", "scope"} or type(meta["schema_version"]) is not int or meta["schema_version"] != 1 or meta["id"] != book_id or meta["category"] != IDS[book_id] or meta["scope"] != "synthetic-lab" or not isinstance(meta["title"], str) or not meta["title"] or not isinstance(meta["aliases"], list) or not meta["aliases"] or any(not isinstance(a, str) or not re.fullmatch("[a-z0-9]+", a) for a in meta["aliases"]):
        raise ValueError("INVALID_METADATA")
    body = text[match.end():].strip()
    if re.findall(r"^## (.+)$", body, re.M) != HEADINGS or re.search(r"<[^>]*>|!\[|```|\{\{|^\s{2,}[-*] |^\s*[#!].*(?:include|exec)", body, re.M) or sensitive(text, secrets):
        raise ValueError("INVALID_DOCUMENT")
    sections = {}
    for index, heading in enumerate(HEADINGS):
        part = body.split("## " + heading + "\n", 1)[1]
        if index < len(HEADINGS) - 1:
            part = part.split("## " + HEADINGS[index + 1] + "\n", 1)[0]
        part = part.strip()
        if not part or len(part) > 1500:
            raise ValueError("INVALID_DOCUMENT")
        sections[heading] = part
    return {**meta, "sha256": hashlib.sha256(data).hexdigest(), "content": text, "sections": sections}


def snapshot(root, now, secrets=()):
    eligible, diagnostics = {}, {}
    try:
        manifest_path = root / "runbooks/reviews.json"
        if manifest_path.is_symlink():
            raise ValueError()
        manifest = strict_json(manifest_path.read_text())
        if set(manifest) != {"schema_version", "entries"} or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1 or not isinstance(manifest["entries"], dict):
            raise ValueError()
    except (OSError, ValueError, KeyError, TypeError):
        return {}, {book_id: "INVALID_MANIFEST" for book_id in IDS}
    duplicates = set()
    for path in (root / "runbooks").glob("*.md"):
        if path.stem in IDS or path.is_symlink():
            continue
        try:
            if path.stat().st_size > 65536:
                continue
            match = re.search(r"```json\n(.*?)\n```", path.read_text(), re.S)
            meta = strict_json(match[1]) if match else {}
            if isinstance(meta, dict) and meta.get("id") in IDS:
                duplicates.add(meta["id"])
        except (OSError, ValueError, UnicodeError, TypeError):
            continue
    for book_id in IDS:
        try:
            if book_id in duplicates:
                raise ValueError("DUPLICATE_ID")
            book = document(root, book_id, secrets)
            entry = manifest["entries"][book_id]
            if entry.get("status") != "reviewed":
                diagnostics[book_id] = "DRAFT"
                continue
            if set(entry) != {"status", "review_kind", "reviewer", "reviewed_at", "review_due_at", "sha256", "checks"} or entry["review_kind"] != "synthetic-lab-review" or not isinstance(entry["reviewer"], str) or not entry["reviewer"].strip() or set(entry["checks"]) != set(CHECKS) or any(entry["checks"][k] is not True for k in CHECKS):
                raise ValueError("INVALID_REVIEW")
            reviewed = datetime.fromisoformat(entry["reviewed_at"])
            due = datetime.fromisoformat(entry["review_due_at"])
            if reviewed.tzinfo is None or due.tzinfo is None or not reviewed <= now < due:
                raise ValueError("REVIEW_TIME")
            if entry["sha256"] != book["sha256"]:
                raise ValueError("HASH_MISMATCH")
            # Reviewer identity stays in the local manifest; public API needs only provenance and times.
            book["review"] = {k: entry[k] for k in ("review_kind", "reviewed_at", "review_due_at")}
            eligible[book_id] = book
        except (OSError, ValueError, KeyError, TypeError, UnicodeError):
            diagnostics[book_id] = "INELIGIBLE"
    return eligible, diagnostics


def review(root, book_id, reviewer, days, now, secrets=()):
    book = document(root, book_id, secrets)
    if not reviewer.strip() or sensitive(reviewer, secrets) or not 1 <= days <= 365:
        raise ValueError("INVALID_REVIEW")
    target = root / "runbooks/reviews.json"
    if target.is_symlink():
        raise ValueError("INVALID_MANIFEST")
    data = strict_json(target.read_text())
    data["entries"][book_id] = {"status": "reviewed", "review_kind": "synthetic-lab-review", "reviewer": reviewer,
                               "reviewed_at": now.isoformat(timespec="milliseconds"), "review_due_at": (now + timedelta(days=days)).isoformat(timespec="milliseconds"),
                               "sha256": book["sha256"], "checks": dict.fromkeys(CHECKS, True)}
    fd, name = tempfile.mkstemp(dir=target.parent, prefix=".review-")
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(data, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return {"id": book_id, "status": "reviewed", "review_kind": "synthetic-lab-review"}


def citation(book, section):
    heading = {"evidence": "What the evidence proves", "l1": "L1 checks", "l2": "L2 escalation"}[section]
    return {"id": f'{book["id"]}:1:{section}', "runbook_id": book["id"], "title": book["title"], "section": section,
            "sha256": book["sha256"], **book["review"], "excerpt": book["sections"][heading]}
