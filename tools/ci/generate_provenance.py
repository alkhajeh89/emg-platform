#!/usr/bin/env python3
"""Generate deterministic local SLSA-compatible provenance metadata."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("subjects", nargs="+", type=Path)
    args = parser.parse_args()
    subjects = [
        {
            "name": subject.name,
            "digest": {"sha256": hashlib.sha256(subject.read_bytes()).hexdigest()},
        }
        for subject in sorted(args.subjects)
    ]
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": subjects,
        "predicateType": "https://slsa.dev/provenance/v1",
        "predicate": {
            "buildDefinition": {
                "buildType": "https://github.com/emg-platform/reproducible-release/v1",
                "externalParameters": {"gitRef": args.ref},
                "resolvedDependencies": [
                    {
                        "uri": f"git+https://github.com/{args.repository}",
                        "digest": {"gitCommit": args.commit},
                    }
                ],
            },
            "runDetails": {"builder": {"id": "https://github.com/actions/runner"}},
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(statement, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
