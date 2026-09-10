# literature-skill

A Claude Code plugin: search, catalog, tag, filter, and export (BibTeX) academic literature.

`data/literature.json` (in your project) is the single source of truth; `data/literature.bib` is a derived export, always regenerated, never hand-edited.

## Install

```
claude
```

then, in `settings.json`:

```json
{
  "extraKnownMarketplaces": {
    "literature-skill": {
      "source": { "source": "github", "repo": "jacklin92/literature-skill" }
    }
  },
  "enabledPlugins": {
    "literature@literature-skill": true
  }
}
```

Or install interactively with `/plugin marketplace add jacklin92/literature-skill` followed by `/plugin install literature@literature-skill`.

## Requirements

- A conda environment named `literature` (the skill creates it on first use if missing: `conda create -n literature python=3.11 -y`). No extra packages needed — the script only uses the Python standard library.

## Usage

Just ask Claude, in your own words, to search for papers, add one to your catalog, tag/classify entries, filter the catalog, or export citations as BibTeX. See `skills/literature/SKILL.md` for exactly what Claude runs under the hood.
