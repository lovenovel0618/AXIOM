"""獨立曝光 authority：只追加、先 fsync，再確認；checkpoint 可偵測歷史截短。"""
from contextlib import contextmanager
from collections.abc import Generator
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
from secrets import token_bytes
from uuid import uuid4
from runtime.contracts import canonical_bytes, identity_hash, validate
from runtime.budget_types import integer, object_fields
from sealing.types import JournalEntry, SealRejected, entry_from, text

MAX_JOURNAL = 1024*1024
ZERO_HASH = "0"*64


def durable_file(path: Path, value: bytes) -> None:
    """原子替換 checkpoint／私有檔；先 fsync 檔案，再 fsync 目錄。"""
    temporary = path.with_name(".pending-"+uuid4().hex)
    descriptor = os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    try:
        with os.fdopen(descriptor,"wb") as target:
            target.write(value)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary,path)
        directory = os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def checked_payload(value: object) -> dict[str,object]:
    """只允許無 labels 的控制 intent；不能把原始數列寫進 journal。"""
    row = object_fields(value)
    action = text(row.get("action"))
    common = {"action","operation_id"}
    shapes = {"INIT":{"key_fingerprint"},"REGISTER":{"sealed","blob_sha256","blob_size"},
              "RESERVE":{"tenant_id","sealed_test_id","submission_id","snapshot_hash"},
              "CONSUME":{"tenant_id","sealed_test_id","submission_id","snapshot_hash"},
              "RETIRE":{"tenant_id","sealed_test_id","submission_id","snapshot_hash"}}
    if action not in shapes or set(row) != common|shapes[action]:
        raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
    text(row["operation_id"])
    if action == "REGISTER":
        validate(row["sealed"],"research-v2.schema.json","SealedTest")
        integer(row["blob_size"])
        text(row["blob_sha256"])
    return row


class JournalStore:
    """僅 authority 程序持有檔案與簽章金鑰；RPC writer 沒有刪除／截短能力。"""
    def __init__(self, directory: Path, checkpoint: Path) -> None:
        self.directory,self.checkpoint = directory,checkpoint
        for path in (directory,checkpoint):
            path.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.path = directory/"events.jsonl"
        self.marker = checkpoint/"authority.json"
        self.key_path = checkpoint/"signing.key"
        with self.locked():
            if not self.key_path.exists():
                if self.marker.exists() or self.path.exists():
                    raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
                durable_file(self.key_path,token_bytes(32))
                durable_file(self.marker,canonical_bytes({"epoch":str(uuid4()),"sequence":0,"entry_hash":ZERO_HASH}))
            self.key = self.key_path.read_bytes()
            if len(self.key)!=32 or not self.marker.is_file():
                raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
            self._read()

    @contextmanager
    def locked(self) -> Generator[None]:
        """跨程序序列化 append／checkpoint，並行 writer 不能共用同一序號。"""
        descriptor = os.open(self.directory/"authority.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(descriptor,fcntl.LOCK_EX)
            yield
        finally:
            os.close(descriptor)

    def _read(self) -> list[JournalEntry]:
        """每次取得目前完整鏈，不接受備份快取水位或未結束的半行。"""
        marker = object_fields(json.loads(self.marker.read_bytes()))
        epoch,checkpoint_sequence = text(marker["epoch"]),integer(marker["sequence"])
        data = self.path.read_bytes() if self.path.exists() else b""
        if len(data)>MAX_JOURNAL or (data and not data.endswith(b'\n')):
            raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
        entries: list[JournalEntry] = []
        previous = ZERO_HASH
        for raw in data.splitlines():
            entry = entry_from(json.loads(raw))
            unsigned = {name:entry[name] for name in ("epoch","sequence","previous_hash","payload")}
            signature = hmac.new(self.key,canonical_bytes(unsigned),hashlib.sha256).hexdigest()
            digest = identity_hash(dict(unsigned,signature=entry["signature"]))
            if entry["epoch"]!=epoch or entry["sequence"]!=len(entries)+1 or entry["previous_hash"]!=previous or not hmac.compare_digest(signature,entry["signature"]) or digest!=entry["entry_hash"]:
                raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
            checked_payload(entry["payload"])
            entries.append(entry)
            previous = digest
        checkpoint_hash: str | None = None
        if checkpoint_sequence==0:
            checkpoint_hash = ZERO_HASH
        elif checkpoint_sequence<=len(entries):
            checkpoint_hash = entries[checkpoint_sequence-1]["entry_hash"]
        if checkpoint_hash != marker["entry_hash"]:
            raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
        if checkpoint_sequence<len(entries):
            durable_file(self.marker,canonical_bytes({"epoch":epoch,"sequence":len(entries),"entry_hash":previous}))
        return entries

    def read(self) -> list[JournalEntry]:
        """只有通過簽章、連續鏈及獨立 checkpoint 的事件才可供重播。"""
        with self.locked():
            return self._read()

    def append(self, payload: dict[str,object], expected: int) -> JournalEntry:
        """先耐久保存 intent；相同操作內容冪等，過時水位或衝突內容拒絕。"""
        checked_payload(payload)
        with self.locked():
            entries = self._read()
            for entry in entries:
                if entry["payload"]["operation_id"]==payload["operation_id"]:
                    if entry["payload"]!=payload:
                        raise SealRejected("INVALID_TRANSITION")
                    return entry
            if expected!=len(entries):
                raise SealRejected("REQUEST_IN_PROGRESS")
            marker = object_fields(json.loads(self.marker.read_bytes()))
            unsigned = {"epoch":text(marker["epoch"]),"sequence":len(entries)+1,"previous_hash":text(marker["entry_hash"]),"payload":payload}
            signature = hmac.new(self.key,canonical_bytes(unsigned),hashlib.sha256).hexdigest()
            signed = dict(unsigned,signature=signature)
            entry = entry_from(dict(signed,entry_hash=identity_hash(signed)))
            raw = canonical_bytes(entry)+b'\n'
            if self.path.exists() and self.path.stat().st_size+len(raw)>MAX_JOURNAL:
                raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
            descriptor = os.open(self.path,os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW,0o600)
            with os.fdopen(descriptor,"ab") as target:
                target.write(raw)
                target.flush()
                os.fsync(target.fileno())
            durable_file(self.marker,canonical_bytes({"epoch":entry["epoch"],"sequence":entry["sequence"],"entry_hash":entry["entry_hash"]}))
            return entry
