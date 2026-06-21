"""从 pyproject.toml 自动生成 requirements.txt。

用法:
    python -m scripts.sync_requirements
    # 或安装后: sync-requirements

规则:
    - pyproject.toml 是依赖的唯一源
    - requirements.txt 由本脚本自动生成，请勿手动编辑
    - 核心依赖直接输出，optional-dependencies 以注释分组
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:
        print("Error: Python >= 3.11 or `tomli` package required", file=sys.stderr)
        sys.exit(1)


BACKEND_DIR = Path(__file__).resolve().parent.parent
PYPROJECT_PATH = BACKEND_DIR / "pyproject.toml"
REQUIREMENTS_PATH = BACKEND_DIR / "requirements.txt"

HEADER = (
    "# Auto-generated from pyproject.toml — do NOT edit manually.\n"
    "# To update: edit pyproject.toml, then run:\n"
    "#   python -m scripts.sync_requirements\n"
)


def main() -> None:
    with open(PYPROJECT_PATH, "rb") as f:
        data = tomllib.load(f)

    deps = data["project"]["dependencies"]
    optional = data["project"].get("optional-dependencies", {})

    lines = [HEADER]
    for d in sorted(deps):
        lines.append(d)

    for group, items in optional.items():
        lines.append(f"\n# [{group}]")
        for d in sorted(items):
            lines.append(d)

    lines.append("")  # trailing newline

    content = "\n".join(lines)

    # Only write if changed (avoid unnecessary file timestamp bump)
    if REQUIREMENTS_PATH.exists():
        existing = REQUIREMENTS_PATH.read_text(encoding="utf-8")
        if existing == content:
            print("requirements.txt is already up-to-date — no changes.")
            return

    REQUIREMENTS_PATH.write_text(content, encoding="utf-8")
    print(f"requirements.txt synced from pyproject.toml ({len(deps)} core deps).")


if __name__ == "__main__":
    main()
