# Build SimpleDiagrams diagrams

This Agent Skill creates new editable `.simplediagram` documents from a description or from an image of a diagram. It searches the public shape catalogue and uses a small JSON spec for nodes, labels, positions and connectors. The builder writes the document package and checks its structure and layout.

It writes document format 15, which opens in SimpleDiagrams for macOS 5.0.8 and later, and retains an offline catalogue from SimpleDiagrams after 5.0.16 (unreleased) with 510 packaged shapes in seven libraries. The 83 BPMN shapes need the first release after 5.0.16; the 58 newer Biz shapes need 5.0.16; the 89 added UI Flow shapes need 5.0.12. Earlier apps show placeholders for shapes they do not contain. The builder says when a document needs a newer app. Searching and building need Python 3.10+ and Pydantic 2; `uv run` may download Pydantic when it is not cached.

## Install

In Claude Code:

```bash
claude plugin marketplace add mcquilleninteractive/simplediagrams-diagram-skill
claude plugin install simplediagrams-diagram-skill@simplediagrams
```

To install by copying, keep the folder name `simplediagrams-diagram-skill`.

- Claude Code: copy it into `~/.claude/skills/` or a project's `.claude/skills/`.
- Codex: copy it into `$HOME/.agents/skills/` or a repository's `.agents/skills/`.
- Other agents: point the agent at `SKILL.md`.

## Example requests

> Use the simplediagrams-diagram-skill skill to draw how a customer order moves through our web shop, order service, payments and warehouse.

- "Diagram the architecture described in this repository's README."
- "Make an org chart for this team."
- "Turn this procedure into a flowchart."
- "Redraw this whiteboard photo as a diagram."

## Scope

- Creates new documents using native rectangles, ellipses, notes, text, connectors, and the seven bundled shape libraries, BPMN included. A library shape gets the connection points and label placement its library gives it, as in the app.
- Searches all published libraries through `https://simplediagrams.com/shape-libraries/catalog.json`, with hourly ETag caching and explicit offline fallback.
- Places packaged shapes using their exact API references. Downloaded-library metadata is searchable, but the builder refuses those placements because desktop 5.0.16 cannot yet resolve them. Their artwork must be placed manually in the app. Personal libraries, embedded images and shape data remain outside this authoring profile.
- Redraws a pictured diagram as boxes and connectors. It does not trace artwork or handwriting, embed the picture, or draw pin-level wiring.
- Never overwrites an existing document. Keep the JSON spec to rebuild under a new name.

## Build locally

```bash
uv run scripts/build_diagram.py assets/example-spec.json
uv run scripts/build_diagram.py assets/example-spec.json "Order flow.simplediagram"
```

The first command checks without writing. The second creates the package at a new path.

## Files

| Path | Purpose |
|---|---|
| `SKILL.md` | Agent instructions |
| `references/visual-design.md` | Layout guidance |
| `references/from-an-image.md` | Redrawing a photo, scan, or screenshot of a diagram |
| `references/shape-catalogue.md` | API search, cache and offline behavior |
| `references/document-format.md` | Generated package structure |
| `assets/built-in-shapes.json` | 510 packaged shapes, with their connection points and label placement, for offline fallback |
| `assets/example-spec.json` | Example input |
| `scripts/find_shapes.py` | Search names, descriptions and keywords across published libraries |
| `scripts/sd_catalog.py` | Bounded API validation, ETag caching and offline fallback |
| `scripts/build_diagram.py` | Check a spec and build a new package |
| `scripts/preview_diagram.py` | Render a new wireframe SVG from a spec |
| `scripts/sd_spec.py`, `scripts/sd_format.py`, `scripts/sd_package.py` | Spec compiler, format models, and package writer |
| `schema/` | Generated JSON Schemas |

The skill is MIT licensed. SimpleDiagrams and its built-in shapes have separate licenses.
