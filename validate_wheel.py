"""Wheel validation script checking openHop Repeater packaging contracts."""

import glob
import json
import sys
from pathlib import Path
from zipfile import ZipFile


def validate() -> None:
    wheels = glob.glob("dist/openhop_apcups_plugin-*.whl")
    if not wheels:
        print("ERROR: No wheel found in dist/. Run 'python -m build --wheel' first.")
        sys.exit(1)

    wheel_path = Path(wheels[0])
    print(f"Validating {wheel_path.name} against openHop Repeater contracts...")

    with ZipFile(wheel_path) as archive:
        names = archive.namelist()

        # 1. Check entry points
        entry_points_files = [n for n in names if n.endswith("entry_points.txt")]
        assert entry_points_files, "Missing entry_points.txt"
        ep_content = archive.read(entry_points_files[0]).decode("utf-8")
        assert "openhop-apc-ups = openhop_apc_ups.main:main" in ep_content, "Missing console script entrypoint"
        print("  [PASS] Console script entry point verified")

        # 2. Check openhop-plugin.json location
        manifest_files = [n for n in names if n.endswith("openhop-plugin.json")]
        assert manifest_files, "Missing openhop-plugin.json in wheel"
        expected_manifest_suffix = "share/openhop/plugins/openhop.apcups/openhop-plugin.json"
        assert any(n.replace("\\", "/").endswith(expected_manifest_suffix) for n in manifest_files), (
            f"Manifest not in expected share data path: {manifest_files}"
        )
        print("  [PASS] Data share path for manifest verified")

        # 3. Check manifest content
        manifest_data = json.loads(archive.read(manifest_files[0]).decode("utf-8"))
        assert manifest_data.get("schema") == 1
        assert manifest_data.get("id") == "openhop.apcups"
        assert manifest_data.get("runtime", {}).get("entrypoint") == "openhop-apc-ups"
        assert manifest_data.get("ui", {}).get("entry") == "ui/index.html"
        print("  [PASS] Manifest schema and runtime/ui configuration verified")

        # 4. Check UI assets
        ui_assets = [n for n in names if "/ui/" in n.replace("\\", "/")]
        assert any(n.endswith("index.html") for n in ui_assets), "Missing ui/index.html"
        assert any(n.endswith("app.js") for n in ui_assets), "Missing ui/app.js"
        assert any(n.endswith("styles.css") for n in ui_assets), "Missing ui/styles.css"
        print("  [PASS] UI assets bundle verified")

        # 5. Check Python package modules
        pkg_files = [n for n in names if n.startswith("openhop_apc_ups/")]
        assert any(n.endswith("__init__.py") for n in pkg_files)
        assert any(n.endswith("main.py") for n in pkg_files)
        print("  [PASS] Python package code verified")

    print(f"\nALL CHECKS PASSED: {wheel_path.name} is a valid openHop Repeater plugin wheel!")


if __name__ == "__main__":
    validate()
