import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib
import yaml

ROOT = Path(__file__).parents[2]


def get_pyproject_dependencies(path: Path):
    data = tomllib.loads(path.read_text())

    deps = data.get("project", {}).get("dependencies", [])

    result = []

    for dep in deps:
        name = dep.split(">")[0].split("=")[0].split("<")[0].strip()
        if name.startswith("emg-"):
            result.append(name)

    return set(result)


def main():
    manifest = ROOT / "docker" / "dependencies.yaml"

    data = yaml.safe_load(manifest.read_text())

    failed = False

    for name, service in data["components"].items():

        path = ROOT / service["path"]

        pyproject = path / "pyproject.toml"

        if not pyproject.exists():
            continue

        declared = set(service.get("dependencies", []))
        actual = get_pyproject_dependencies(pyproject)

        missing = actual - declared

        if missing:
            print(f"❌ {name}: missing dependencies in manifest:")
            for item in sorted(missing):
                print(f"   - {item}")
            failed = True

        else:
            print(f"✅ {name}: dependencies aligned")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
