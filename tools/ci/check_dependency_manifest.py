import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]


def load_manifest():

    with open(ROOT / "docker/dependencies.yaml") as f:
        return yaml.safe_load(f)


def check_component(name, component):

    # Libraries do not have Dockerfiles
    if component.get("type") == "library":
        return True

    dockerfile_value = component.get("dockerfile")

    if not dockerfile_value:
        print(f"❌ {name}: missing dockerfile entry")
        return False

    dockerfile = ROOT / dockerfile_value

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


def main():

    manifest = load_manifest()

    failed = False

    for name, component in manifest["services"].items():

        if not check_component(name, component):
            failed = True

    if failed:
        sys.exit(1)

    print("✅ Dependency manifest validation passed")


if __name__ == "__main__":
    main()
