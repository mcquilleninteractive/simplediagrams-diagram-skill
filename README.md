# Build SimpleDiagrams diagrams

This Agent Skill creates new editable `.simplediagram` documents from a description or from an image of a diagram. It searches the public shape catalogue and uses a small JSON spec for nodes, labels, positions and connectors. The builder writes the document package and checks its structure and layout.

It writes document format 15, which opens in SimpleDiagrams for macOS 5.0.8 and later. A document that uses a shape from a downloadable library is written at format 16, which names that library and opens in 5.0.16 and later; its shapes appear in 5.1.0 and later with the library installed. The skill retains an offline catalogue from SimpleDiagrams 5.1.0 (not yet released) with 534 packaged shapes in eight libraries. The 89 BPMN shapes, the 8 UML shapes and the 10 newer Basic shapes need 5.1.0; the 58 newer Biz shapes need 5.0.16; the 89 added UI Flow shapes need 5.0.12. Earlier apps show placeholders for shapes they do not contain. The builder says when a document needs a newer app or a library. Searching and building need Python 3.10+ and Pydantic 2; `uv run` may download Pydantic when it is not cached.

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

- Creates new documents using native rectangles, ellipses, notes, text, connectors, and the eight bundled shape libraries, BPMN and UML included. A library shape gets the connection points and label placement its library gives it, as in the app, except that a name the app centres below a narrow shape, wider than it, is kept to the shape's width or written as a caption.
- Searches all published libraries through `https://simplediagrams.com/shape-libraries/catalog.json`, with one request per command, nothing stored, and the bundled packaged list offline.
- Places every catalogued shape by its exact API reference: packaged shapes by the app's own names, downloadable ones by their published UUIDs. A document with downloadable shapes names their libraries, so SimpleDiagrams puts the artwork in place when the library is installed and otherwise names the library and links to its page. Personal libraries, embedded images and shape data remain outside this authoring profile.
- Redraws a pictured diagram as boxes and connectors. It does not trace artwork or handwriting or embed the picture. A connector can attach to any connection point a shape has, so pin-level wiring is drawn where the parts' library shapes give their pins or leads as connection points.
- Never overwrites an existing document. Keep the JSON spec to rebuild under a new name.
- The scripts send nothing but the one catalogue request, which carries no diagram content; the AI service running the skill handles your files under its own policies.

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
| `references/shape-catalogue.md` | API search, requests and offline behavior |
| `references/document-format.md` | Generated package structure |
| `assets/built-in-shapes.json` | 534 packaged shapes, with their connection points and label placement, for offline fallback |
| `assets/example-spec.json` | Example input |
| `scripts/find_shapes.py` | Search names, descriptions and keywords across published libraries |
| `scripts/sd_catalog.py` | One bounded, validated catalogue request, with the packaged fallback |
| `scripts/build_diagram.py` | Check a spec and build a new package |
| `scripts/preview_diagram.py` | Render a new wireframe SVG from a spec |
| `scripts/sd_spec.py`, `scripts/sd_format.py`, `scripts/sd_package.py` | Spec compiler, format models, and package writer (checked in memory before writing) |
| `schema/` | Generated JSON Schemas |

The skill is MIT licensed. SimpleDiagrams and its built-in shapes have separate licenses.
