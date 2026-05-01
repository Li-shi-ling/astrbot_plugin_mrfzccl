from __future__ import annotations

import argparse
import subprocess
import zipfile
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PLUGIN_ROOT / "dist"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将已跟踪的插件文件打包为 AstrBot 本地安装 zip。",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="输出 zip 路径，默认使用 dist/<插件名>-<版本号>.zip。",
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
        raise RuntimeError("metadata.yaml 必须包含 name 和 version 字段。")
    return name, version


def package_plugin(output_path: Path) -> Path:
    tracked_files = list_tracked_files()
    if not tracked_files:
        raise RuntimeError("未找到任何 Git 已跟踪文件。")

    plugin_name, _ = read_metadata_name_and_version()
    package_root = plugin_name.strip().strip("/\\")
    if not package_root:
        raise RuntimeError("metadata.yaml 中的插件名无效。")

    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # AstrBot v4.22.x 要求 zip 的第一项是目录。
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
