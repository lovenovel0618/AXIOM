"""正式封存與曝光帳本：canonical 身分、重疊、狀態機與復原的 runtime 證據。"""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import stat
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from uuid import uuid4
from django.test import SimpleTestCase
from sealing.journal import JournalStore, durable_file
from sealing.rpc import JournalClient
from sealing.types import JournalEntry, SealRejected
from sealing.vault import Vault

SOURCE = hashlib.sha256(b"source").hexdigest()
ROWS = hashlib.sha256(b"rows").hexdigest()
OTHER_ROWS = hashlib.sha256(b"other-rows").hexdigest()
PROTOCOL = hashlib.sha256(b"protocol").hexdigest()
OTHER_PROTOCOL = hashlib.sha256(b"other-protocol").hexdigest()
SNAPSHOT = hashlib.sha256(b"snapshot-a").hexdigest()
OTHER_SNAPSHOT = hashlib.sha256(b"snapshot-b").hexdigest()
BLOCKED = "EXPOSURE_RECOVERY_BLOCKED"


class LocalJournal:
    """以同一 authority 檔取代私有 RPC；介面相同但無網路，僅供測試接線。"""
    def __init__(self, store: JournalStore) -> None:
        self.store = store

    def read(self) -> list[JournalEntry]:
        return self.store.read()

    def append(self, payload: dict[str, object], expected: int) -> JournalEntry:
        return self.store.append(payload, expected)


class BlockedJournal:
    """隔離中的 authority：任何讀寫都回遮罩失敗，不降級為本地猜測。"""
    def read(self) -> list[JournalEntry]:
        raise SealRejected(BLOCKED)

    def append(self, payload: dict[str, object], expected: int) -> JournalEntry:
        raise SealRejected(BLOCKED)


@skipUnless(sys.platform == "linux", "journal durability evidence requires Linux")
class VaultTests(SimpleTestCase):
    def setUp(self) -> None:
        self.root = TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        base = Path(self.root.name)
        self.events, self.checkpoint = base/"events", base/"checkpoint"
        self.data, self.keys = base/"data", base/"keys"
        self.journal = LocalJournal(JournalStore(self.events, self.checkpoint))
        self.tenant = str(uuid4())
        self.vault = Vault(self.data, self.keys, self.journal)

    def content(self, *rows: int) -> list[str]:
        return [self.vault.token(self.tenant, "CONTENT", {"row": row}) for row in rows]

    def lineage(self, *rows: int) -> list[str]:
        return [self.vault.token(self.tenant, "LINEAGE", ["LOCAL_UNTRUSTED_SOURCE", SOURCE, row]) for row in rows]

    def sealed(self, contents: list[str], lineages: list[str], *, protocol: str = PROTOCOL, rows: str = ROWS, **overrides: object) -> dict[str, object]:
        """合成最小合法 SealedTest；容器／split／dataset 預設每次不同，身分才看得出是否被洗白。"""
        document: dict[str, object] = {"kind": "SealedTest", "id": str(uuid4()), "tenant_id": self.tenant, "schema_version": "2.0",
            "created_at": "2026-10-21T00:00:00+00:00", "dataset_version_id": str(uuid4()), "observation_split_id": str(uuid4()),
            "benchmark_partition_id": None, "benchmark_case_id": None, "final_rows_hash": rows, "protocol_hash": protocol,
            "state": "AVAILABLE", "submission_id": None, "source_content_sha256": SOURCE,
            "final_observation_tokens": sorted(contents), "final_lineage_tokens": sorted(lineages), "exposure_fingerprint_version": "1.0"}
        document.update(overrides)
        return document

    def test_reordered_container_and_split_reuse_one_identity(self) -> None:
        first = self.sealed(self.content(0, 1), self.lineage(0, 1))
        attestation = self.vault.register(first, b"final-rows")
        self.assertEqual(attestation.sealed_test_id, str(first["id"]))
        again = self.vault.register(self.sealed(self.content(1, 0), self.lineage(1, 0)), b"final-rows")
        self.assertEqual(again.sealed_test_id, str(first["id"]))
        blob = self.data/(str(first["id"])+".sealed")
        self.assertEqual(stat.S_IMODE(blob.stat().st_mode), 0o400)
        self.assertEqual(self.journal.read()[0]["sequence"], 1)

    def test_protocol_change_and_row_subset_cannot_launder_same_observations(self) -> None:
        self.vault.register(self.sealed(self.content(0, 1), self.lineage(0, 1)), b"final-rows")
        for changed in (self.sealed(self.content(0, 1), self.lineage(0, 1), protocol=OTHER_PROTOCOL, rows=OTHER_ROWS),
                        self.sealed(self.content(0), self.lineage(0), rows=OTHER_ROWS)):
            with self.subTest(protocol=changed["protocol_hash"]), self.assertRaises(SealRejected) as raised:
                self.vault.register(changed, b"final-rows")
            self.assertEqual(raised.exception.code, "TEST_ALREADY_CONSUMED")

    def test_parallel_overlapping_registration_admits_exactly_one(self) -> None:
        candidates = [self.sealed(self.content(0, 1), self.lineage(0, 1)), self.sealed(self.content(1, 2), self.lineage(1, 2), rows=OTHER_ROWS)]
        def attempt(document: dict[str, object]) -> str:
            try:
                return self.vault.register(document, b"final-rows").sealed_test_id
            except SealRejected as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, candidates))
        self.assertEqual(outcomes.count("TEST_ALREADY_CONSUMED"), 1)
        self.assertEqual(len(set(outcomes)-{"TEST_ALREADY_CONSUMED"}), 1)

    def test_state_machine_consume_before_read_and_no_resurrection(self) -> None:
        identity = self.vault.register(self.sealed(self.content(0, 1), self.lineage(0, 1)), b"final-rows").sealed_test_id
        submission = str(uuid4())
        with self.assertRaises(SealRejected) as raised:
            self.vault.read_final(self.tenant, identity, submission, SNAPSHOT, lambda: None)
        self.assertEqual(raised.exception.code, "INVALID_TRANSITION")
        self.assertEqual(self.vault.transition(self.tenant, identity, "RESERVE", submission, SNAPSHOT), "RESERVED")
        authorized: list[int] = []
        with self.assertRaises(SealRejected):
            self.vault.read_final(self.tenant, identity, submission, SNAPSHOT, lambda: authorized.append(1))
        self.assertEqual(authorized, [])
        self.assertEqual(self.vault.transition(self.tenant, identity, "CONSUME", submission, SNAPSHOT), "CONSUMED")
        self.assertEqual(self.vault.read_final(self.tenant, identity, submission, SNAPSHOT, lambda: authorized.append(1)), b"final-rows")
        self.assertEqual(authorized, [1])
        self.assertEqual(self.vault.transition(self.tenant, identity, "RESERVE", submission, SNAPSHOT), "CONSUMED")
        self.assertEqual(self.vault.transition(self.tenant, identity, "RETIRE", None, None), "RETIRED")
        with self.assertRaises(SealRejected) as raised:
            self.vault.transition(self.tenant, identity, "RESERVE", submission, SNAPSHOT)
        self.assertEqual(raised.exception.code, "TEST_ALREADY_CONSUMED")

    def test_submission_snapshot_aliasing_and_invalid_transitions(self) -> None:
        identity = self.vault.register(self.sealed(self.content(0, 1), self.lineage(0, 1)), b"final-rows").sealed_test_id
        submission, other = str(uuid4()), str(uuid4())
        self.assertEqual(self.vault.transition(self.tenant, identity, "RESERVE", submission, SNAPSHOT), "RESERVED")
        self.assertEqual(self.vault.transition(self.tenant, identity, "RESERVE", submission, SNAPSHOT), "RESERVED")
        for action, selected, snapshot in (("RESERVE", submission, OTHER_SNAPSHOT), ("CONSUME", other, SNAPSHOT)):
            with self.subTest(action=action, snapshot=snapshot), self.assertRaises(SealRejected) as raised:
                self.vault.transition(self.tenant, identity, action, selected, snapshot)
            self.assertEqual(raised.exception.code, "TEST_ALREADY_RESERVED")
        for selected, snapshot in ((submission, "short"), (submission, None), (None, SNAPSHOT)):
            with self.subTest(snapshot=snapshot), self.assertRaises(SealRejected) as raised:
                self.vault.transition(self.tenant, identity, "RESERVE", selected, snapshot)
            self.assertEqual(raised.exception.code, "INVALID_TRANSITION")
        with self.assertRaises(SealRejected) as raised:
            self.vault.transition(self.tenant, identity, "UNKNOWN", submission, SNAPSHOT)
        self.assertEqual(raised.exception.code, "INVALID_TRANSITION")

    def test_missing_key_never_regenerates_exposure_authority(self) -> None:
        self.vault.register(self.sealed(self.content(0, 1), self.lineage(0, 1)), b"final-rows")
        key = self.keys/"exposure.key"
        key.unlink()
        with self.assertRaises(SealRejected) as raised:
            Vault(self.data, self.keys, self.journal)
        self.assertEqual(raised.exception.code, BLOCKED)
        self.assertFalse(key.exists())

    def test_truncated_journal_and_unreachable_authority_block_recovery(self) -> None:
        self.vault.register(self.sealed(self.content(0, 1), self.lineage(0, 1)), b"final-rows")
        path = self.events/"events.jsonl"
        content = path.read_bytes()
        path.write_bytes(content[:content.index(b"\n")+1])
        with self.assertRaises(SealRejected) as raised:
            Vault(self.data, self.keys, self.journal)
        self.assertEqual(raised.exception.code, BLOCKED)
        path.write_bytes(content)
        with self.assertRaises(SealRejected) as raised:
            Vault(self.data, self.keys, BlockedJournal())
        self.assertEqual(raised.exception.code, BLOCKED)

    def test_orphan_intent_and_deleted_private_db_replay_latest_water_level(self) -> None:
        document = self.sealed(self.content(0, 1), self.lineage(0, 1))
        blob = b"orphan-final-rows"
        durable_file(self.data/(str(document["id"])+".sealed"), blob)
        identity = self.vault.identity(document)
        self.assertEqual(self.journal.append({"action": "REGISTER", "operation_id": "REGISTER:"+identity, "sealed": document,
            "blob_sha256": hashlib.sha256(blob).hexdigest(), "blob_size": len(blob)}, 1)["sequence"], 2)
        (self.data/"sealed.sqlite3").unlink()
        recovered = Vault(self.data, self.keys, self.journal)
        self.assertEqual(recovered.register(document, blob).sealed_test_id, str(document["id"]))
        with self.assertRaises(SealRejected) as raised:
            recovered.register(self.sealed(self.content(0), self.lineage(0), rows=OTHER_ROWS), blob)
        self.assertEqual(raised.exception.code, "TEST_ALREADY_CONSUMED")

    def test_private_rpc_and_volume_boundaries_reject_untrusted_callers(self) -> None:
        for path, token in (("relative/journal.sock", "x"*40), ("/var/lib/axiom/socket/journal.sock", "short"), ("/var/lib/axiom/socket/journal.sock", "")):
            with self.subTest(path=path, token=token), self.assertRaises(SealRejected) as raised:
                JournalClient(path, token)
            self.assertEqual(raised.exception.code, BLOCKED)
        self.assertEqual(stat.S_IMODE(self.data.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(self.keys.stat().st_mode), 0o700)
