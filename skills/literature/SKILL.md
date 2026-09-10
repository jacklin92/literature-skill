---
name: literature
description: Search, catalog, tag, filter, and organize academic literature/papers. Use when the user asks to search for papers, add a paper to their literature catalog, classify/tag existing entries, filter the catalog by criteria, or export citations as BibTeX.
---

# Literature management

The single source of truth is `data/literature.json` (relative to the project root where the skill is invoked). `data/literature.bib` is a derived export — **always regenerate it, never hand-edit it**. To keep it in sync with zero extra effort: **run `export-bib` right after every `add`/`add-doi`** that changes the catalog, so the .bib file is never stale without the user having to ask.

## One-time environment setup

The script only needs the Python standard library, no extra packages. Make sure a conda env named `literature` exists; create it if it doesn't:

```
conda env list
conda create -n literature python=3.11 -y   # only if "literature" isn't listed above
```

Optionally set `UNPAYWALL_EMAIL` (any real contact email of the user's) so `add`/`add-doi` can also look up a legal open-access copy via Unpaywall — best-effort, and silently skipped if the env var isn't set. This never fetches the paper itself, only a link to where a legal free copy exists; **the skill must never download full text or PDFs**, regardless of a paper's open-access status — only bibliographic metadata, abstracts, and OA links.

## Running the core script

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" <subcommand> ...
```

> Troubleshooting: on some Windows setups (locale/codepage dependent), `conda run` can raise a `UnicodeEncodeError` when the subprocess prints non-ASCII text. Workaround: resolve the env's own `python.exe` path with `conda info --envs`, then call `<that path>\python.exe "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" ...` directly instead of going through `conda run`.

## Search for literature

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" search "query" [--author NAME] [--venue "journal or conference name"] [--from-year YEAR] [--until-year YEAR] --limit 10
```

`query` is free-text topic/keywords; `--author`, `--venue` (journal/conference name), and `--from-year`/`--until-year` (publication date range) narrow it further via Crossref's own query fields, and can be combined with `query` or used alone. Crossref has no publisher-name filter and no subject/field-of-study filter — if the user asks to filter by publisher or academic field, those aren't queryable upstream; field/discipline grouping is handled locally instead, via tags (see Classification below).

Calls the Crossref API and returns candidates (title/authors/year/venue/doi/url/abstract). **You (Claude) judge which results are actually relevant**, summarize them for the user, and let the user pick which ones to keep — never bulk-add everything automatically.

The JSON object each search result gives you already matches what `add` expects — pipe it straight into `add` after adding a `tags` field, no reshaping needed.

If the user already has a specific DOI (they pasted a link, or picked one from search results), prefer `add-doi` over `search` + `add` — it fetches the authoritative Crossref record directly, so metadata is more accurate than a keyword search and there's no manual JSON to write:

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" add-doi "10.xxxx/..."
```

## Classification

Tags have no fixed taxonomy — decide short, consistent tags yourself from the title/abstract (e.g. `nlp`, `transformer`, `survey`). Reuse existing tags within the same organizing session instead of inventing synonyms. Check what's already in use with:

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" tags
```

This is cheaper than pulling the whole catalog with `list` just to see the tag vocabulary.

## Add / update an entry

Add entries one at a time, piping JSON through stdin (avoids shell-escaping issues with special characters):

```
echo '{"title":"...","authors":["Author One","Author Two"],"year":2024,"venue":"journal or venue name","doi":"...","url":"...","abstract":"...","tags":["tag1","tag2"],"notes":"your own notes"}' | conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" add
```

Dedup key: `doi` when present, otherwise `title + year`. Re-`add`ing (or re-`add-doi`ing) the same entry updates it in place instead of creating a duplicate. Follow up with `export-bib` (see top of this file) so the exported citations stay current.

## Filter / list

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" list [--tag TAG] [--year YEAR] [--author NAME] [--keyword TEXT]
```

Filters can be combined freely (all given filters must match); omit all of them to list everything.

## Export BibTeX

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" export-bib [--tag TAG] [--year YEAR] [--author NAME] [--keyword TEXT] [--output PATH]
```

No filters exports everything, defaulting to `data/literature.bib`. To export citations for just one topic, pass the matching filter flags — no extra scripting needed.
