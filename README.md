# Build SimpleDiagrams diagrams

This Agent Skill creates new editable `.simplediagram` documents from a description or from an image of a diagram. It uses the shapes packaged with SimpleDiagrams and a small JSON spec for nodes, labels, positions and connectors. The builder writes the document package and checks its structure and layout.

It writes document format 18, which needs SimpleDiagrams 5.1.0 or later for macOS. The skill carries the list of the 534 shapes packaged with SimpleDiagrams 5.1.0, in eight libraries, and makes no network request. Searching and building need Python 3.10+ and Pydantic 2; `uv run` may download Pydantic when it is not cached. Download it only with uv 0.13.4 or later, or pip 26.2.2 or later: older versions still trust the certificate authority withdrawn after the October 2026 eMudhra (emSign) certificate incident, so a download could be tampered with.

See the [privacy policy](PRIVACY.md) for how the skill and your chosen AI application handle data.

## Install

In Claude Code:

```bash
claude plugin marketplace add mcquilleninteractive/simplediagrams-diagram-skill
claude plugin install simplediagrams-diagram-skill@simplediagrams
```

In Codex, paste this into a chat:

```text
$skill-installer Install the skill from https://github.com/mcquilleninteractive/simplediagrams-diagram-skill (the repository root), named simplediagrams-diagram-skill.
```

Then ask Codex to use `simplediagrams-diagram-skill` with a request like the examples below. If the skill does not appear after installation, restart Codex. See the [Codex skill installation documentation](https://learn.chatgpt.com/docs/build-skills#install-curated-skills-for-local-use).

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

- Creates new documents using native rectangles, ellipses, notes, text, connectors, and the eight bundled shape libraries, BPMN and UML included. A library shape gets the connection points and label placement its library gives it, as in the app.
- Draws the complex shapes SimpleDiagrams draws itself: containers fitted around the shapes they hold, swimlanes and BPMN pools with members in each lane, tables such as UML class, interface, enumeration and entity boxes, callouts whose tails lock to a shape, and UML sequence diagrams with lifelines, messages attached along them, destroy marks, frames and alt, loop and opt fragments.
- Searches the packaged shapes by name, description and keyword, and places each by the app's own reference. Shapes from downloadable or personal libraries, embedded images and shape data are outside this authoring profile.
- Redraws a pictured diagram as boxes and connectors. It does not trace artwork or handwriting or embed the picture. A connector can attach to any connection point a shape has.
- Never overwrites an existing document. Keep the JSON spec to rebuild under a new name.
- The scripts make no network request and store nothing between runs; the AI service running the skill handles your files under its own policies.

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
| `references/shape-catalogue.md` | Searching and placing the packaged shapes |
| `references/document-format.md` | Generated package structure |
| `assets/built-in-shapes.json` | The 534 packaged shapes, with their connection points and label placement |
| `assets/example-spec.json` | Example input |
| `assets/example-bpmn-spec.json`, `assets/example-sequence-spec.json`, `assets/example-class-spec.json` | Examples with complex shapes: a BPMN pool with lanes, a UML sequence diagram, UML classes as tables |
| `scripts/find_shapes.py` | Search the packaged shapes' names, descriptions and keywords |
| `scripts/build_diagram.py` | Check a spec and build a new package |
| `scripts/preview_diagram.py` | Render a new wireframe SVG from a spec |
| `scripts/sd_spec.py`, `scripts/sd_format.py`, `scripts/sd_package.py` | Spec compiler, format models, and package writer (checked in memory before writing) |
| `schema/` | Generated JSON Schemas |

The skill is MIT licensed. SimpleDiagrams and its built-in shapes have separate licenses.
