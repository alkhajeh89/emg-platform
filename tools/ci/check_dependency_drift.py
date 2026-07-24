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

    dependencies = data.get("project", {}).get("dependencies", [])

    result = set()

    for dependency in dependencies:
        name = dependency.split(">")[0].split("=")[0].split("<")[0].strip()

        if name.startswith("emg-"):
            result.add(name)

    return result


def main():

    manifest_path = ROOT / "docker" / "dependencies.yaml"

    if not manifest_path.exists():
        print("❌ Missing docker/dependencies.yaml")
        sys.exit(1)

    data = yaml.safe_load(manifest_path.read_text())

    if not data or "services" not in data:
        print("❌ Invalid dependency manifest: missing services section")
        sys.exit(1)

    failed = False

    for service_name, service in data["services"].items():

        service_path = ROOT / service.get("path", "")

        pyproject = service_path / "pyproject.toml"

        # Skip services without pyproject
        if not pyproject.exists():
            print(f"⚪ {service_name}: no pyproject.toml (skipped)")
            continue

        declared = set(service.get("dependencies", []))

        actual = get_pyproject_dependencies(pyproject)

        missing = actual - declared

        if missing:
            print(f"❌ {service_name}: missing dependencies in manifest:")

            for dependency in sorted(missing):
                print(f"   - {dependency}")

            failed = True

        else:
            print(f"✅ {service_name}: dependencies aligned")

    if failed:
        sys.exit(1)

    print("\n✅ Dependency drift check passed")


if __name__ == "__main__":
    main()
