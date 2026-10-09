import re

MAX_CHARS = 1800


def split_eligibility(text: str) -> tuple[str, str]:
    m = re.search(r"exclusion criteria\s*:?", text, re.I)
    if m:
        return text[: m.start()].strip(), text[m.end():].strip()
    return text.strip(), ""


def window(text: str, size: int = MAX_CHARS) -> list[str]:
    out, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > size:
            out.append(cur.strip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        out.append(cur.strip())
    return out


def chunk_trial(t: dict) -> list[dict]:
    head = f"Trial: {t['title']}\nConditions: {', '.join(t['conditions'])}\n"
    chunks = [{
        "id": f"{t['nct_id']}::overview::0", "nct_id": t["nct_id"], "type": "overview",
        "text": head + f"Phase: {', '.join(t['phases']) or 'N/A'}\n"
                       f"Interventions: {', '.join(t['interventions'][:8])}\nSummary: {t['brief_summary'][:1500]}",
    }]
    inc, exc = split_eligibility(t["eligibility_text"])
    for kind, body in (("inclusion", inc), ("exclusion", exc)):
        for i, piece in enumerate(window(body) if body else []):
            chunks.append({"id": f"{t['nct_id']}::{kind}::{i}", "nct_id": t["nct_id"], "type": kind,
                           "text": head + f"{kind.upper()} CRITERIA:\n{piece}"})
    for i, pub in enumerate(t.get("publications", [])):
        chunks.append({"id": f"{t['nct_id']}::publication::{i}", "nct_id": t["nct_id"], "type": "publication",
                       "text": head + f"Publication ({pub['pmcid']}): {pub['title']}\n{pub['abstract'][:1500]}"})
    return chunks