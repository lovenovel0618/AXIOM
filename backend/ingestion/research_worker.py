"""Fixed research entry point; raw data never appears on stdout or stderr."""
import json
from pathlib import Path
import sys


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ingestion.limits import ImportLimits, ImportRejected
    from ingestion.worker import configure
    limits = ImportLimits(**json.loads(sys.argv[2]))
    configure(limits.max_parse_seconds)
    try:
        from ingestion.research import inspect_file
        config = json.loads(Path("request").read_bytes())
        result = {"status": "PASS", "report": inspect_file(Path("input"), sys.argv[1], limits, config)}
    except ImportRejected as error:
        result = {"status": "REJECTED", "code": error.code}
    except MemoryError:
        result = {"status": "REJECTED", "code": "IMPORT_LIMIT_EXCEEDED"}
    except Exception:
        result = {"status": "REJECTED", "code": "DEPENDENCY_UNAVAILABLE"}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
