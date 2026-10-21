"""Evaluator 私有封存與曝光狀態機；app DB 回退不能洗掉獨立 journal 的 intent。"""
from collections.abc import Callable, Generator
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat
from secrets import token_bytes
from uuid import UUID
from runtime.budget_types import integer, object_fields
from runtime.contracts import canonical_bytes, identity_hash, validate
from sealing.journal import durable_file, ZERO_HASH
from sealing.rpc import Journal
from sealing.types import Attestation, JournalEntry, SealRejected, sequence, text

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS sealed(id TEXT PRIMARY KEY,identity_hash TEXT UNIQUE NOT NULL,document TEXT NOT NULL,blob_sha256 TEXT NOT NULL,blob_size INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS membership(sealed_id TEXT NOT NULL REFERENCES sealed(id),kind TEXT NOT NULL,token TEXT NOT NULL,PRIMARY KEY(sealed_id,kind,token));
CREATE TABLE IF NOT EXISTS exposure(tenant_id TEXT NOT NULL,version TEXT NOT NULL,kind TEXT NOT NULL,token TEXT NOT NULL,sealed_id TEXT NOT NULL REFERENCES sealed(id),submission_id TEXT,snapshot_hash TEXT,state TEXT NOT NULL CHECK(state IN ('RESERVED','CONSUMED','RETIRED')),PRIMARY KEY(tenant_id,version,kind,token));
"""


class Vault:
    """只有可信 Evaluator 掛載 data／keys；公有 DB 只保存 opaque attestation。"""
    def __init__(self, data: Path, keys: Path, journal: Journal) -> None:
        self.data,self.keys,self.journal = data,keys,journal
        for directory in (data,keys):
            directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.database = data/'sealed.sqlite3'
        self.master_path = keys/'exposure.key'
        entries = journal.read()
        if not self.master_path.exists():
            if entries or self.database.exists():
                raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
            durable_file(self.master_path,token_bytes(32))
        self.master = self.master_path.read_bytes()
        if len(self.master)!=32:
            raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
        with self.session() as connection:
            self.sync(connection)

    @contextmanager
    def session(self) -> Generator[sqlite3.Connection]:
        """鎖整個 authority 操作，SQLite 交易只能在 journal 確認之後提交。"""
        descriptor = os.open(self.data/'vault.lock',os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
        try:
            fcntl.flock(descriptor,fcntl.LOCK_EX)
            if not self.database.exists():
                created = os.open(self.database,os.O_CREAT|os.O_EXCL|os.O_WRONLY|os.O_NOFOLLOW,0o600)
                os.close(created)
            connection = sqlite3.connect(self.database,timeout=5)
            try:
                connection.execute('PRAGMA foreign_keys=ON')
                connection.execute('PRAGMA synchronous=FULL')
                connection.executescript(SCHEMA)
                connection.execute('BEGIN IMMEDIATE')
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()
        finally:
            os.close(descriptor)

    def fingerprint(self) -> str:
        """金鑰版本在獨立 journal 留指紋；密鑰遺失不得自動生成後重設資格。"""
        return hashlib.sha256(self.master).hexdigest()

    def token(self, tenant: str, kind: str, payload: object) -> str:
        """租戶範圍穩定 HMAC；外界無法用公開觀測雜湊猜回 final 值。"""
        tenant_key = hmac.new(self.master,('exposure-v1:'+str(UUID(tenant))).encode(),hashlib.sha256).digest()
        return hmac.new(tenant_key,canonical_bytes([kind,payload]),hashlib.sha256).hexdigest()

    def sync(self, connection: sqlite3.Connection) -> list[JournalEntry]:
        """每次追到當前 authority；舊 DB 重播較嚴格 intent，缺鏈／key 則整個拒絕。"""
        entries = self.journal.read()
        if not entries:
            entries = [self.journal.append({'action':'INIT','operation_id':'INIT','key_fingerprint':self.fingerprint()},0)]
        if entries[0]['payload'].get('key_fingerprint')!=self.fingerprint():
            raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
        row = connection.execute("SELECT value FROM meta WHERE key='head'").fetchone()
        saved = {'sequence':0,'epoch':entries[0]['epoch'],'entry_hash':ZERO_HASH} if row is None else object_fields(json.loads(row[0]))
        previous = ZERO_HASH
        for index,entry in enumerate(entries,1):
            unsigned = {key:entry[key] for key in ('epoch','sequence','previous_hash','payload','signature')}
            if entry['sequence']!=index or entry['epoch']!=entries[0]['epoch'] or entry['previous_hash']!=previous or identity_hash(unsigned)!=entry['entry_hash']:
                raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
            previous = entry['entry_hash']
        applied = integer(saved['sequence'])
        if applied>len(entries) or saved['epoch']!=entries[0]['epoch']:
            raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
        expected_hash = ZERO_HASH if applied==0 else entries[applied-1]['entry_hash']
        if saved['entry_hash']!=expected_hash:
            raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
        for entry in entries[applied:]:
            self.apply(connection,entry['payload'])
            connection.execute("INSERT OR REPLACE INTO meta VALUES('head',?)",(canonical_bytes({'sequence':entry['sequence'],'epoch':entry['epoch'],'entry_hash':entry['entry_hash']}).decode(),))
        return entries

    def write(self, connection: sqlite3.Connection, entries: list[JournalEntry], payload: dict[str,object]) -> JournalEntry:
        """journal 已確認而 DB commit 失敗時，不撤銷 intent；下次 sync 必須重播。"""
        entry = self.journal.append(payload,len(entries))
        self.apply(connection,payload)
        connection.execute("INSERT OR REPLACE INTO meta VALUES('head',?)",(canonical_bytes({'sequence':entry['sequence'],'epoch':entry['epoch'],'entry_hash':entry['entry_hash']}).decode(),))
        return entry

    def apply(self, connection: sqlite3.Connection, payload: dict[str,object]) -> None:
        """重播固定事件白名單，不解釋任意 SQL；labels 永遠不在 journal 內。"""
        action = payload['action']
        if action=='INIT':
            return
        if action=='REGISTER':
            document = object_fields(payload['sealed'])
            identity = self.identity(document)
            connection.execute('INSERT INTO sealed VALUES(?,?,?,?,?)',(text(document['id']),identity,canonical_bytes(document).decode(),text(payload['blob_sha256']),integer(payload['blob_size'])))
            for kind,field in [('CONTENT','final_observation_tokens'),('LINEAGE','final_lineage_tokens')]:
                connection.executemany('INSERT INTO membership VALUES(?,?,?)',[(text(document['id']),kind,text(token)) for token in sequence(document[field])])
            return
        self.apply_transition(connection,payload)

    def identity(self, document: dict[str,object]) -> str:
        """封存身分不依可重建容器；改協定仍由觀測 token 阻擋重複曝光。"""
        keys = ('tenant_id','source_content_sha256','final_rows_hash','protocol_hash','benchmark_partition_id','benchmark_case_id')
        return identity_hash({key:document[key] for key in keys})

    def stored(self, connection: sqlite3.Connection, identity: str, tenant: str) -> dict[str,object]:
        """私有查詢仍核對租戶；找不到不洩露別的租戶有無相同觀測。"""
        row = connection.execute('SELECT document FROM sealed WHERE id=?',(identity,)).fetchone()
        if row is None:
            raise SealRejected('NOT_FOUND')
        document = object_fields(json.loads(row[0]))
        if document['tenant_id']!=tenant:
            raise SealRejected('NOT_FOUND')
        return document

    def members(self, connection: sqlite3.Connection, identity: str) -> list[tuple[str,str]]:
        """固定 kind／token 順序，並行重疊由唯一鍵與 authority 鎖裁決。"""
        return [(text(kind),text(token)) for kind,token in connection.execute('SELECT kind,token FROM membership WHERE sealed_id=? ORDER BY kind,token',(identity,))]

    def overlap(self, connection: sqlite3.Connection, tenant: str, tokens: list[tuple[str,str]]) -> bool:
        """任一 token 已預留／消耗／退役都算重疊，不只比整包 SHA。"""
        return any(connection.execute('SELECT 1 FROM exposure WHERE tenant_id=? AND version=? AND kind=? AND token=?',(tenant,'1.0',kind,token)).fetchone() is not None for kind,token in tokens)

    def registered(self, connection: sqlite3.Connection, tokens: list[tuple[str,str]]) -> bool:
        """token 具租戶範圍，已在任何封存登記者一律拒絕；換 protocol 不能洗白同批觀測。"""
        return any(connection.execute('SELECT 1 FROM membership WHERE kind=? AND token=?',(kind,token)).fetchone() is not None for kind,token in tokens)

    def register(self, document: dict[str,object], final_bytes: bytes) -> Attestation:
        """私有檔先耐久保存，再登記；app DB 失敗只留下 AVAILABLE 孤立封存。"""
        validate(document,'research-v2.schema.json','SealedTest')
        tenant = text(document['tenant_id'])
        with self.session() as connection:
            entries = self.sync(connection)
            identity = self.identity(document)
            existing = connection.execute('SELECT id FROM sealed WHERE identity_hash=?',(identity,)).fetchone()
            if existing is not None:
                previous = self.stored(connection,text(existing[0]),tenant)
                if previous['state']!='AVAILABLE' or self.overlap(connection,tenant,self.members(connection,text(previous['id']))):
                    raise SealRejected('TEST_ALREADY_CONSUMED')
                self.blob(connection,text(previous['id']))
                return self.attest(previous,entries[-1])
            tokens = [(kind,text(token)) for kind,field in [('CONTENT','final_observation_tokens'),('LINEAGE','final_lineage_tokens')] for token in sequence(document[field])]
            if self.registered(connection,tokens) or self.overlap(connection,tenant,tokens):
                raise SealRejected('TEST_ALREADY_CONSUMED')
            path = self.data/(str(UUID(text(document['id'])))+'.sealed')
            if path.exists():
                raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
            durable_file(path,final_bytes)
            os.chmod(path,0o400)
            event = self.write(connection,entries,{'action':'REGISTER','operation_id':'REGISTER:'+identity,'sealed':document,'blob_sha256':hashlib.sha256(final_bytes).hexdigest(),'blob_size':len(final_bytes)})
            return self.attest(document,event)

    def attest(self, document: dict[str,object], event: JournalEntry) -> Attestation:
        """只回不透明封存 ID 與來源／協定／水位，不回 tokens 或 final 統計。"""
        return Attestation(text(document['id']),text(document['source_content_sha256']),text(document['protocol_hash']),event['epoch'],event['sequence'],event['entry_hash'])

    def apply_transition(self, connection: sqlite3.Connection, payload: dict[str,object]) -> None:
        """所有不可逆變動共用會員集合；退役不刪除曝光 tombstone。"""
        identity,tenant = text(payload['sealed_test_id']),text(payload['tenant_id'])
        document = self.stored(connection,identity,tenant)
        target = {'RESERVE':'RESERVED','CONSUME':'CONSUMED','RETIRE':'RETIRED'}[text(payload['action'])]
        for kind,token in self.members(connection,identity):
            connection.execute('INSERT OR IGNORE INTO exposure VALUES(?,?,?,?,?,?,?,?)',(tenant,'1.0',kind,token,identity,payload['submission_id'],payload['snapshot_hash'],target))
            connection.execute('UPDATE exposure SET state=? WHERE tenant_id=? AND kind=? AND token=? AND sealed_id=?',(target,tenant,kind,token,identity))
        document.update(state=target,submission_id=payload['submission_id'])
        connection.execute('UPDATE sealed SET document=? WHERE id=?',(canonical_bytes(document).decode(),identity))

    def transition(self, tenant: str, identity: str, action: str, submission: str | None, snapshot: str | None) -> str:
        """僅可信協調器原語；公開 API 尚未開放任填 submission 的預留。"""
        with self.session() as connection:
            entries = self.sync(connection)
            document = self.stored(connection,identity,tenant)
            state = text(document['state'])
            if action not in {'RESERVE','CONSUME','RETIRE'}:
                raise SealRejected('INVALID_TRANSITION')
            if action!='RETIRE':
                if submission is None or snapshot is None or len(snapshot)!=64:
                    raise SealRejected('INVALID_TRANSITION')
                UUID(submission)
                self.same_submission(connection,document,submission,snapshot)
            expected = {'RESERVE':{'AVAILABLE','RESERVED','CONSUMED'},'CONSUME':{'RESERVED','CONSUMED'},'RETIRE':{'AVAILABLE','RESERVED','CONSUMED','RETIRED'}}[action]
            if state not in expected:
                raise SealRejected('TEST_ALREADY_CONSUMED')
            target = {'RESERVE':'RESERVED','CONSUME':'CONSUMED','RETIRE':'RETIRED'}[action]
            if state==target or (action=='RESERVE' and state=='CONSUMED'):
                return state
            self.write(connection,entries,{'action':action,'operation_id':f'{action}:{identity}:{submission}:{snapshot}',
                'tenant_id':tenant,'sealed_test_id':identity,'submission_id':submission if submission is not None else document['submission_id'],'snapshot_hash':snapshot})
            return target

    def same_submission(self, connection: sqlite3.Connection, document: dict[str,object], submission: str, snapshot: str) -> None:
        """相同 submission 也不能換 snapshot 或別的封存包；唯一鍵不能被 alias 繞過。"""
        for kind,token in self.members(connection,text(document['id'])):
            row = connection.execute('SELECT sealed_id,submission_id,snapshot_hash FROM exposure WHERE tenant_id=? AND kind=? AND token=?',(text(document['tenant_id']),kind,token)).fetchone()
            if row is not None and tuple(row)!=(document['id'],submission,snapshot):
                raise SealRejected('TEST_ALREADY_RESERVED')

    def blob(self, connection: sqlite3.Connection, identity: str) -> bytes:
        """只能在私有域讀固定 UUID 檔；拒 symlink／大小或 SHA 掉包。"""
        row = connection.execute('SELECT blob_sha256,blob_size FROM sealed WHERE id=?',(identity,)).fetchone()
        if row is None:
            raise SealRejected('NOT_FOUND')
        descriptor = os.open(self.data/(str(UUID(identity))+'.sealed'),os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
        with os.fdopen(descriptor,'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size!=row[1] or info.st_size>524288:
                raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
            value = source.read(524289)
        if hashlib.sha256(value).hexdigest()!=row[0]:
            raise SealRejected('EXPOSURE_RECOVERY_BLOCKED')
        return value

    def read_final(self, tenant: str, identity: str, submission: str, snapshot: str, authorize: Callable[[],None]) -> bytes:
        """先核對已消耗與最新 journal，允許授權後才讀 labels；未消耗不得觸發任何授權副作用。"""
        with self.session() as connection:
            self.sync(connection)
            # replay 的 CONSUMED 必須先提交，才可建立新的唯讀／fencing 區段。
            connection.commit()
            connection.execute('BEGIN IMMEDIATE')
            document = self.stored(connection,identity,tenant)
            self.same_submission(connection,document,submission,snapshot)
            if document['state']!='CONSUMED' or document['submission_id']!=submission:
                raise SealRejected('INVALID_TRANSITION')
            authorize()
            return self.blob(connection,identity)
