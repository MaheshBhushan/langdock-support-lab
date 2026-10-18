import re
import unicodedata
from .runbooks import citation

STOP = set("a an and are as at be by can did do for from how i in is it of on or the this to was what why with".split())


def tokens(text):
    return {t for t in re.findall("[a-z0-9]+", unicodedata.normalize("NFKC", text).casefold()) if len(t) >= 2 and t not in STOP}


def answer(question, books, category=None):
    query = tokens(question)
    candidates = []
    for book in books.values():
        aliases = query & set(book["aliases"])
        context = book["category"] == category
        score = 4 * len(aliases) + 2 * len(query & tokens(book["title"])) + len(query & tokens(" ".join(book["sections"].values()))) + 3 * context
        if score >= 4 and (aliases or context):
            candidates.append((score, book))
    candidates.sort(key=lambda c: (-c[0], c[1]["id"]))
    reason = "NO_ELIGIBLE_RUNBOOKS" if not books else "NO_MATCH" if not candidates else None
    if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 2 and candidates[0][1]["category"] != candidates[1][1]["category"]:
        reason = "AMBIGUOUS"
    if reason:
        return {"status": "abstained", "reason": reason, "parts": [], "citations": [], "provenance": "reviewed-local-runbooks", "message": "No sufficiently specific reviewed guidance is available. Collect a run and request L2 review."}
    citations = [citation(candidates[0][1], section) for section in ("evidence", "l1")]
    return {"status": "answered", "reason": None, "parts": [{"text": c["excerpt"], "citation_id": c["id"]} for c in citations], "citations": citations, "provenance": "reviewed-local-runbooks", "message": None}
