"""不可變本機物件 adapter：以 UUID 命名，拒絕 symlink／非一般檔，逐次核對大小與 SHA。
暫存、固定版本及只讀引用分開；此 adapter 不是 S3 或多租戶檔案系統沙箱。

Private local version adapter: generated keys, bounded IO, no mutable latest."""
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
import tempfile
from typing import BinaryIO, Protocol
from uuid import UUID

MAX_UPLOAD = 50 * 1024 * 1024
CHUNK_SIZE = 65536


class Readable(Protocol):
    def read(self, size: int = -1, /) -> bytes: ...


class StorageRejected(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ObjectRef:
    tenant: UUID
    upload: UUID
    version: UUID
    sha256: str
    size: int


class LocalVersionStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, reference: ObjectRef) -> Path:
        # Only UUID-derived components; a user's filename never enters this path.
        return self.root / f"{reference.tenant.hex}-{reference.upload.hex}-{reference.version.hex}.blob"

    def create(self, reference: ObjectRef, source: Readable) -> None:
        if not 1 <= reference.size <= MAX_UPLOAD:
            raise StorageRejected("UPLOAD_TOO_LARGE")
        descriptor, temporary = tempfile.mkstemp(prefix=".partial-", dir=self.root)
        temporary_path = Path(temporary)
        try:
            with os.fdopen(descriptor, "wb") as target:
                self._copy(source, target, reference)
                target.flush()
                os.fsync(target.fileno())
                os.fchmod(target.fileno(), 0o400)
            try:
                os.link(temporary_path, self.path(reference), follow_symlinks=False)
            except FileExistsError:
                self.verify(reference)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary_path.unlink(missing_ok=True)

    def _copy(self, source: Readable, target: BinaryIO, reference: ObjectRef) -> None:
        digest, total = hashlib.sha256(), 0
        while True:
            block = source.read(min(CHUNK_SIZE, reference.size - total + 1))
            if not block:
                break
            total += len(block)
            if total > reference.size:
                raise StorageRejected("UPLOAD_TOO_LARGE")
            digest.update(block)
            target.write(block)
        if total != reference.size or digest.hexdigest() != reference.sha256:
            raise StorageRejected("CHECKSUM_MISMATCH")

    def verify(self, reference: ObjectRef) -> None:
        self.read_verified(reference)

    def read_verified(self, reference: ObjectRef) -> bytes:
        if not 1 <= reference.size <= MAX_UPLOAD:
            raise StorageRejected("UPLOAD_OBJECT_CHANGED")
        try:
            descriptor = os.open(self.path(reference), os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size != reference.size:
                    raise StorageRejected("UPLOAD_OBJECT_CHANGED")
                content = source.read(reference.size + 1)
        except OSError as error:
            raise StorageRejected("UPLOAD_OBJECT_CHANGED") from error
        if len(content) != reference.size or hashlib.sha256(content).hexdigest() != reference.sha256:
            raise StorageRejected("UPLOAD_OBJECT_CHANGED")
        return content
