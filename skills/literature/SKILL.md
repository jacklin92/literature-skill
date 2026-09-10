---
name: literature
description: Search, catalog, tag, filter, and organize academic literature/papers. Use when the user asks to search for papers, add a paper to their literature catalog, classify/tag existing entries, filter the catalog by criteria, or export citations as BibTeX.
---

# Literature management

The single source of truth is `data/literature.json` (relative to the project root where the skill is invoked). `data/literature.bib` is a derived export — **always regenerate it, never hand-edit it**.

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
conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" search "query" --limit 10
```

Calls the Crossref API and returns candidates (title/authors/year/venue/doi/url/abstract). **You (Claude) judge which results are actually relevant**, summarize them for the user, and let the user pick which ones to keep — never bulk-add everything automatically.

## Classification

Tags have no fixed taxonomy — decide short, consistent tags yourself from the title/abstract (e.g. `nlp`, `transformer`, `survey`). Reuse existing tags within the same organizing session instead of inventing synonyms; run `list` first to see what tags already exist.

## Add / update an entry

Add entries one at a time, piping JSON through stdin (avoids shell-escaping issues with special characters):

```
echo '{"title":"...","authors":["Author One","Author Two"],"year":2024,"venue":"journal or venue name","doi":"...","url":"...","abstract":"...","tags":["tag1","tag2"],"notes":"your own notes"}' | conda run -n literature python "${CLAUDE_PLUGIN_ROOT}/scripts/catalog.py" add
```

Dedup key: `doi` when present, otherwise `title + year`. Re-`add`ing the same entry updates it in place instead of creating a duplicate.

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
