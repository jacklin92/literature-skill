"""Literature catalog tool: JSON is the single source of truth, BibTeX is a derived export (never hand-edited).
Subcommands: add (from stdin JSON), add-doi (fetch by DOI), annotate (update notes/tags only),
remove (delete by DOI), search (OpenAlex), list (filter), tags, export-bib (write .bib).
Backed by OpenAlex (openalex.org): free, no API key, and unlike Crossref it also exposes
publisher and field/topic metadata plus a built-in open-access link.
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
    authors = entry.get("authors") or []
    author = last_name(authors[0]) if authors else "anon"
    return f"{slugify(author)}{entry.get('year', '')}{slugify((entry.get('title') or '')[:15])}"


def dedup_id(entry: dict) -> str:
    doi = (entry.get("doi") or "").strip().lower()
    if doi:
        return f"doi:{doi}"
    return f"ty:{slugify(entry.get('title', '')).lower()}:{entry.get('year', '')}"


def last_name(author: str) -> str:
    # Sources disagree on "Last, First" vs "First Last" for the same person - handle both.
    author = author.strip()
    if "," in author:
        return author.split(",", 1)[0].strip().lower()
    parts = author.split()
    return parts[-1].lower() if parts else ""


def fuzzy_key(entry: dict) -> tuple:
    """Same normalized title + first-author last name, ignoring DOI - catches the same paper
    saved twice under different DOIs (e.g. a preprint and its later published version).
    Deliberately exact-on-both-fields rather than a similarity score, to keep false positives rare.
    """
    title = re.sub(r"[^\w]+", "", (entry.get("title") or "").lower())
    authors = entry.get("authors") or []
    first_author = last_name(authors[0]) if authors else ""
    return (title, first_author)


def rebuild_abstract(inverted_index: dict) -> str:
    if not inverted_index:
        return ""
    slots = {}
    for word, positions in inverted_index.items():
        for pos in positions:
            slots[pos] = word
    return " ".join(slots[i] for i in sorted(slots))


def openalex_item_to_entry(it: dict) -> dict:
    """Map an OpenAlex work to our entry schema. OpenAlex covers publisher and field/topic
    metadata (which Crossref does not expose), plus a built-in open-access link — no separate
    lookup service needed. This never fetches the paper itself, only metadata + a link to it.
    """
    source = (it.get("primary_location") or {}).get("source") or {}
    topic = it.get("primary_topic") or {}
    doi = (it.get("doi") or "").removeprefix("https://doi.org/")
    return {
        "title": it.get("display_name") or it.get("title") or "",
        "authors": [
            (a.get("author") or {}).get("display_name", "")
            for a in it.get("authorships", [])
        ],
        "year": it.get("publication_year"),
        "venue": source.get("display_name", ""),
        "publisher": source.get("host_organization_name", ""),
        "field": (topic.get("field") or {}).get("display_name", ""),
        "type": it.get("type", ""),
        "doi": doi,
        "url": it.get("doi") or "",
        "abstract": rebuild_abstract(it.get("abstract_inverted_index")),
        "oa_url": (it.get("open_access") or {}).get("oa_url", ""),
    }


def get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "literature-skill/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.load(resp)


def openalex_id(url: str) -> str:
    return url.rsplit("/", 1)[-1] if url else ""


def resolve_source_id(name: str) -> str:
    data = get_json("https://api.openalex.org/sources?" + urllib.parse.urlencode({"search": name, "per_page": 1}))
    results = data.get("results") or []
    return openalex_id(results[0]["id"]) if results else ""


def resolve_publisher_id(name: str) -> str:
    data = get_json("https://api.openalex.org/publishers?" + urllib.parse.urlencode({"search": name, "per_page": 1}))
    results = data.get("results") or []
    return openalex_id(results[0]["id"]) if results else ""


def resolve_field_id(name: str) -> str:
    data = get_json("https://api.openalex.org/fields")
    needle = name.lower()
    for f in data.get("results") or []:
        names = [f.get("display_name", "")] + (f.get("display_name_alternatives") or [])
        if any(needle in n.lower() for n in names):
            return openalex_id(f["id"])
    return ""


def upsert(data_path: Path, entry: dict) -> str:
    entries = load(data_path)
    entry.setdefault("tags", [])
    entry["added_at"] = datetime.now(timezone.utc).isoformat()
    oa_note = f" (open access copy: {entry['oa_url']})" if entry.get("oa_url") else ""
    new_id = dedup_id(entry)
    for i, existing in enumerate(entries):
        if dedup_id(existing) == new_id:
            entry["added_at"] = existing.get("added_at", entry["added_at"])
            entries[i] = entry
            save(data_path, entries)
            return f"Updated existing entry: {entry.get('title')}{oa_note}"

    dup_note = ""
    target_key = fuzzy_key(entry)
    if target_key[0]:  # non-empty normalized title
        for existing in entries:
            if fuzzy_key(existing) == target_key and existing.get("doi") != entry.get("doi"):
                dup_note = f" (note: possible duplicate of existing entry under a different DOI: {existing.get('doi') or '<no doi>'})"
                break

    entries.append(entry)
    save(data_path, entries)
    return f"Added: {entry.get('title')}{oa_note}{dup_note}"


def cmd_add(args):
    entry = json.loads(sys.stdin.read())
    print(upsert(args.data, entry))


def cmd_add_doi(args):
    doi = args.doi.strip()
    data = get_json(f"https://api.openalex.org/works/doi:{doi}")
    entry = openalex_item_to_entry(data)
    print(upsert(args.data, entry))


def cmd_annotate(args):
    if args.notes is None and args.tags is None:
        print("Nothing to do: pass --notes and/or --tags", file=sys.stderr)
        sys.exit(1)
    entries = load(args.data)
    target = args.doi.strip().lower()
    for e in entries:
        if (e.get("doi") or "").strip().lower() == target:
            if args.notes is not None:
                e["notes"] = args.notes
            if args.tags is not None:
                e["tags"] = [t.strip() for t in args.tags.split(",") if t.strip()]
            save(args.data, entries)
            print(f"Annotated: {e.get('title')}")
            return
    print(f"No entry found with doi {args.doi}", file=sys.stderr)
    sys.exit(1)


def cmd_remove(args):
    entries = load(args.data)
    target = args.doi.strip().lower()
    kept = [e for e in entries if (e.get("doi") or "").strip().lower() != target]
    if len(kept) == len(entries):
        print(f"No entry found with doi {args.doi}", file=sys.stderr)
        sys.exit(1)
    save(args.data, kept)
    print(f"Removed entry with doi {args.doi}")


def build_search_filters(args) -> list:
    filters = []
    if args.author:
        filters.append(f"raw_author_name.search:{args.author}")
    if args.venue:
        source_id = resolve_source_id(args.venue)
        if source_id:
            filters.append(f"primary_location.source.id:{source_id}")
        else:
            print(f"Note: no matching venue found for '{args.venue}', ignoring --venue", file=sys.stderr)
    if args.publisher:
        publisher_id = resolve_publisher_id(args.publisher)
        if publisher_id:
            filters.append(f"primary_location.source.host_organization_lineage:{publisher_id}")
        else:
            print(f"Note: no matching publisher found for '{args.publisher}', ignoring --publisher", file=sys.stderr)
    if args.field:
        field_id = resolve_field_id(args.field)
        if field_id:
            filters.append(f"primary_topic.field.id:{field_id}")
        else:
            print(f"Note: no matching field found for '{args.field}', ignoring --field", file=sys.stderr)
    if args.from_year:
        filters.append(f"from_publication_date:{args.from_year}-01-01")
    if args.until_year:
        filters.append(f"to_publication_date:{args.until_year}-12-31")
    return filters


def cmd_search(args):
    params = {"per_page": min(args.limit, 200)}
    if args.query:
        params["search"] = args.query
    filters = build_search_filters(args)
    if filters:
        params["filter"] = ",".join(filters)
    url = "https://api.openalex.org/works?" + urllib.parse.urlencode(params)
    data = get_json(url)
    results = [openalex_item_to_entry(it) for it in data.get("results", [])]

    local_entries = load(args.data)
    known_dois = {(e.get("doi") or "").strip().lower() for e in local_entries if e.get("doi")}
    fuzzy_index = {fuzzy_key(e): e.get("doi", "") for e in local_entries if fuzzy_key(e)[0]}
    for r in results:
        r["already_saved"] = bool(r.get("doi")) and r["doi"].strip().lower() in known_dois
        if not r["already_saved"]:
            match_doi = fuzzy_index.get(fuzzy_key(r))
            if match_doi is not None:
                r["possible_duplicate_of"] = match_doi

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
    if getattr(args, "field", None) and args.field.lower() not in (entry.get("field") or "").lower():
        return False
    if args.keyword:
        needle = args.keyword.lower()
        haystack = f"{entry.get('title', '')} {entry.get('abstract', '')} {entry.get('notes', '')}".lower()
        if needle not in haystack:
            return False
    return True


def cmd_list(args):
    entries = [e for e in load(args.data) if matches(e, args)]
    print(json.dumps(entries, ensure_ascii=False, indent=2))


def cmd_tags(args):
    tags = sorted({t for e in load(args.data) for t in (e.get("tags") or [])})
    print(json.dumps(tags, ensure_ascii=False, indent=2))


BIBTEX_TYPE_MAP = {
    "conference-paper": "inproceedings",
    "book-chapter": "incollection",
    "book": "book",
    "dissertation": "phdthesis",
    "report": "techreport",
}


def to_bibtex(entry: dict) -> str:
    key = make_key(entry)
    entry_type = BIBTEX_TYPE_MAP.get(entry.get("type", ""))
    if entry_type is None:
        entry_type = "article" if entry.get("venue") else "misc"
    fields = {
        "title": entry.get("title", ""),
        "author": " and ".join(entry.get("authors") or []),
        "year": str(entry.get("year", "")),
    }
    # ponytail: one field set for every entry type (not per-type BibTeX fields e.g. booktitle
    # for incollection) - good enough for a personal catalog, revisit if a style guide complains.
    if entry.get("venue"):
        fields["journal"] = entry["venue"]
    if entry.get("publisher"):
        fields["publisher"] = entry["publisher"]
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

    p_add_doi = sub.add_parser("add-doi", help="Fetch by DOI from OpenAlex and add/update")
    p_add_doi.add_argument("doi")
    p_add_doi.set_defaults(func=cmd_add_doi)

    p_annotate = sub.add_parser("annotate", help="Update only notes/tags on an existing entry, by DOI")
    p_annotate.add_argument("doi")
    p_annotate.add_argument("--notes")
    p_annotate.add_argument("--tags", help="Comma-separated, replaces the existing tag list")
    p_annotate.set_defaults(func=cmd_annotate)

    p_remove = sub.add_parser("remove", help="Remove an entry by DOI")
    p_remove.add_argument("doi")
    p_remove.set_defaults(func=cmd_remove)

    p_search = sub.add_parser("search", help="Search OpenAlex")
    p_search.add_argument("query", nargs="?", default="")
    p_search.add_argument("--author")
    p_search.add_argument("--venue", help="Journal/conference name")
    p_search.add_argument("--publisher")
    p_search.add_argument("--field", help="Academic field/discipline, e.g. 'Computer Science'")
    p_search.add_argument("--from-year")
    p_search.add_argument("--until-year")
    p_search.add_argument("--limit", type=int, default=10)
    p_search.set_defaults(func=cmd_search)

    for name, func in (("list", cmd_list),):
        p = sub.add_parser(name, help="List/filter the local catalog")
        p.add_argument("--tag")
        p.add_argument("--year")
        p.add_argument("--author")
        p.add_argument("--field")
        p.add_argument("--keyword")
        p.set_defaults(func=func)

    sub.add_parser("tags", help="List distinct tags already in use").set_defaults(func=cmd_tags)

    p_bib = sub.add_parser("export-bib", help="Export the (optionally filtered) catalog to .bib")
    p_bib.add_argument("--tag")
    p_bib.add_argument("--year")
    p_bib.add_argument("--author")
    p_bib.add_argument("--field")
    p_bib.add_argument("--keyword")
    p_bib.add_argument("--output", type=Path, default=DEFAULT_BIB)
    p_bib.set_defaults(func=cmd_export_bib)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
