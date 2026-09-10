---
name: literature
description: Search, catalog, tag, filter, and organize academic literature/papers. Use when the user asks to search for papers, add a paper to their literature catalog, classify/tag existing entries, filter the catalog by criteria, or export citations as BibTeX.
---

# Literature management

The single source of truth is `data/literature.json` (relative to the project root where the skill is invoked). `data/literature.bib` is a derived export — **always regenerate it, never hand-edit it**. To keep it in sync with zero extra effort: **run `export-bib` right after every `add`/`add-doi`** that changes the catalog, so the .bib file is never stale without the user having to ask.

Search/lookup is backed by [OpenAlex](https://openalex.org/) (free, no API key). The skill **must never download full text or PDFs** — only bibliographic metadata, abstracts, and open-access links, regardless of a paper's access status (OpenAlex reports a native `oa_url` when a legal open copy exists — still just a link, never fetched).

## One-time environment setup

The script only needs the Python standard library, no extra packages. Make sure a conda env named `literature` exists; create it if it doesn't:

```
conda env list
conda create -n literature python=3.11 -y   # only if "literature" isn't listed above
```

## Running the core script

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" <subcommand> ...
```

> Troubleshooting: on some Windows setups (locale/codepage dependent), `conda run` can raise a `UnicodeEncodeError` when the subprocess prints non-ASCII text. Workaround: resolve the env's own `python.exe` path with `conda info --envs`, then call `<that path>\python.exe "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" ...` directly instead of going through `conda run`.

## Search for literature

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" search "query" [--author NAME] [--venue "journal or conference name"] [--publisher NAME] [--field "academic field"] [--from-year YEAR] [--until-year YEAR] --limit 10
```

`query` is free-text topic/keywords. All the flags narrow it further and can be combined with `query` or used alone:

- `--author` — author name
- `--venue` — journal/conference name
- `--publisher` — publisher name (e.g. `Springer`, `Nature Portfolio`, `Elsevier`)
- `--field` — academic field/discipline (OpenAlex's fixed top-level taxonomy, e.g. `Computer Science`, `Medicine`, `Physics` — pass whatever the user says, it's matched case-insensitively against the taxonomy)
- `--from-year` / `--until-year` — publication year range

`--venue`, `--publisher`, and `--field` are resolved to OpenAlex entity IDs first; if nothing matches, that filter is dropped with a note on stderr rather than failing the whole search.

Calls OpenAlex and returns candidates (title/authors/year/venue/publisher/field/doi/url/abstract/oa_url). **You (Claude) judge which results are actually relevant**, summarize them for the user, and let the user pick which ones to keep — never bulk-add everything automatically.

The JSON object each search result gives you already matches what `add` expects — pipe it straight into `add` after adding a `tags` field, no reshaping needed.

If the user already has a specific DOI (they pasted a link, or picked one from search results), prefer `add-doi` over `search` + `add` — it fetches the authoritative record directly, so metadata is more accurate than a keyword search and there's no manual JSON to write:

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" add-doi "10.xxxx/..."
```

## Relevance analysis and notes

Before adding anything from a search, work through three things — say them in the chat, and distill the result into the entry's `notes` so the judgment isn't lost once the conversation scrolls past it:

1. **Judge relevance against what the user actually asked for**, not just topical overlap. Sharing a keyword isn't relevance; ask whether this paper's content would actually help what they're trying to do. If the abstract doesn't give you enough to tell, say so rather than guessing.
2. **Pin down what specifically is relevant** — the part of the abstract that connects to the user's stated need, not a restatement of the whole abstract.
3. **Summarize the core architecture/technique with zero fluff** — no "this important paper demonstrates...", no restating the title, no generic praise. State the method/approach in as few words as it takes to be accurate.

This is based on title + abstract only — never full text (see the copyright note above); if that's not enough to do #3 justice, say so instead of padding it out. Write the distilled result into `notes` when you `add`/`add-doi`, e.g.:

```
"notes": "Relevant to: <the specific need>. Approach: <terse technique description>."
```

so `list`/`export-bib` carry that judgment forward instead of it living only in chat history.

## Classification

Two independent dimensions, don't confuse them:

- `field` is auto-populated from OpenAlex's own topic classification (search/add-doi set it automatically) — a real discipline label, not something you invent.
- `tags` have no fixed taxonomy — decide short, consistent tags yourself from the title/abstract (e.g. `nlp`, `transformer`, `survey`) for whatever finer-grained grouping `field` doesn't capture. Reuse existing tags within the same organizing session instead of inventing synonyms. Check what's already in use with:

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" tags
```

This is cheaper than pulling the whole catalog with `list` just to see the tag vocabulary.

## Add / update an entry

Add entries one at a time, piping JSON through stdin (avoids shell-escaping issues with special characters):

```
echo '{"title":"...","authors":["Author One","Author Two"],"year":2024,"venue":"journal or venue name","publisher":"...","field":"...","doi":"...","url":"...","abstract":"...","tags":["tag1","tag2"],"notes":"your own notes"}' | conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" add
```

Dedup key: `doi` when present, otherwise `title + year`. Re-`add`ing (or re-`add-doi`ing) the same entry updates it in place instead of creating a duplicate. Follow up with `export-bib` (see top of this file) so the exported citations stay current.

## Filter / list

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" list [--tag TAG] [--year YEAR] [--author NAME] [--field TEXT] [--keyword TEXT]
```

Filters can be combined freely (all given filters must match); omit all of them to list everything. (No `--venue`/`--publisher` filter locally — use `--keyword` for that, since it already matches against title/abstract text, or ask Claude to eyeball the small full listing.)

## Export BibTeX

```
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" export-bib [--tag TAG] [--year YEAR] [--author NAME] [--field TEXT] [--keyword TEXT] [--output PATH]
```

No filters exports everything, defaulting to `data/literature.bib`. To export citations for just one topic, pass the matching filter flags — no extra scripting needed.
