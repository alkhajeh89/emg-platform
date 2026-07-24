import sys
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import yaml

ROOT = Path(__file__).parents[2]


def load_pyproject_dependencies(path: Path):
    data = tomllib.loads(path.read_text())

    dependencies = data.get("project", {}).get("dependencies", [])

    result = set()

    for dependency in dependencies:
        package = dependency.split(">")[0].split("=")[0].split("<")[0].strip()

        if package.startswith("emg-"):
            result.add(package)

    return result


def main():
    manifest_path = ROOT / "docker" / "dependencies.yaml"

    if not manifest_path.exists():
        print("❌ docker/dependencies.yaml not found")
        sys.exit(1)

    data = yaml.safe_load(manifest_path.read_text())
    print("Loaded manifest:")
    print(data)

    # Support both:
    # services:
    #   identity:
    #       ...
    #
    # and direct root mapping
    services = data.get("services", data)

    failed = False

    for name, service in services.items():

        service_path = ROOT / service.get("path", "")

        pyproject = service_path / "pyproject.toml"

        # Skip services without pyproject
        if not pyproject.exists():
            print(f"⚠️ {name}: no pyproject.toml found, skipped")
            continue

        manifest_dependencies = set(service.get("dependencies", []))

        project_dependencies = load_pyproject_dependencies(pyproject)

        missing = project_dependencies - manifest_dependencies

        if missing:
            print(f"❌ {name}: missing dependencies in docker/dependencies.yaml:")

            for dependency in sorted(missing):
                print(f"   - {dependency}")

            failed = True

        else:
            print(f"✅ {name}: dependencies aligned")

    if failed:
        sys.exit(1)

    print("\n✅ Dependency drift validation passed")


if __name__ == "__main__":
    main()
