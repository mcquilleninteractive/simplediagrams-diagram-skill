# Local processing and credentials

The diagram builder, shape search and SVG preview scripts run locally. They do
not make network requests, read credentials, send email or upload user files.
They read the supplied spec and bundled catalogue, and write only the requested
new document or preview. Dependency installation through uv or pip may access
the package index; it is separate from diagram processing. The AI service
running the skill handles prompts and supplied files under its own policies.

## Plugin submission review

A non-executable entry can be mistaken for a credential-to-network path:

- `assets/built-in-shapes.json` contains `mail` search keywords for shapes.
  This is catalogue data, not an email command or network operation.

The plugin manifest declares metadata only: no MCP servers, hooks or commands
that read credentials or transmit data. The catalogue is loaded as JSON data;
its names and keywords are never executed. `tests/test_catalog.py` checks that
the runtime scripts do not import networking modules. Maintainer tests include
synthetic credential strings to check that accidental secrets are rejected.

If a submission review cites these entries, request review of the actual
executable paths. Do not remove credential exclusions or legitimate catalogue
entries merely to silence a text-based warning.

## Listing icon

`.claude-plugin/icon.png` is the existing SimpleDiagrams product logo, copied
unchanged from the macOS application's artwork. It is a 1024 by 1024 PNG under
2 MB. This exact path is the sole binary-image exception to publication hygiene
checks; user-supplied images remain excluded.
