"""Trusted synthetic canary reader executed under the actual probe UID."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path


def effective_capabilities() -> int:
    for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
        if line.startswith("CapEff:"):
            return int(line.split(":", 1)[1].strip(), 16)
    raise ValueError("Effective capabilities unavailable")


def file_access(path: Path) -> tuple[str, str | None]:
    try:
        content = path.read_bytes()
        return "ALLOWED", hashlib.sha256(content).hexdigest()
    except PermissionError:
        return "DENIED", None
    except OSError:
        return "ERROR", None


def directory_access(path: Path) -> str:
    try:
        list(path.iterdir())
        return "ALLOWED"
    except PermissionError:
        return "DENIED"
    except OSError:
        return "ERROR"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", type=Path, required=True)
    parser.add_argument("--sealed", type=Path, required=True)
    parser.add_argument("--expected-uid", type=int, required=True)
    parser.add_argument("--role", choices=("solver", "evaluator"), required=True)
    args = parser.parse_args()
    public_access, _ = file_access(args.public)
    sealed_access, digest = file_access(args.sealed)
    listing = directory_access(args.sealed.parent)
    identity = os.geteuid() == args.expected_uid
    capabilities = effective_capabilities()
    expected_access = "DENIED" if args.role == "solver" else "ALLOWED"
    passed = identity and capabilities == 0 and public_access == "ALLOWED"
    passed = passed and sealed_access == expected_access and listing == expected_access
    report = {
        "uid": os.geteuid(), "gid": os.getegid(), "effective_capabilities": capabilities,
        "identity_verified": identity, "public_access": public_access,
        "sealed_access": sealed_access, "directory_access": listing, "sealed_digest": digest,
    }
    print(json.dumps(report))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
