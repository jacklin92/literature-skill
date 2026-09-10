"""Literature catalog tool: JSON is the single source of truth, BibTeX is a derived export (never hand-edited).
Subcommands: add (from stdin JSON), search (Crossref), list (filter), export-bib (write .bib).
"""
import argparse
import json
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


def cmd_add(args):
    entries = load(args.data)
    raw = sys.stdin.read()
    entry = json.loads(raw)
    entry.setdefault("tags", [])
    entry["added_at"] = datetime.now(timezone.utc).isoformat()
    new_id = dedup_id(entry)
    for i, existing in enumerate(entries):
        if dedup_id(existing) == new_id:
            entry["added_at"] = existing.get("added_at", entry["added_at"])
            entries[i] = entry
            save(args.data, entries)
            print(f"Updated existing entry: {entry.get('title')}")
            return
    entries.append(entry)
    save(args.data, entries)
    print(f"Added: {entry.get('title')}")


def cmd_search(args):
    url = "https://api.crossref.org/works?" + urllib.parse.urlencode(
        {"query": args.query, "rows": args.limit}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "literature-skill/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = json.load(resp)
    items = data.get("message", {}).get("items", [])
    results = []
    for it in items:
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
        results.append({
            "title": (it.get("title") or [""])[0],
            "authors": authors,
            "year": year,
            "venue": (it.get("container-title") or [""])[0],
            "doi": it.get("DOI", ""),
            "url": it.get("URL", ""),
            "abstract": re.sub("<[^>]+>", "", it.get("abstract", "")),
        })
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
