from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PLUGIN_ROOT / "dist"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Package tracked plugin files into an AstrBot local-install zip.",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output zip path. Defaults to dist/<plugin-name>-<version>.zip.",
    )
    args = parser.parse_args()

    output_path = args.output or default_output_path()
    package_plugin(output_path)
    print(output_path)
    return 0


def default_output_path() -> Path:
    plugin_name, version = read_metadata_name_and_version()
    safe_version = version.replace("/", "-").replace("\\", "-")
    return DEFAULT_OUTPUT_DIR / f"{plugin_name}-{safe_version}.zip"


def read_metadata_name_and_version() -> tuple[str, str]:
    metadata_path = PLUGIN_ROOT / "metadata.yaml"
    name = ""
    version = ""
    for line in metadata_path.read_text(encoding="utf-8").splitlines():
        line = line.lstrip("\ufeff")
        if line.startswith("name:"):
            name = line.split(":", 1)[1].strip().split("#", 1)[0].strip()
        elif line.startswith("version:"):
            version = line.split(":", 1)[1].strip().split("#", 1)[0].strip()
    if not name or not version:
        raise RuntimeError("metadata.yaml must contain name and version.")
    return name, version


def package_plugin(output_path: Path) -> Path:
    tracked_files = list_tracked_files()
    if not tracked_files:
        raise RuntimeError("No git tracked files found.")

    plugin_name, _ = read_metadata_name_and_version()
    package_root = plugin_name.strip().strip("/\\")
    if not package_root:
        raise RuntimeError("metadata.yaml must contain a valid plugin name.")

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # AstrBot v4.22.x expects the first zip entry to be a directory.
        zf.writestr(f"{package_root}/", "")
        for relative_path in tracked_files:
            source_path = PLUGIN_ROOT / relative_path
            if not source_path.is_file():
                continue
            archive_name = f"{package_root}/{relative_path.as_posix()}"
            zf.write(source_path, archive_name)
    return output_path


def list_tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PLUGIN_ROOT,
        check=True,
        capture_output=True,
    )
    paths = [Path(item.decode("utf-8")) for item in result.stdout.split(b"\0") if item]
    return sorted(paths, key=lambda path: path.as_posix())


if __name__ == "__main__":
    raise SystemExit(main())
