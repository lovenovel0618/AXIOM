"""固定解析 child 入口：先設定 Linux 資源限制，再解析暫存檔並輸出有界 metadata。

Fixed isolated entry point; bootstrap resource limits before parser imports."""
import json
import os
from pathlib import Path
import resource
import sys

MEMORY_BYTES = 1024 * 1024 * 1024


def configure(seconds: int, file_bytes: int = 0) -> None:
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (seconds + 1, seconds + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (file_bytes, file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    os.umask(0o077)


def main() -> None:
    # -I excludes environment paths; only this repository's fixed parent is added.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from ingestion.limits import ImportLimits, ImportRejected
    limits = ImportLimits(**json.loads(sys.argv[2]))
    configure(limits.max_parse_seconds)
    try:
        from ingestion.parser import parse
        result = {"status": "PASS", "metadata": parse(Path("input"), sys.argv[1], limits)}
    except ImportRejected as error:
        result = {"status": "REJECTED", "code": error.code}
    except MemoryError:
        result = {"status": "REJECTED", "code": "IMPORT_LIMIT_EXCEEDED"}
    except Exception:
        # Native parser failures are sanitized; no raw input or exception text leaves.
        result = {"status": "REJECTED", "code": "INVALID_SCHEMA"}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))


if __name__ == "__main__":
    main()
