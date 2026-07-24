import re
import sys
from pathlib import Path

import yaml

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


ROOT = Path(__file__).parents[2]
INTERNAL_DEPENDENCY = re.compile(r"^(emg-[A-Za-z0-9-]+)")


def get_pyproject_dependencies(path: Path) -> set[str]:
    data = tomllib.loads(path.read_text())
    dependencies = data.get("project", {}).get("dependencies", [])
    return {
        match.group(1)
        for dependency in dependencies
        if (match := INTERNAL_DEPENDENCY.match(dependency.strip()))
    }


def get_dockerfile_dependencies(path: Path) -> set[str]:
    return {
        dependency
        for line in path.read_text().splitlines()
        if line.lstrip().upper().startswith("COPY ")
        for dependency in re.findall(r"\blibs/python/(emg-[A-Za-z0-9-]+)\b", line)
    }


def report_missing(service: str, location: str, dependencies: set[str]) -> bool:
    if not dependencies:
        return False

    print(f"❌ {service}: missing from {location}")
    for dependency in sorted(dependencies):
        print(f"   - {dependency}")
    return True


def main() -> None:
    manifest = ROOT / "docker" / "dependencies.yaml"
    print(f"Reading manifest: {manifest}")
    data = yaml.safe_load(manifest.read_text())

    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        print("❌ Invalid dependency manifest: missing services section")
        sys.exit(1)

    failed = False

    for name, service in data["services"].items():
        if service.get("type") != "service":
            continue

        pyproject = ROOT / service["path"] / "pyproject.toml"
        dockerfile_value = service.get("dockerfile")

        if not pyproject.exists():
            print(f"❌ {name}: pyproject.toml not found: {pyproject}")
            failed = True
            continue

        if not dockerfile_value:
            print(f"❌ {name}: missing dockerfile entry in manifest")
            failed = True
            continue

        dockerfile = ROOT / dockerfile_value
        if not dockerfile.is_file():
            print(f"❌ {name}: Dockerfile not found: {dockerfile}")
            failed = True
            continue

        manifest_dependencies = {
            dependency
            for dependency in service.get("dependencies", [])
            if dependency.startswith("emg-")
        }
        pyproject_dependencies = get_pyproject_dependencies(pyproject)
        dockerfile_dependencies = get_dockerfile_dependencies(dockerfile)

        service_failed = any(
            (
                report_missing(name, "manifest", pyproject_dependencies - manifest_dependencies),
                report_missing(
                    name,
                    "pyproject.toml",
                    manifest_dependencies - pyproject_dependencies,
                ),
                report_missing(
                    name,
                    "Dockerfile COPY declarations",
                    manifest_dependencies - dockerfile_dependencies,
                ),
                report_missing(name, "manifest", dockerfile_dependencies - manifest_dependencies),
            )
        )
        failed = failed or service_failed

        if not service_failed:
            print(f"✅ {name}: dependencies aligned")

    if failed:
        sys.exit(1)

    print("✅ Dependency drift check passed")


if __name__ == "__main__":
    main()
