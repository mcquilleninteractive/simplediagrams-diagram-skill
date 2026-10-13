# Versions

The skill writes one fixed document format. The builder and bundled shape catalog need to agree with the version named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.1.0 | `.claude-plugin/plugin.json` |
| Package format | 15 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 14 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams 5.0.14 | `assets/built-in-shapes.json` |

The document format began in SimpleDiagrams for macOS 5.0.8. The bundled catalog was regenerated on 13 October 2026 from the desktop app's own bundled catalogue, which is the source of truth for the six packaged libraries: 369 shape IDs, versions and sizes, unchanged in the app since 5.0.12. The 280 shapes of the first catalog (from 5.0.9) are all still present with the same names, sizes and versions; the 89 added are UI Flow shapes that exist from 5.0.12, and a diagram using one shows a dashed placeholder in an earlier version. Check compatibility with each release before claiming support for it.

Each library also lists `published_library_id`, and each shape `published_item_id`: the same shape's identifiers on the SimpleDiagrams website. They are for matching against the website's catalogue. A `symbol_reference` for a packaged shape is still written with `library_id`, `item_id` and `asset_version`, which every version from 5.0.8 understands.

When the skill reads the website's catalogue, the website's information supersedes this file. This file is what the skill uses without the network.

## Compatibility rules

- One skill release writes one package format. A new package format requires a major skill release.
- Spec version 1 keeps its meaning. Add a later version alongside it instead of silently changing version 1.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 15/14 version pair, generated schemas, required fields, catalog size, and the version statements in the release files. They do not establish compatibility with future desktop releases.
