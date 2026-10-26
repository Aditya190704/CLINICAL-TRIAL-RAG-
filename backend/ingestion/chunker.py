import re # to search for the exclusion criteria heading

MAX_CHARS = 1800 # Sets the target maximum size of each text window to approximately 1,800 characters.


def split_eligibility(text: str) -> tuple[str, str]: # it assumes everything before the first matching exclusion heading is inclusion text and evrything after it is exclusion text
    m = re.search(r"exclusion criteria\s*:?", text, re.I) # Searches for the phrase "exclusion criteria", optionally followed by a colon.
    if m: # Checks whether the exclusion criteria heading was found.
        return text[: m.start()].strip(), text[m.end():].strip() # Returns the text before the heading as inclusion text, Returns the text after the heading as exclusion text, strip() removes unnecessary whitespace from both ends.
    return text.strip(), ""


def window(text: str, size: int = MAX_CHARS) -> list[str]: # this function takes a long string and divides it into smaller text windows
    out, cur = [], "" # Creates an empty list for completed chunks and an empty string for the current chunk.
    for line in text.split("\n"): # Splits the text at newline characters and processes one line at a time.
        if cur and len(cur) + len(line) + 1 > size:  # Checks whether adding this line would make the current chunk exceed the target size.
            out.append(cur.strip()) # Saves the completed chunk after removing surrounding whitespace.
            cur = "" # Resets the current chunk so a new chunk can begin
        cur += line + "\n"  # Adds the current line and a newline character to the current chunk.
    if cur.strip():  # Checks whether any non-empty text remains after the loop.
        out.append(cur.strip()) # Adds the final chunk to the output list
    return out # Returns all generated text chunks.


def chunk_trial(t: dict) -> list[dict]: # main function, takes one cleaned trial dictionary and creates its overview, inclusion, exclusion
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