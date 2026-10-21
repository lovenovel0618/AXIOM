"""封存專用固定 child；只向 stdout 回校驗資料，labels 留在 private 暫存檔。"""
import hashlib
import json
from pathlib import Path
import sys

MAX_PAYLOAD = 524288


def main() -> None:
    """先設 Linux 上限；僅允許有限 private payload 檔，例外永遠遮罩。"""
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
    from ingestion.limits import ImportLimits
    from ingestion.worker import configure
    from runtime.budget_types import object_fields
    limits = ImportLimits(**json.loads(sys.argv[2]))
    configure(limits.max_parse_seconds,file_bytes=MAX_PAYLOAD)
    try:
        from sealing.prepare import private_payload
        content = private_payload(Path('input'),sys.argv[1],limits,object_fields(json.loads(Path('request').read_bytes())))
        Path('sealed_payload').write_bytes(content)
        Path('sealed_payload').chmod(0o400)
        result: dict[str,object] = {'status':'PASS','sha256':hashlib.sha256(content).hexdigest(),'size_bytes':len(content)}
    except Exception:
        result = {'status':'REJECTED','code':'DEPENDENCY_UNAVAILABLE'}
    print(json.dumps(result,allow_nan=False))


if __name__=='__main__':
    main()
