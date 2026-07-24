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

    deps = data.get("project", {}).get("dependencies", [])

    result = set()

    for dep in deps:
        name = dep.split(">")[0].split("=")[0].split("<")[0].strip()

        if name.startswith("emg-"):
            result.add(name)

    return result


def main():
    manifest = ROOT / "docker" / "dependencies.yaml"

    print(f"Reading manifest: {manifest}")

    data = yaml.safe_load(manifest.read_text())

    print(data.keys())

    if "services" not in data:
        print("❌ Manifest missing services section")
        sys.exit(1)

    failed = False

    for name, service in data["services"].items():

        service_path = ROOT / service["path"]

        pyproject = service_path / "pyproject.toml"

        if not pyproject.exists():
            print(f"⚪ {name}: no pyproject.toml")
            continue

        actual = get_pyproject_dependencies(pyproject)
        declared = set(service.get("dependencies", []))

        missing = actual - declared

        if missing:
            print(f"❌ {name}: missing in manifest")

            for item in sorted(missing):
                print(f"   - {item}")

            failed = True
        else:
            print(f"✅ {name}: dependencies aligned")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
