import json
import re
from pathlib import Path

ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
SEMVER_PATTERN = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+([+-][a-zA-Z0-9.-]+)?$")
ENTRYPOINT_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._+-]*$")


def test_openhop_manifest_conformance():
    manifest_path = Path("openhop-plugin.json")
    assert manifest_path.is_file(), "openhop-plugin.json must exist"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Schema must be integer 1
    assert manifest.get("schema") == 1

    # ID validation
    plugin_id = manifest.get("id")
    assert isinstance(plugin_id, str)
    assert ID_PATTERN.match(plugin_id)
    assert ".." not in plugin_id
    assert "/" not in plugin_id
    assert "\\" not in plugin_id

    # Name validation
    name = manifest.get("name")
    assert isinstance(name, str) and len(name) > 0

    # Version validation
    version = manifest.get("version")
    assert isinstance(version, str)
    assert SEMVER_PATTERN.match(version)

    # Runtime validation
    runtime = manifest.get("runtime")
    assert isinstance(runtime, dict)
    assert runtime.get("type") == "python"
    entrypoint = runtime.get("entrypoint")
    assert isinstance(entrypoint, str)
    assert ENTRYPOINT_PATTERN.match(entrypoint)
    assert ":" not in entrypoint, "entrypoint must be a bare console script name, not module:callable"

    # UI validation
    ui = manifest.get("ui")
    assert isinstance(ui, dict)
    assert ui.get("type") == "application"
    entry = ui.get("entry")
    assert isinstance(entry, str)
    assert entry.startswith("ui/"), "UI entry must be located under dedicated ui/ subtree"
    assert not entry.startswith("/"), "UI entry must be a relative path"

    # Config validation
    config = manifest.get("config")
    assert isinstance(config, dict)
    defaults = config.get("defaults")
    assert isinstance(defaults, dict)
    assert "poll_interval_seconds" in defaults
    assert "meshcore_channel_idx" in defaults
