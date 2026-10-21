"""封存域的具體型別與 JSON 邊界；不使用 Any 或未驗證的強制轉型。"""
from dataclasses import dataclass
from typing import Literal, TypedDict, cast
from uuid import UUID
from runtime.budget_types import integer, object_fields

SealState = Literal["AVAILABLE", "RESERVED", "CONSUMED", "RETIRED"]
TokenKind = Literal["CONTENT", "LINEAGE"]


class SealRejected(ValueError):
    """只攜穩定遮罩代碼；不可把 token／觀測／底層例外輸出至公有 API。"""
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def text(value: object) -> str:
    """明確拒絕數字或容器冒充字串，避免 str() 隱藏契約錯誤。"""
    if not isinstance(value,str):
        raise SealRejected("INVALID_SCHEMA")
    return value


def sequence(value: object) -> list[object]:
    """只在檢查 list 後收斂元素為 object，後續仍需逐欄驗證。"""
    if not isinstance(value,list):
        raise SealRejected("INVALID_SCHEMA")
    return cast(list[object],value)


def uuid_text(value: object) -> str:
    """以標準 UUID 字串固定引用，排除任意路徑及不等價的拼寫。"""
    raw = text(value)
    if str(UUID(raw)) != raw:
        raise SealRejected("INVALID_SCHEMA")
    return raw


class JournalEntry(TypedDict):
    """單一不可變 authority 事件；payload 不能包含 final labels。"""
    epoch: str
    sequence: int
    previous_hash: str
    payload: dict[str,object]
    signature: str
    entry_hash: str


def entry_from(value: object) -> JournalEntry:
    """檢查 RPC 事件形狀；簽章由獨立 authority 驗證，客戶端再驗鏈。"""
    row = object_fields(value)
    if set(row) != {"epoch","sequence","previous_hash","payload","signature","entry_hash"}:
        raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
    return {"epoch":uuid_text(row["epoch"]),"sequence":integer(row["sequence"]),"previous_hash":text(row["previous_hash"]),
            "payload":object_fields(row["payload"]),"signature":text(row["signature"]),"entry_hash":text(row["entry_hash"])}


@dataclass(frozen=True)
class Attestation:
    """可以進公開 DB 的不透明登記；不攜私有 token、labels 或檔案位置。"""
    sealed_test_id: str
    source_sha256: str
    protocol_hash: str
    authority_epoch: str
    authority_sequence: int
    attestation_hash: str

    def document(self) -> dict[str,object]:
        """只回固定白名單，避免把 authority 的完整私有文件直接投影。"""
        return {"sealed_test_id":self.sealed_test_id,"source_sha256":self.source_sha256,"protocol_hash":self.protocol_hash,
                "authority_epoch":self.authority_epoch,"authority_sequence":self.authority_sequence,"attestation_hash":self.attestation_hash}

    @classmethod
    def read(cls, value: object) -> "Attestation":
        """工作程序內部傳遞仍驗型別與必要欄位，不相信任意 child 多出欄位。"""
        row = object_fields(value)
        if set(row) != {"sealed_test_id","source_sha256","protocol_hash","authority_epoch","authority_sequence","attestation_hash"}:
            raise SealRejected("INVALID_SCHEMA")
        return cls(uuid_text(row["sealed_test_id"]),text(row["source_sha256"]),text(row["protocol_hash"]),uuid_text(row["authority_epoch"]),integer(row["authority_sequence"]),text(row["attestation_hash"]))
