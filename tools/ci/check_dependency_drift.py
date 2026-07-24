import sys
from pathlib import Path

import yaml

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


ROOT = Path(__file__).parents[2]


def get_pyproject_dependencies(path: Path):
    data = tomllib.loads(path.read_text())

    dependencies = data.get("project", {}).get("dependencies", [])

    result = set()

    for dep in dependencies:
        name = dep.split(">")[0].split("=")[0].split("<")[0].strip()

        if name.startswith("emg-"):
            result.add(name)

    return result


def main():

    manifest = ROOT / "docker" / "dependencies.yaml"

    with manifest.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not data or "services" not in data:
        print("❌ Invalid dependency manifest format")
        sys.exit(1)

    failed = False

    for name, service in data["services"].items():

        path = ROOT / service["path"]

        pyproject = path / "pyproject.toml"

        if not pyproject.exists():
            continue

        declared = set(service.get("dependencies", []))

        actual = get_pyproject_dependencies(pyproject)

        missing = actual - declared

        if missing:
            print(f"❌ {name}: missing dependencies:")
            for item in sorted(missing):
                print(f"   - {item}")

            failed = True

        else:
            print(f"✅ {name}: dependencies aligned")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
