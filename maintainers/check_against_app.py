# /// script
# requires-python = ">=3.10"
# dependencies = ["pydantic>=2.7,<3"]
# ///
"""Checks what the skill writes against SimpleDiagrams for Mac's own reader. For maintainers.

The skill's tests compare it with its own models, so they can all pass while the app refuses
what it writes. This shows the app's reader, compiled by `app_reader.swift` from a copy of the
app's source, the bundled examples, the test fixtures and every kind of complex shape in many
settings. The run fails when:

- the app refuses a document the skill accepted;
- the app accepts one built over a limit the skill must keep, which would mean a limit here
  is stricter than it needs to be or no longer the app's;
- a shape that places its own connection points has other points in the app than the builder
  works out, or has them elsewhere, since a connector is stored ending at those places.

Needs macOS, Swift 6.1 or later and a copy of the app's source, such as one exported from the
release tag. The build fetches the one package the reader depends on, at the version the app
pins, from GitHub; nothing else uses the network. Nothing is written inside the app's source
or the skill: the build and the documents go to `--work-dir`, or to a new temporary folder
removed afterwards.

    uv run maintainers/check_against_app.py --app-source PATH [--work-dir DIR]
"""

from __future__ import annotations

import sys

# Set before the skill's own files are loaded below, so none leaves a compiled cache.
sys.dont_write_bytecode = True

import argparse
import itertools
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from pydantic import ValidationError

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / "scripts"), str(ROOT / "tests")]

import fixtures
import sd_format as wire
from sd_package import write_package
from sd_spec import DiagramSpec, compile_spec, load_spec

# Marks a work folder as this tool's, so that a folder holding anything else is never reused.
WORK_MARKER = ".simplediagrams-diagram-check"
# How far apart, in points, the builder's place for a connection point and the app's may be.
POINT_TOLERANCE = 0.01
SPEC_ID = "11111111-2222-4333-8444-555555555555"


def build_reader(app_source: Path, work: Path) -> Path:
    """Compiles `app_reader.swift` against the app's reader and returns the program."""
    core = app_source / "Sources" / "SimpleDiagramsCore"
    if not core.is_dir():
        raise SystemExit(f"{app_source} does not look like the SimpleDiagrams for Mac source")
    pins = json.loads((app_source / "Package.resolved").read_text(encoding="utf-8"))["pins"]
    pin = next(pin for pin in pins if pin["identity"] == "zipfoundation")
    package = work / "reader"
    sources = package / "Sources"
    (sources / "AppReader").mkdir(parents=True, exist_ok=True)
    (package / "Package.swift").write_text(
        f"""// swift-tools-version: 6.1
import PackageDescription

let package = Package(
  name: "AppReader",
  platforms: [.macOS(.v15)],
  dependencies: [
    .package(url: "{pin['location']}", revision: "{pin['state']['revision']}"),
  ],
  targets: [
    .target(
      name: "SimpleDiagramsCore",
      dependencies: [.product(name: "ZIPFoundation", package: "ZIPFoundation")],
      resources: [.process("Resources/Localizable.xcstrings")]),
    .executableTarget(name: "AppReader", dependencies: ["SimpleDiagramsCore"]),
  ]
)
""",
        encoding="utf-8",
    )
    link = sources / "SimpleDiagramsCore"
    if link.is_symlink() or link.exists():
        link.unlink()
    link.symlink_to(core, target_is_directory=True)
    shutil.copyfile(Path(__file__).with_name("app_reader.swift"), sources / "AppReader" / "main.swift")
    print("Building the app's reader (a few minutes the first time)...", flush=True)
    result = subprocess.run(
        ["swift", "build", "-c", "release", "--package-path", str(package)],
        capture_output=True, text=True, check=False,
    )  # fmt: skip
    if result.returncode != 0:
        raise SystemExit("The reader did not build:\n" + (result.stdout + result.stderr)[-4000:])
    return package / ".build" / "release" / "AppReader"


def every_kind_in_many_settings() -> list[dict]:
    """Nodes covering every setting of the kinds that place their own points."""
    nodes: list[dict] = []

    def add(**node: object) -> None:
        nodes.append({"key": f"n{len(nodes)}", "x": 100 + len(nodes) * 10, "y": 100, **node})

    for base, spacing, pointer, direction, count, (width, height) in itertools.product(
        wire.FLOW_BASE_SHAPES, ("gap", "touch", "overlap"), (False, True), ("across", "down"), (2, 3, 7),
        ((360, 80), (500, 140), (120, 300)),
    ):
        plain = base in ("rectangle", "rounded_rectangle", "circle")
        if (plain or (spacing != "overlap" and not pointer)) and (height if direction == "down" else width) >= 16 * count:
            add(
                shape="flow", base_shape=base, spacing=spacing, pointer=pointer, direction=direction,
                steps=[f"s{index}" for index in range(count)], width=width, height=height,
            )
    for count, band, (width, height) in itertools.product(
        (1, 2, 3, 5, 12, 20), (40, 10, 500, "full"), ((200, 200), (400, 200), (100, 300))
    ):
        add(shape="ring", sections=[f"s{index}" for index in range(count)], ring_width=band, width=width, height=height)
    # Rings whose sections hold shares: touching, some thin, some leaving a piece missing.
    for shares, band, (width, height) in itertools.product(
        ((100,), (40, 35, 25), (30, None, None), (3, None, 95), (50, 2, 2, 2), (1, 1, 1), (60, None), (5,) * 20),
        (40, 10, "full"), ((200, 200), (400, 200), (60, 60)),
    ):
        sections = [{"label": f"s{index}", **({"share": share} if share else {})} for index, share in enumerate(shares)]
        add(shape="ring", sections=sections, ring_width=band, width=width, height=height)
    for groups, (width, height) in itertools.product(
        ((1,), (50, 30, 20), (1000,), (1,) * 20), ((240, 140), (500, 140), (100, 300), (48, 28))
    ):
        add(shape="audience", groups=list(groups), width=width, height=height)
    # Gantt charts: short and long plans, weekends skipped or not, milestones at either end,
    # tasks that follow a named task, at several sizes; each picks its own axis step.
    plans = (
        [[{"label": "a", "start": "2026-11-09", "days": 5}]],
        [[{"label": "a", "start": "2026-11-13", "days": 1}, {"label": "m", "milestone": True}, {"label": "b", "days": 3}]],
        [
            [{"label": "m", "start": "2026-11-14", "milestone": True}, {"label": "a", "key": "a", "days": 12}],
            [{"label": "b", "after": "a", "days": 40}, {"label": "c", "start": "2026-10-01", "days": 7}, {"label": "d", "days": 90}],
        ],
        [[{"label": "a", "start": "2024-02-28", "days": 400}, {"label": "b", "days": 1200}, {"label": "c", "days": 3650}]],
        [[{"label": f"t{index}", **({"start": "1999-12-30"} if index == 0 else {}), "days": 1 + index % 9} for index in range(60)]],
    )
    for plan, skip, (width, height) in itertools.product(
        plans, (False, True), ((480, 220), (200, 800), (900, 300), (1600, 1000))
    ):
        tasks = sum(len(section) for section in plan)
        if height >= wire.gantt_smallest_size(tasks)[1]:
            add(
                shape="gantt", label="G", skip_weekends=skip, width=width, height=height,
                plan=[{"label": f"s{index}", "tasks": section} for index, section in enumerate(plan)],
            )
    for count, form, (width, height) in itertools.product((2, 3, 8), ("pyramid", "funnel"), ((240, 200), (600, 80), (50, 400))):
        if height >= 12 * count:
            add(shape="pyramid", form=form, layers=[f"l{index}" for index in range(count)], width=width, height=height)
    for count, band, style, direction, (width, height) in itertools.product(
        (3, 4, 8), (50, 10, 900), ("arrow", "chevron"), ("clockwise", "anticlockwise"), ((240, 240), (500, 240), (60, 60))
    ):
        add(
            shape="cycle", steps=[f"s{index}" for index in range(count)], ring_width=band, arrow_style=style,
            direction=direction, width=width, height=height,
        )
    for count, (width, height) in itertools.product((1, 3, 5), ((200, 140), (500, 140), (100, 300))):
        add(shape="gauge", bands=[f"b{index}" for index in range(count)], label="c", width=width, height=height)
    for count in (1, 2, 9):
        fields = [{"name": f"f{index}", "type": "t", "marks": ["primary_key"] if index == 0 else []} for index in range(count)]
        add(shape="entity_table", label="E", fields=fields)
        add(shape="entity_table", label="E", fields=[{"name": "two\nlines"}, *fields], width=300, height=400)
    return nodes


def over_the_limits() -> dict[str, dict]:
    """The JSON of documents past a limit or breaking a rule, which the models would refuse
    and the app must too."""
    made: dict[str, dict] = {}
    base = wire.dump(fixtures.complex_profile_document())
    plain = wire.dump(fixtures.full_profile_document())

    def changed(change, source: dict = base) -> dict:
        document = json.loads(json.dumps(source))
        change(document["pages"][0]["elements"])
        return document

    def changed_connection(change) -> dict:
        document = json.loads(json.dumps(plain))
        change(document["pages"][0]["content"]["content"]["connections"][0])
        return document

    def element(elements: list, number: int) -> dict:
        """The first level of the element the fixtures number `number`."""
        return next(
            item for item in elements if item["content"]["content"]["content"]["id"].endswith(f"{number:012X}")
        )["content"]

    def task(elements: list, place: int) -> dict:
        return [part for part in of(elements, "gantt")["parts"] if part["role"] == "task"][place]

    def of(elements: list, kind: str) -> dict:
        return next(item for item in elements if item.get("complex_shape", {}).get("type") == kind)["complex_shape"]

    made["lane title over 1,000"] = changed(lambda elements: of(elements, "swimlanes")["parts"][0]["text"].update(string="L" * 1001))
    made["cell over 2,000"] = changed(lambda elements: of(elements, "table")["parts"][-1]["cells"][0].update(string="x" * 2001))
    made["section over 500"] = changed(lambda elements: of(elements, "ring")["parts"][0]["text"].update(string="x" * 501))
    made["an empty part style"] = changed(lambda elements: of(elements, "ring")["parts"][1].update(style={}))
    made["a chevron with a pointer"] = changed(
        lambda elements: of(elements, "flow")["settings"].update(base_shape="chevron")
    )
    made["a null part style"] = changed(lambda elements: of(elements, "ring")["parts"][1].update(style=None))

    def one_shape_in_two_lanes(elements: list) -> None:
        lanes = of(elements, "swimlanes")["parts"]
        lanes[1]["members"] = list(lanes[0]["members"])

    def turned_proportional(elements: list) -> None:
        holder = next(
            item for item in elements if item.get("complex_shape", {}).get("settings", {}).get("layout") == "proportional"
        )
        holder["content"]["content"]["content"]["rotation_degrees"] = 30

    made["one shape in two lanes"] = changed(one_shape_in_two_lanes)
    made["a turned proportional container"] = changed(turned_proportional)
    # What document formats 20 and 21 added.
    made["a table without uml_box"] = changed(lambda elements: of(elements, "table")["settings"].pop("uml_box"))
    made["a table with an unknown uml_box"] = changed(lambda elements: of(elements, "table")["settings"].update(uml_box="record"))
    made["a ring's shares over 100"] = changed(lambda elements: of(elements, "ring")["parts"][1].update(size=71))
    made["a ring's share that is not whole"] = changed(lambda elements: of(elements, "ring")["parts"][0].update(size=30.5))
    made["an audience of 1,001 seats"] = changed(lambda elements: of(elements, "audience")["parts"][0].update(size=971))
    made["an audience's group with words"] = changed(
        lambda elements: of(elements, "audience")["parts"][0].update(text=of(elements, "ring")["parts"][0]["text"])
    )
    made["a Gantt chart whose sections' sizes do not add up"] = changed(
        lambda elements: of(elements, "gantt")["parts"][0].update(size=3)
    )
    made["a task with a start and an after"] = changed(lambda elements: task(elements, 2).update(start="2026-11-20"))
    made["a milestone with a length"] = changed(lambda elements: task(elements, 3).update(size=2))
    made["a task without a length"] = changed(lambda elements: task(elements, 1).pop("size"))
    made["a task after itself through another"] = changed(
        lambda elements: task(elements, 0).update(after=[task(elements, 2)["id"]]) or task(elements, 0).pop("start")
    )
    made["a task after a section"] = changed(
        lambda elements: task(elements, 2).update(after=[of(elements, "gantt")["parts"][0]["id"]])
    )
    made["a task marked active"] = changed(lambda elements: task(elements, 1).update(marks=["active"]))
    made["a start that is not a real day"] = changed(lambda elements: task(elements, 0).update(start="2026-02-30"))
    made["a task ending after 2199"] = changed(lambda elements: task(elements, 0).update(start="2199-12-30"))
    made["a first task without a start"] = changed(lambda elements: task(elements, 0).pop("start"))
    made["a list at level 4"] = changed(
        lambda elements: element(elements, 7)["content"]["content"]["text_content"]["paragraph_runs"][0]["list"].update(level=4),
        plain,
    )
    made["a list of an unknown kind"] = changed(
        lambda elements: element(elements, 7)["content"]["content"]["text_content"]["paragraph_runs"][0]["list"].update(kind="dash"),
        plain,
    )
    made["a collapsed rectangle"] = changed(lambda elements: element(elements, 2).update(collapsed=True), plain)
    made["an end label of 201 characters"] = changed_connection(
        lambda connection: connection["end_label"]["content"].update(string="x" * 201)
    )
    made["an end label at a negative distance"] = changed_connection(
        lambda connection: connection["end_label"].update(distance=-1)
    )
    return made


def read(reader: Path, paths: list[Path]) -> dict[str, dict]:
    result = subprocess.run([str(reader), *map(str, paths)], capture_output=True, text=True, check=True)
    reports = [json.loads(line) for line in result.stdout.splitlines()]
    return {report["path"]: report for report in reports}


def write(document: wire.Document, target: Path) -> Path:
    if target.exists():
        shutil.rmtree(target)
    return write_package(document, target)


def check(reader: Path, work: Path) -> list[str]:
    """Every disagreement between what the skill writes and what the app reads."""
    documents = work / "documents"
    documents.mkdir(exist_ok=True)
    built: dict[Path, wire.Document] = {}
    for spec in sorted((ROOT / "assets").glob("example*-spec.json")):
        built[documents / f"{spec.stem}.simplediagram"] = compile_spec(load_spec(spec))
    built[documents / "full-profile.simplediagram"] = fixtures.full_profile_document()
    built[documents / "complex-profile.simplediagram"] = fixtures.complex_profile_document()
    nodes = every_kind_in_many_settings()
    pages = [{"nodes": nodes[start : start + 200]} for start in range(0, len(nodes), 200)]
    built[documents / "many-settings.simplediagram"] = compile_spec(
        DiagramSpec.model_validate({"name": "Many", "id": SPEC_ID, "pages": pages})
    )
    for target, document in built.items():
        write(document, target)

    problems: list[str] = []
    reports = read(reader, list(built))
    compared = 0
    for target, document in built.items():
        report = reports[str(target)]
        if report.get("error"):
            problems.append(f"{target.name}: the app refuses it: {report['error']}")
            continue
        for page in document.pages:
            for element in page.elements:
                shape = element.complex_shape
                if shape is None or shape.own_point_ids is None:
                    continue
                frame = element.core.frame
                ours = wire.shape_points(shape, frame.width, frame.height)
                theirs = report["points"][element.core.id]
                if {str(point) for point in ours} != set(theirs):
                    problems.append(f"{target.name}: a {shape.type} has points {sorted(theirs)} in the app, {sorted(ours)} here")
                    continue
                for point, (x, y) in ours.items():
                    compared += 1
                    other_x, other_y = theirs[str(point)]
                    if max(abs(x - other_x) * frame.width, abs(y - other_y) * frame.height) > POINT_TOLERANCE:
                        problems.append(f"{target.name}: a {shape.type}'s point {point} is at {(x, y)} here, {(other_x, other_y)} in the app")

    # A document over a limit goes through the raw JSON, past the models that would refuse it.
    limits = over_the_limits()
    raw: dict[Path, str] = {}
    for index, (what, document) in enumerate(limits.items()):
        target = documents / f"over-{index}.simplediagram"
        write(fixtures.minimal_document(), target)
        (target / "document.json").write_text(json.dumps(document), encoding="utf-8")
        raw[target] = what
    reports = read(reader, list(raw))
    for target, what in raw.items():
        if not reports[str(target)].get("error"):
            problems.append(f"The app opens a document with {what}, which the skill refuses")
    for what, document in limits.items():
        try:
            wire.Document.model_validate_json(json.dumps(document))
            problems.append(f"The models accept a document with {what}, which the app refuses")
        except ValidationError:
            pass
    print(f"{len(built)} documents opened; {compared} connection points compared; {len(raw)} over a limit refused by both.")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--app-source", type=Path, required=True, help="A copy of the app's source")
    parser.add_argument("--work-dir", type=Path, help="Keeps the build here between runs")
    arguments = parser.parse_args()
    temporary = None
    if arguments.work_dir:
        work = arguments.work_dir
        if work.exists() and any(work.iterdir()) and not (work / WORK_MARKER).exists():
            raise SystemExit(f"{work} holds other files; choose an empty folder")
        work.mkdir(parents=True, exist_ok=True)
        (work / WORK_MARKER).touch()
    else:
        temporary = tempfile.TemporaryDirectory()
        work = Path(temporary.name)
    try:
        problems = check(build_reader(arguments.app_source.resolve(), work), work)
    finally:
        if temporary:
            temporary.cleanup()
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
