#!/usr/bin/env python3
"""Rebuild plugin.zip/checksum.sha256 per plugin and regenerate index.json.

Usage: scripts/build_index.py [--check] [plugin-name ...]

--check: verify manifest.json matches src/init.lua and exit non-zero on
         mismatch, without writing anything (used by the PR validation job).
Without --check: rebuild build/plugin.zip + build/checksum.sha256 for the
         given plugins (or all of them) and regenerate index.json.
"""
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"
INDEX_PATH = REPO_ROOT / "index.json"
SCHEMA_VERSION = 1

REQUIRED_MANIFEST_FIELDS = {"name", "version", "author", "description", "permissions"}


def discover_plugins():
    if not PLUGINS_DIR.is_dir():
        return []
    return sorted(p.name for p in PLUGINS_DIR.iterdir() if p.is_dir())


def safe_plugin_dir(name: str) -> Path:
    """Resolve a plugin name to a directory guaranteed to live inside plugins/."""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        raise ValueError(f"invalid plugin name: {name!r}")
    plugin_dir = (PLUGINS_DIR / name).resolve()
    if plugin_dir.parent != PLUGINS_DIR.resolve():
        raise ValueError(f"plugin dir escapes plugins/: {name!r}")
    return plugin_dir


def load_manifest(plugin_dir: Path) -> dict:
    manifest_path = plugin_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"{plugin_dir.name}: missing manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    missing = REQUIRED_MANIFEST_FIELDS - manifest.keys()
    if missing:
        raise ValueError(f"{plugin_dir.name}: manifest.json missing fields {sorted(missing)}")
    return manifest


def extract_lua_field(src: str, field: str):
    """Best-effort regex extraction of M.<field> = ... from init.lua.

    Read-only text matching — init.lua is never executed as Lua code.
    """
    if field == "permissions":
        m = re.search(r"M\.permissions\s*=\s*\{([^}]*)\}", src)
        if not m:
            return []
        return [a or b for a, b in re.findall(r'"([^"]+)"|\'([^\']+)\'', m.group(1))]
    m = re.search(rf'M\.{field}\s*=\s*"([^"]*)"', src)
    return m.group(1) if m else None


def check_manifest_matches_lua(plugin_dir: Path, manifest: dict):
    init_lua_path = plugin_dir / "src" / "init.lua"
    if not init_lua_path.is_file():
        raise ValueError(f"{plugin_dir.name}: missing src/init.lua")
    src = init_lua_path.read_text(encoding="utf-8")

    for field in ("name", "version"):
        lua_value = extract_lua_field(src, field)
        if lua_value != manifest[field]:
            raise ValueError(
                f"{plugin_dir.name}: manifest.json {field}={manifest[field]!r} "
                f"!= init.lua M.{field}={lua_value!r}"
            )

    lua_permissions = sorted(extract_lua_field(src, "permissions") or [])
    manifest_permissions = sorted(manifest.get("permissions") or [])
    if lua_permissions != manifest_permissions:
        raise ValueError(
            f"{plugin_dir.name}: manifest.json permissions={manifest_permissions} "
            f"!= init.lua M.permissions={lua_permissions}"
        )


def iter_src_files(src_dir: Path):
    """Yield (absolute_path, arcname) pairs, rejecting anything outside src_dir."""
    src_dir_resolved = src_dir.resolve()
    for path in sorted(src_dir.rglob("*")):
        if not path.is_file():
            continue
        resolved = path.resolve()
        if src_dir_resolved not in resolved.parents:
            # Defends against symlinks pointing outside the plugin's src/.
            raise ValueError(f"refusing to package file outside src/: {path}")
        arcname = resolved.relative_to(src_dir_resolved).as_posix()
        yield resolved, arcname


def build_zip(plugin_dir: Path) -> Path:
    src_dir = plugin_dir / "src"
    if not src_dir.is_dir():
        raise ValueError(f"{plugin_dir.name}: missing src/ directory")

    build_dir = plugin_dir / "build"
    build_dir.mkdir(exist_ok=True)
    zip_path = build_dir / "plugin.zip"

    # Deterministic zip: fixed file order, fixed timestamp, no extra metadata.
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for abs_path, arcname in iter_src_files(src_dir):
            info = zipfile.ZipInfo(arcname, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, abs_path.read_bytes())

    return zip_path


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def process_plugin(name: str, check_only: bool) -> dict:
    plugin_dir = safe_plugin_dir(name)
    manifest = load_manifest(plugin_dir)
    check_manifest_matches_lua(plugin_dir, manifest)

    if check_only:
        return manifest

    zip_path = build_zip(plugin_dir)
    checksum = sha256_of(zip_path)
    (plugin_dir / "build" / "checksum.sha256").write_text(checksum + "\n", encoding="utf-8")

    return {
        **manifest,
        "zip_path": zip_path,
        "sha256": checksum,
        "size_bytes": zip_path.stat().st_size,
    }


def zip_url_for(name: str) -> str:
    org_repo = "REPLACE_ME/terminalis-plugins"
    return f"https://raw.githubusercontent.com/{org_repo}/main/plugins/{name}/build/plugin.zip"


def write_index(entries: list[dict]):
    index = {
        "schema_version": SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "plugins": [
            {
                "name": e["name"],
                "version": e["version"],
                "author": e["author"],
                "description": e["description"],
                "permissions": e["permissions"],
                "zip_url": zip_url_for(e["name"]),
                "sha256": e["sha256"],
                "size_bytes": e["size_bytes"],
            }
            for e in entries
        ],
    }
    INDEX_PATH.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str]) -> int:
    check_only = "--check" in argv
    names = [a for a in argv if a != "--check"] or discover_plugins()

    try:
        entries = [process_plugin(name, check_only) for name in names]
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not check_only:
        write_index(entries)
        print(f"rebuilt {len(entries)} plugin(s), wrote index.json")
    else:
        print(f"checked {len(entries)} plugin(s), all manifests match init.lua")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
