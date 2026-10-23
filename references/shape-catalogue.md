# Search the packaged shapes

The skill knows the shapes packaged with SimpleDiagrams 5.1.0: 534 shapes in
eight libraries, including the 89 shapes of BPMN and the 8 of UML. They are
listed in `assets/built-in-shapes.json`, with names, descriptions, keywords,
natural sizes and exact placement references. Search it through the CLI instead
of reading the full JSON into conversation. The search makes no network request.

```sh
uv run "$SKILL_DIR/scripts/find_shapes.py" currency --json
uv run "$SKILL_DIR/scripts/find_shapes.py" --library biz
uv run "$SKILL_DIR/scripts/find_shapes.py" database --json
```

Results include `selector`, the exact `reference`, and `connection_points`:
`"standard"` for the app's eight (0 left, 1 right, 2 top, 3 bottom at the
middle of each side, then 4 top left, 5 bottom left, 6 top right, 7 bottom
right), or the shape's own list of `id`, `x` and `y` as fractions of its frame.
The text listing prints a shape's own points as `points: id (x, y)`. An edge
names one with `source_point` or `target_point`.
Searches match every query word across names, descriptions and keywords.
Results default to 30; use `--offset` and `--limit` (at most 300) for more.
Library selectors accept a short name or the full library ID.

## Placement

Every result can be placed by its `selector`, which the builder writes as the
shape's exact `reference`: the app's own library ID, item ID and asset version.
Item IDs are case sensitive (`3DBasicHatch/Burst` and `3DBasicHatch/burst` are
different shapes). These are the only library shapes the skill knows; shapes
from libraries downloaded from simplediagrams.com cannot be placed. When no
packaged shape fits, use a labelled native `rectangle`, `ellipse` or `note`.

A packaged shape's connection points and label placement come from the list,
as the app gives them to a shape dragged from its Library panel. Some packaged
shapes have no connection points at all (BPMN's task marks, which sit on a
task); the builder refuses a connector to one, naming the shape. A name the app
centres below a narrow shape, wider than it (a BPMN event, the UML Actor), is
written as the app writes it. The UML Fork / Join Bar keeps its thickness: give
it a `width` or `scale`, never a `height`.

BPMN's plain Task and Gateway are Basic shapes, as in the app's BPMN section:
`basic/rounded-rectangle` at 98 by 64 and `basic/Diamond` at 50 by 50 with its
name below. BPMN's flows and UML's relationships are connector settings, not
shapes; SKILL.md lists them.

## Shapes SimpleDiagrams draws itself

Containers, swimlanes, tables, callouts and UML lifelines are not in the list:
SimpleDiagrams draws them from a few settings, and a spec names them by kind
(`"shape": "table"`) with their own fields, as SKILL.md describes. They cover
BPMN's Pool and Expanded Sub-Process and UML's Class, Interface, Enumeration,
Database Entity, System Boundary, Lifeline, Actor Lifeline, Frame and Alt, Loop
and Opt fragments. A search with a word such as `pool`, `lane`, `class`,
`entity`, `lifeline` or `fragment` adds a line naming the kind to use
(`complex_shapes` in `--json` output).
