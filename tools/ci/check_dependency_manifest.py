import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
_COPY_PACKAGE = re.compile(r"^COPY\s+libs/python/(emg-[A-Za-z0-9-]+)\s", re.MULTILINE)
_INSTALL_PACKAGE = re.compile(r"/build/libs/python/(emg-[A-Za-z0-9-]+)(?:\s|\\|$)")


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


def internal_dependency_closure(manifest: dict, component_name: str) -> set[str]:
    """Resolve the recursively required internal distributions for a component.

    Manifest entries continue to describe direct dependencies. This resolver is
    used only at the production-image boundary, where ``pip --no-deps`` requires
    every transitive internal distribution to be copied and installed explicitly.
    """
    components = manifest.get("services", {})
    pending = list(components[component_name].get("dependencies", []))
    closure: set[str] = set()
    while pending:
        dependency = pending.pop()
        if not dependency.startswith("emg-") or dependency in closure:
            continue
        closure.add(dependency)
        dependency_name = dependency.removeprefix("emg-")
        dependency_component = components.get(dependency_name)
        if dependency_component is None:
            raise ValueError(
                f"{component_name}: internal dependency {dependency} is not registered"
            )
        pending.extend(dependency_component.get("dependencies", []))
    return closure


def check_component(
    name: str, component: dict, root: Path = ROOT, manifest: dict | None = None
) -> bool:

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

    if component.get("type") == "deployment-tool":
        for dependency in component.get("dependencies", []):
            if f"libs/python/{dependency}" not in content:
                print(f"❌ {name}: missing {dependency}")
                success = False
        return success

    required = (
        internal_dependency_closure(manifest, name)
        if manifest is not None
        else set(component.get("dependencies", []))
    )
    copied = set(_COPY_PACKAGE.findall(content))
    installed = set(_INSTALL_PACKAGE.findall(content))

    for dependency in sorted(required - copied):
        print(f"❌ {name}: Dockerfile does not copy {dependency}")
        success = False
    for dependency in sorted(required - installed):
        print(f"❌ {name}: Dockerfile does not install {dependency}")
        success = False

    return success


def main() -> None:

    manifest = load_manifest()

    if "services" not in manifest:
        print("❌ Invalid dependency manifest: missing services section")
        sys.exit(1)

    failed = not check_production_service_coverage(manifest)

    for name, component in manifest["services"].items():

        if not check_component(name, component, manifest=manifest):
            failed = True

    if failed:
        sys.exit(1)

    print("✅ Dependency manifest validation passed")


if __name__ == "__main__":
    main()
