"""Real UID canary checks in disposable Linux containers, not product ACL acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import secrets
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any, cast

JsonObject = dict[str, Any]  # Child JSON process boundary.
SOLVER_UID = 10001
EVALUATOR_UID = 10002
CHILD = Path(__file__).with_name("access_child.py")


def run_child(public: Path, sealed: Path, uid: int, role: str, expected_uid: int | None = None) -> JsonObject:
    command = [sys.executable, str(CHILD), "--public", str(public), "--sealed", str(sealed),
               "--expected-uid", str(expected_uid if expected_uid is not None else uid), "--role", role]
    completed = subprocess.run(
        command, user=uid, group=uid, extra_groups=[], cwd=public.parent,
        env={"LANG": "C.UTF-8"}, capture_output=True, text=True, timeout=10, check=False,
    )
    value: object = json.loads(completed.stdout)
    if not isinstance(value, dict):
        raise ValueError("Child did not return an object")
    result = cast(JsonObject, value).copy()
    result["exit_code"] = completed.returncode
    return result


def valid_identity(result: JsonObject, uid: int) -> bool:
    expected = {"uid": uid, "gid": uid, "effective_capabilities": 0, "exit_code": 0}
    return all(type(result.get(key)) is int and result[key] == value for key, value in expected.items())


def solver_isolated(result: JsonObject) -> bool:
    return all((
        valid_identity(result, SOLVER_UID), result.get("identity_verified") is True, result.get("public_access") == "ALLOWED",
        result.get("sealed_access") == "DENIED", result.get("directory_access") == "DENIED",
        result.get("sealed_digest") is None,
    ))


def evaluator_authorized(result: JsonObject, digest: str) -> bool:
    return all((
        valid_identity(result, EVALUATOR_UID), result.get("identity_verified") is True, result.get("public_access") == "ALLOWED",
        result.get("sealed_access") == "ALLOWED", result.get("directory_access") == "ALLOWED",
        result.get("sealed_digest") == digest,
    ))


def prepare_workspace(root: Path) -> tuple[Path, Path, str]:
    root.chmod(0o755)
    public = root / "solver.json"
    public.write_text(json.dumps({"scope": "SYNTHETIC_PROJECTION_CANARY",
                                  "fit": [{"row_id": 0, "x": 0, "y": 1}],
                                  "development": [{"row_id": 1, "x": 1, "y": 3}]}), encoding="utf-8")
    public.chmod(0o444)
    sealed_directory = root / "sealed"
    sealed_directory.mkdir(mode=0o700)
    sealed = sealed_directory / "canary.bin"
    content = secrets.token_bytes(32)
    sealed.write_bytes(content)
    sealed.chmod(0o600)
    os.chown(sealed, EVALUATOR_UID, EVALUATOR_UID)
    os.chown(sealed_directory, EVALUATOR_UID, EVALUATOR_UID)
    return public, sealed, hashlib.sha256(content).hexdigest()


def sanitized_result(result: JsonObject) -> JsonObject:
    allowed = {"uid", "gid", "effective_capabilities", "identity_verified", "public_access",
               "sealed_access", "directory_access", "exit_code"}
    return {key: result[key] for key in allowed if key in result}


def exercise_isolation(root: Path) -> JsonObject:
    public, sealed, digest = prepare_workspace(root)
    solver = run_child(public, sealed, SOLVER_UID, "solver")
    evaluator = run_child(public, sealed, EVALUATOR_UID, "evaluator")
    wrong_identity = run_child(public, sealed, SOLVER_UID, "solver", expected_uid=EVALUATOR_UID)
    sealed.parent.chmod(0o755)
    sealed.chmod(0o644)
    leaky = run_child(public, sealed, SOLVER_UID, "solver")
    sealed.unlink()
    missing = run_child(public, sealed, SOLVER_UID, "solver")
    negative_controls = {
        "wrong_identity_detected": not solver_isolated(wrong_identity) and wrong_identity["identity_verified"] is False,
        "insecure_permissions_detected": not solver_isolated(leaky) and leaky["sealed_access"] == "ALLOWED",
        "missing_file_not_accepted_as_denial": not solver_isolated(missing) and missing["sealed_access"] == "ERROR",
    }
    passed = solver_isolated(solver) and evaluator_authorized(evaluator, digest) and all(negative_controls.values())
    return {"status": "PASS" if passed else "FAIL", "solver": sanitized_result(solver),
            "evaluator": sanitized_result(evaluator), "negative_controls": negative_controls}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report: JsonObject = {
        "scope": "POSIX_FILE_ACCESS_PROBE_ONLY", "product_status": "NOT_RUN",
        "platform": platform.system(), "machine": platform.machine(), "python": platform.python_version(), "status": "NOT_RUN",
    }
    if platform.system() == "Linux" and os.geteuid() == 0:
        try:
            with TemporaryDirectory(prefix="axiom-t03-") as temporary:
                report.update(exercise_isolation(Path(temporary)))
        except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
            report.update(status="FAIL", error=type(error).__name__)
    else:
        report["reason"] = "Requires a disposable Linux container with UID setup permission"
    serialized = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    if report["status"] == "NOT_RUN":
        return 2
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
