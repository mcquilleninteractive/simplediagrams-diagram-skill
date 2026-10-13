# Build SimpleDiagrams diagrams

This Agent Skill creates new editable `.simplediagram` documents from a description or from an image of a diagram. It uses a bundled catalog of built-in shapes and a small JSON spec for nodes, labels, positions, and connectors. The builder writes the document package and checks its structure and layout.

It uses document format 15 and a built-in shape catalog from SimpleDiagrams for macOS 5.0.14 (369 shapes; the 89 UI Flow shapes added in 5.0.12 show as dashed placeholders in earlier versions). Building needs Python 3.10+ and Pydantic 2; `uv run` may download Pydantic when it is not cached.

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

- Creates new documents using native rectangles, ellipses, notes, text, connectors, and the six bundled shape libraries.
- Uses only the static catalog included with the skill. Downloaded or personal libraries, images, and shape data are outside this authoring profile.
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
| `references/document-format.md` | Generated package structure |
| `assets/built-in-shapes.json` | Available library shape IDs and natural sizes |
| `assets/example-spec.json` | Example input |
| `scripts/find_shapes.py` | Search the bundled catalog |
| `scripts/build_diagram.py` | Check a spec and build a new package |
| `scripts/preview_diagram.py` | Render a new wireframe SVG from a spec |
| `scripts/sd_spec.py`, `scripts/sd_format.py`, `scripts/sd_package.py` | Spec compiler, format models, and package writer |
| `schema/` | Generated JSON Schemas |

The skill is MIT licensed. SimpleDiagrams and its built-in shapes have separate licenses.
