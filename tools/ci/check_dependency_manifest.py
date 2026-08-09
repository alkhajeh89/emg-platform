import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def load_manifest(root: Path = ROOT) -> dict:
    with open(root / "docker/dependencies.yaml") as manifest_file:
        return yaml.safe_load(manifest_file)


def discover_production_services(root: Path = ROOT) -> set[str]:
    """Find deployable service directories governed by this manifest."""
    services: set[str] = set()
    for parent_name in ("services", "apps"):
        parent = root / parent_name
        if not parent.exists():
            continue
        for component_dir in parent.iterdir():
            if (component_dir / "service.yaml").is_file() and (
                component_dir / "Dockerfile"
            ).is_file():
                services.add(component_dir.relative_to(root).as_posix())
    return services


def check_production_service_coverage(manifest: dict, root: Path = ROOT) -> bool:
    registered = {
        component.get("path"): (name, component)
        for name, component in manifest.get("services", {}).items()
        if component.get("type") == "service"
    }
    success = True
    for service_path in sorted(discover_production_services(root)):
        registration = registered.get(service_path)
        if registration is None:
            print(f"❌ Unregistered production service: {service_path}")
            success = False
            continue
        name, component = registration
        expected_dockerfile = f"{service_path}/Dockerfile"
        if component.get("dockerfile") != expected_dockerfile:
            print(f"❌ {name}: Dockerfile registration must be {expected_dockerfile}")
            success = False
    return success


def check_component(name: str, component: dict, root: Path = ROOT) -> bool:

    # Libraries do not have Dockerfiles
    if component.get("type") == "library":
        return True

    dockerfile_value = component.get("dockerfile")

    if not dockerfile_value:
        print(f"❌ {name}: missing dockerfile entry")
        return False

    dockerfile = root / dockerfile_value

    if not dockerfile.exists():
        print(f"❌ {name}: Dockerfile not found: {dockerfile}")
        return False

    if dockerfile.is_dir():
        print(f"❌ {name}: Dockerfile path is a directory")
        return False

    content = dockerfile.read_text()

    success = True

    for dependency in component.get("dependencies", []):

        expected = f"libs/python/{dependency}"

        if expected not in content:
            print(f"❌ {name}: missing {dependency}")
            success = False

    return success


def main() -> None:

    manifest = load_manifest()

    if "services" not in manifest:
        print("❌ Invalid dependency manifest: missing services section")
        sys.exit(1)

    failed = not check_production_service_coverage(manifest)

    for name, component in manifest["services"].items():

        if not check_component(name, component):
            failed = True

    if failed:
        sys.exit(1)

    print("✅ Dependency manifest validation passed")


if __name__ == "__main__":
    main()
