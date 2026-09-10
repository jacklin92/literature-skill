"""Literature catalog tool: JSON is the single source of truth, BibTeX is a derived export (never hand-edited).
Subcommands: add (from stdin JSON), add-doi (fetch by DOI), search (Crossref), list (filter), tags, export-bib (write .bib).
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except AttributeError:
    pass

DEFAULT_JSON = Path("data/literature.json")
DEFAULT_BIB = Path("data/literature.bib")


def load(path: Path) -> list:
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, entries: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def slugify(text: str) -> str:
    text = re.sub(r"[^\w]+", "", text or "")
    return text[:40] or "untitled"


def make_key(entry: dict) -> str:
    author = (entry.get("authors") or ["anon"])[0].split()[-1] if entry.get("authors") else "anon"
    return f"{slugify(author)}{entry.get('year', '')}{slugify((entry.get('title') or '')[:15])}"


def dedup_id(entry: dict) -> str:
    doi = (entry.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    return f"ty:{slugify(entry.get('title', '')).lower()}:{entry.get('year', '')}"


def crossref_item_to_entry(it: dict) -> dict:
    authors = [
        f"{a.get('given', '')} {a.get('family', '')}".strip()
        for a in it.get("author", [])
    ]
    year = None
    for date_field in ("published-print", "published-online", "issued"):
        parts = it.get(date_field, {}).get("date-parts")
        if parts and parts[0]:
            year = parts[0][0]
            break
    return {
        "title": (it.get("title") or [""])[0],
        "authors": authors,
        "year": year,
        "venue": (it.get("container-title") or [""])[0],
        "doi": it.get("DOI", ""),
        "url": it.get("URL", ""),
        "abstract": re.sub("<[^>]+>", "", it.get("abstract", "")),
    }


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "literature-skill/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def find_oa_url(doi: str) -> str:
    """Look up a legal open-access copy via Unpaywall (metadata/link only, never fetches the paper itself).
    Needs the UNPAYWALL_EMAIL env var (Unpaywall's API requires a contact email); skipped if unset.
    """
    email = os.environ.get("UNPAYWALL_EMAIL")
    if not email or not doi:
        return ""
    url = f"https://api.unpaywall.org/v2/{urllib.parse.quote(doi)}?email={urllib.parse.quote(email)}"
    try:
        data = get_json(url)
    except Exception:
        return ""
    if not data.get("is_oa"):
        return ""
    return (data.get("best_oa_location") or {}).get("url", "")


def upsert(data_path: Path, entry: dict) -> str:
    entries = load(data_path)
    entry.setdefault("tags", [])
    if entry.get("doi") and not entry.get("oa_url"):
        oa_url = find_oa_url(entry["doi"])
        if oa_url:
            entry["oa_url"] = oa_url
    entry["added_at"] = datetime.now(timezone.utc).isoformat()
    oa_note = f" (open access copy: {entry['oa_url']})" if entry.get("oa_url") else ""
    new_id = dedup_id(entry)
    for i, existing in enumerate(entries):
        if dedup_id(existing) == new_id:
            entry["added_at"] = existing.get("added_at", entry["added_at"])
            entries[i] = entry
            save(data_path, entries)
            return f"Updated existing entry: {entry.get('title')}{oa_note}"
    entries.append(entry)
    save(data_path, entries)
    return f"Added: {entry.get('title')}{oa_note}"


def cmd_add(args):
    entry = json.loads(sys.stdin.read())
    print(upsert(args.data, entry))


def cmd_add_doi(args):
    doi = args.doi.strip()
    data = get_json(f"https://api.crossref.org/works/{urllib.parse.quote(doi)}")
    entry = crossref_item_to_entry(data.get("message", {}))
    print(upsert(args.data, entry))


def cmd_search(args):
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
        {"query": args.query, "rows": args.limit}
    )
    data = get_json(url)
    items = data.get("message", {}).get("items", [])
    results = [crossref_item_to_entry(it) for it in items]
    print(json.dumps(results, ensure_ascii=False, indent=2))


def matches(entry: dict, args) -> bool:
    if args.tag and args.tag not in (entry.get("tags") or []):
        return False
    if args.year and str(entry.get("year")) != str(args.year):
        return False
    if args.author:
        needle = args.author.lower()
        if not any(needle in a.lower() for a in entry.get("authors") or []):
            return False
    if args.keyword:
        needle = args.keyword.lower()
        haystack = f"{entry.get('title', '')} {entry.get('abstract', '')}".lower()
        if needle not in haystack:
            return False
    return True


def cmd_list(args):
    entries = [e for e in load(args.data) if matches(e, args)]
    print(json.dumps(entries, ensure_ascii=False, indent=2))


def cmd_tags(args):
    tags = sorted({t for e in load(args.data) for t in (e.get("tags") or [])})
    print(json.dumps(tags, ensure_ascii=False, indent=2))


def to_bibtex(entry: dict) -> str:
    key = make_key(entry)
    entry_type = "article" if entry.get("venue") else "misc"
    fields = {
        "title": entry.get("title", ""),
        "author": " and ".join(entry.get("authors") or []),
        "year": str(entry.get("year", "")),
    }
    if entry.get("venue"):
        fields["journal"] = entry["venue"]
    if entry.get("doi"):
        fields["doi"] = entry["doi"]
    if entry.get("url"):
        fields["url"] = entry["url"]
    if entry.get("oa_url"):
        fields["note"] = f"Open access: {entry['oa_url']}"
    body = ",\n".join(f"  {k} = {{{v}}}" for k, v in fields.items() if v)
    return f"@{entry_type}{{{key},\n{body}\n}}"


def cmd_export_bib(args):
    entries = [e for e in load(args.data) if matches(e, args)]
    text = "\n\n".join(to_bibtex(e) for e in entries) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(text, encoding="utf-8")
    print(f"Exported {len(entries)} entries to {args.output}")


def main():
    parser = argparse.ArgumentParser(description="Literature catalog tool")
    parser.add_argument("--data", type=Path, default=DEFAULT_JSON)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("add", help="Add/update one entry from a JSON object on stdin").set_defaults(func=cmd_add)

    p_add_doi = sub.add_parser("add-doi", help="Fetch by DOI from Crossref and add/update")
    p_add_doi.add_argument("doi")
    p_add_doi.set_defaults(func=cmd_add_doi)

    p_search = sub.add_parser("search", help="Search Crossref")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    for name, func in (("list", cmd_list),):
        p = sub.add_parser(name, help="List/filter the local catalog")
        p.add_argument("--tag")
        p.add_argument("--year")
        p.add_argument("--author")
        p.add_argument("--keyword")
        p.set_defaults(func=func)

    sub.add_parser("tags", help="List distinct tags already in use").set_defaults(func=cmd_tags)

    p_bib = sub.add_parser("export-bib", help="Export the (optionally filtered) catalog to .bib")
    p_bib.add_argument("--tag")
    p_bib.add_argument("--year")
    p_bib.add_argument("--author")
    p_bib.add_argument("--keyword")
    p_bib.add_argument("--output", type=Path, default=DEFAULT_BIB)
    p_bib.set_defaults(func=cmd_export_bib)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
