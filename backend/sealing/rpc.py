"""Evaluator 專用 journal RPC；私有 Unix socket 上的有界長度前綴 JSON 交換。"""
from typing import Protocol
import json
import socket
import struct
from runtime.budget_types import object_fields
from runtime.contracts import canonical_bytes
from sealing.types import JournalEntry, SealRejected, entry_from, sequence

MAX_FRAME = 262144


class Journal(Protocol):
    """僅讀目前權威歷史與追加 intent；沒有更新／刪除介面。"""
    def read(self) -> list[JournalEntry]: ...
    def append(self, payload: dict[str,object], expected: int) -> JournalEntry: ...


def receive_frame(connection: socket.socket) -> dict[str,object]:
    """讀入有界長度前綴的 JSON 物件；超界、截斷或格式錯誤一律拒絕。"""
    size = struct.unpack("!I",receive_exactly(connection,4))[0]
    if not 1<=size<=MAX_FRAME:
        raise SealRejected("INVALID_SCHEMA")
    return object_fields(json.loads(receive_exactly(connection,size)))


def send_frame(connection: socket.socket, value: object) -> None:
    """只送出有界 canonical JSON；不夾帶例外、路徑或 journal 原文。"""
    content = canonical_bytes(value)
    if len(content)>MAX_FRAME:
        raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
    connection.sendall(struct.pack("!I",len(content))+content)


def receive_exactly(connection: socket.socket, size: int) -> bytes:
    """在串流上收滿固定長度；對方提早關閉視為格式錯誤而非空內容。"""
    buffer = bytearray()
    while len(buffer)<size:
        chunk = connection.recv(size-len(buffer))
        if not chunk:
            raise SealRejected("INVALID_SCHEMA")
        buffer.extend(chunk)
    return bytes(buffer)


class JournalClient:
    """以私有 Unix socket 存取 authority；連線不確定視為隔離，不降級為只寫 DB。"""
    def __init__(self, path: str, token: str) -> None:
        if not path.startswith("/") or len(token)<32:
            raise SealRejected("EXPOSURE_RECOVERY_BLOCKED")
        self.path,self.token = path,token

    def request(self, message: dict[str,object]) -> dict[str,object]:
        """每次重建連線；逾時、截斷或非 JSON 回應都遮罩為隔離失敗。"""
        try:
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
                connection.settimeout(5)
                connection.connect(self.path)
                send_frame(connection,dict(message,token=self.token))
                return receive_frame(connection)
        except (OSError,ValueError) as error:
            raise SealRejected("EXPOSURE_RECOVERY_BLOCKED") from error

    def read(self) -> list[JournalEntry]:
        """取得當前完整權威鏈，由 vault 檢查序號、epoch 及重播水位。"""
        return [entry_from(value) for value in sequence(self.request({"op":"read"}).get("entries"))]

    def append(self, payload: dict[str,object], expected: int) -> JournalEntry:
        """journal 回應遺失也不假設 intent 未寫入；下一次先重播再裁決。"""
        return entry_from(self.request({"op":"append","payload":payload,"expected":expected}))
