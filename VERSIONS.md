# Versions

The skill writes one fixed document format. The builder and bundled shape catalog need to agree with the version named here.

| What | Current | Source |
|---|---|---|
| Skill | 0.1.0 | `.claude-plugin/plugin.json` |
| Package format | 15 | `FORMAT_VERSION` in `scripts/sd_format.py` |
| Document schema | 14 | `SCHEMA_VERSION` in `scripts/sd_format.py` |
| Diagram spec | 1 | `SPEC_VERSION` in `scripts/sd_spec.py` |
| Built-in shape catalog | Catalog 1, from SimpleDiagrams 5.0.9 | `assets/built-in-shapes.json` |

The document format began in SimpleDiagrams for macOS 5.0.8; the bundled catalog came from 5.0.9. The 280 shape IDs, versions, and sizes match the current desktop source checkout (5.0.11 development line). Check compatibility with each release before claiming support for it.

## Compatibility rules

- One skill release writes one package format. A new package format requires a major skill release.
- Spec version 1 keeps its meaning. Add a later version alongside it instead of silently changing version 1.
- Do not remove or rename a catalog shape, or change an asset version in place, within the same format.
- Regenerate JSON Schemas when the models change, and run the tests before release.

The tests check the 15/14 version pair, generated schemas, required fields, catalog size, and the version statements in the release files. They do not establish compatibility with future desktop releases.
