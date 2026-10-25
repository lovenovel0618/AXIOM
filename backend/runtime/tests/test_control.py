"""PostgreSQL control races, schema boundaries and immutable snapshot tests."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4
from django.db import IntegrityError, connections, transaction
from django.test import TransactionTestCase
from jsonschema.exceptions import ValidationError
from runtime.control import HEARTBEAT_SECONDS, LEASE_SECONDS, Lease, cancel, check_submission, claim, confirm_control_stopped, enqueue, enqueue_child, heartbeat, load_checkpoint, recover, save_checkpoint
from runtime.contracts import canonical_bytes, identity_hash, validate
from runtime.control_fixture import bundle, child_bundle, research_bundle
from runtime.models import InputSnapshot, RunEvent, RuntimeAttempt, RuntimeCheckpoint, RuntimeRun
from runtime.records import ControlError, db_now, public_attempt, public_run, save_run
from runtime.tasks import relay_control

WORKER = "worker-A"


class ControlTests(TransactionTestCase):
    def setUp(self) -> None:
        self.documents = bundle()
        self.tenant = UUID(self.documents[0]["tenant_id"])
        self.identity = enqueue(self.tenant, *self.documents)

    def lease(self) -> Lease:
        lease = claim(self.tenant, self.identity, 0, WORKER)
        assert lease is not None
        return lease

    def row(self) -> RuntimeRun:
        return RuntimeRun.objects.get(pk=self.identity)

    def expire(self, lease: Lease) -> None:
        attempt = RuntimeAttempt.objects.get(pk=lease.attempt_id)
        attempt.document["lease_expires_at"] = (db_now() - timedelta(seconds=1)).isoformat()
        attempt.save()

    def available(self) -> None:
        RuntimeRun.objects.filter(pk=self.identity).update(available_at=db_now() - timedelta(seconds=1))

    def progress(self) -> dict[str, object]:
        """可保存的 checkpoint 進度：DSL／精度／RNG 與策略進度皆為受控 JSON。"""
        return {"dsl_hash": identity_hash({"strategy": "linear"}), "precision_bits": 64,
            "rng_state": {"seed": 7, "counter": 3}, "strategy_progress": {"phase": "SEARCH_OPEN", "candidates": 2}}

    def forge_checkpoint(self, lease: Lease, **changes: object) -> UUID:
        """直接落庫偽造 checkpoint，模擬換環境後帶入或遭改寫的副本；僅供拒絕路徑測試。"""
        source = RuntimeCheckpoint.objects.filter(run_id=self.identity).order_by("created_at").first()
        assert source is not None
        document = dict(source.document) | changes
        identity = uuid4()
        document["id"] = str(identity)
        if "checksum" not in changes:
            document["checksum"] = identity_hash({key: value for key, value in document.items() if key != "checksum"})
        with transaction.atomic():
            RuntimeCheckpoint.objects.create(id=identity, run=self.row(), tenant_id=self.tenant,
                attempt_id=lease.attempt_id, document=document, created_at=source.created_at)
        return identity

    def test_full_records_and_public_projection_match_contracts(self) -> None:
        lease = self.lease()
        validate(self.row().document, "runtime-v2.schema.json", "RunRecord")
        validate(RuntimeAttempt.objects.get(pk=lease.attempt_id).document, "runtime-v2.schema.json", "AttemptRecord")
        run = public_run(self.tenant, self.identity)
        attempt = public_attempt(self.tenant, self.identity, lease.attempt_id)
        self.assertNotIn("input_artifact_id", run)
        self.assertNotIn("cancellation_epoch", run)
        self.assertNotIn("budget_account_id", run)
        self.assertNotIn("heartbeat_at", attempt)
        self.assertEqual((run["kind"], attempt["kind"]), ("Run", "Attempt"))

    def test_enqueue_replay_preserves_one_run_and_event(self) -> None:
        self.lease()
        self.assertEqual(enqueue(self.tenant, *self.documents), self.identity)
        self.assertEqual(RuntimeRun.objects.count(), 1)
        self.assertEqual(RunEvent.objects.count(), 2)

    def test_enqueue_conflicting_input_rejected(self) -> None:
        self.documents[1]["payload"]["object_version"] = "changed"
        self.documents[2]["input_hash"] = identity_hash(self.documents[1])
        with self.assertRaisesRegex(ValueError, "conflict"):
            enqueue(self.tenant, *self.documents)

    def test_input_hash_mismatch_rejected(self) -> None:
        self.documents[2]["input_hash"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            enqueue(self.tenant, *self.documents)

    def test_cross_tenant_create_rejected(self) -> None:
        tenant = uuid4()
        with self.assertRaisesRegex(ValueError, "Tenant"):
            enqueue(tenant, *self.documents)

    def test_cross_tenant_claim_and_read_rejected(self) -> None:
        tenant = uuid4()
        with self.assertRaises(RuntimeRun.DoesNotExist):
            claim(tenant, self.identity, 0, WORKER)
        with self.assertRaises(RuntimeRun.DoesNotExist):
            public_run(tenant, self.identity)
        self.assertEqual(RuntimeAttempt.objects.count(), 0)

    def test_attempt_projection_requires_both_tenant_and_run(self) -> None:
        lease = self.lease()
        wrong_id = uuid4()
        with self.assertRaises(RuntimeAttempt.DoesNotExist):
            public_attempt(self.tenant, wrong_id, lease.attempt_id)
        with self.assertRaises(RuntimeAttempt.DoesNotExist):
            public_attempt(wrong_id, self.identity, lease.attempt_id)

    def test_duplicate_delivery_has_one_attempt(self) -> None:
        self.lease()
        self.assertIsNone(claim(self.tenant, self.identity, 0, WORKER))
        self.assertEqual(RuntimeAttempt.objects.count(), 1)

    def test_parallel_claim_has_one_winner(self) -> None:
        def compete(_index: int) -> Lease | None:
            try:
                return claim(self.tenant, self.identity, 0, WORKER)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            leases = list(pool.map(compete, range(4)))
        self.assertEqual(sum(lease is not None for lease in leases), 1)
        self.assertEqual(RuntimeAttempt.objects.count(), 1)

    def test_heartbeat_keeps_revision_and_event_cursor(self) -> None:
        lease = self.lease()
        before = public_run(self.tenant, self.identity)
        heartbeat(lease)
        self.assertEqual(public_run(self.tenant, self.identity), before)
        self.assertEqual(RunEvent.objects.count(), 2)

    def test_wrong_worker_and_generation_are_fenced(self) -> None:
        lease = self.lease()
        for changed in [replace(lease, worker_id="worker-B"), replace(lease, generation=2), replace(lease, attempt_id=uuid4())]:
            with self.subTest(lease=changed):
                with self.assertRaisesRegex(ControlError, "STALE_ATTEMPT"):
                    check_submission(changed)
        self.assertEqual(RunEvent.objects.count(), 2)

    def test_expired_attempt_is_fenced_before_recovery(self) -> None:
        lease = self.lease()
        self.expire(lease)
        with self.assertRaisesRegex(ControlError, "STALE_ATTEMPT"):
            heartbeat(lease)
        with self.assertRaisesRegex(ControlError, "STALE_ATTEMPT"):
            check_submission(lease)

    def test_retry_retains_history_and_rejects_old_attempt(self) -> None:
        old = self.lease()
        self.expire(old)
        recover(self.tenant, self.identity)
        self.assertIsNone(claim(self.tenant, self.identity, 1, WORKER))
        self.available()
        new = claim(self.tenant, self.identity, 1, "worker-B")
        assert new is not None
        self.assertEqual(new.generation, 2)
        self.assertEqual(RuntimeAttempt.objects.get(pk=old.attempt_id).document["status"], "EXPIRED")
        with self.assertRaisesRegex(ControlError, "STALE_ATTEMPT"):
            check_submission(old)
        check_submission(new)
        self.assertEqual(RuntimeAttempt.objects.count(), 2)

    def test_retry_exhaustion_closes_root(self) -> None:
        lease = self.lease()
        for generation in range(1, 4):
            self.expire(lease)
            recover(self.tenant, self.identity)
            self.available()
            if generation < 3:
                next_lease = claim(self.tenant, self.identity, generation, WORKER)
                assert next_lease is not None
                lease = next_lease
        self.assertEqual(self.row().document["status"], "FAILED")
        self.assertEqual(self.row().document["stop_reason"], "DEPENDENCY_FAILURE")
        self.assertIsNone(claim(self.tenant, self.identity, 3, WORKER))
        self.assertEqual(RuntimeAttempt.objects.count(), 3)

    def test_queue_timeout_is_terminal_without_attempt(self) -> None:
        RuntimeRun.objects.filter(pk=self.identity).update(queue_deadline=db_now() - timedelta(seconds=1))
        self.assertIsNone(claim(self.tenant, self.identity, 0, WORKER))
        self.assertEqual(self.row().document["status"], "FAILED")
        self.assertEqual(RuntimeAttempt.objects.count(), 0)
        self.assertEqual(list(RunEvent.objects.order_by("sequence").values_list("document__event_type", flat=True)), ["RunQueued", "RunFinished"])

    def test_heartbeats_cannot_extend_root_deadline(self) -> None:
        lease = self.lease()
        RuntimeRun.objects.filter(pk=self.identity).update(first_started_at=db_now() - timedelta(seconds=301))
        with self.assertRaisesRegex(ControlError, "STALE_ATTEMPT"):
            heartbeat(lease)
        recover(self.tenant, self.identity)
        self.assertEqual(self.row().document["status"], "FAILED")
        self.assertEqual(self.row().document["stop_reason"], "BUDGET_EXHAUSTED")

    def test_cancel_fences_before_stop_confirmation(self) -> None:
        lease = self.lease()
        cancel(self.tenant, self.identity, self.row().document["revision"])
        self.assertEqual(self.row().document["status"], "CANCEL_REQUESTED")
        self.assertEqual(self.row().document["cancellation_epoch"], 1)
        with self.assertRaisesRegex(ControlError, "ROOT_CANCELLED"):
            check_submission(lease)
        confirm_control_stopped(self.tenant, self.identity)
        self.assertEqual(self.row().document["status"], "CANCELLED")
        self.assertEqual(RuntimeAttempt.objects.get(pk=lease.attempt_id).document["status"], "CANCELLED")

    def test_cancel_queued_then_late_delivery_cannot_claim(self) -> None:
        cancel(self.tenant, self.identity, 0)
        self.assertIsNone(claim(self.tenant, self.identity, 0, WORKER))
        confirm_control_stopped(self.tenant, self.identity)
        self.assertEqual(RuntimeAttempt.objects.count(), 0)

    def test_cancel_revision_and_terminal_rejections(self) -> None:
        with self.assertRaisesRegex(ValueError, "revision"):
            cancel(self.tenant, self.identity, 99)
        self.assertEqual(self.row().document["cancellation_epoch"], 0)
        cancel(self.tenant, self.identity, 0)
        cancel(self.tenant, self.identity, self.row().document["revision"])
        self.assertEqual(self.row().document["cancellation_epoch"], 1)
        confirm_control_stopped(self.tenant, self.identity)
        with self.assertRaisesRegex(ControlError, "RUN_ALREADY_TERMINAL"):
            cancel(self.tenant, self.identity, self.row().document["revision"])

    def test_claim_cancel_race_never_resurrects(self) -> None:
        def compete(action: str) -> None:
            try:
                if action == "claim":
                    claim(self.tenant, self.identity, 0, WORKER)
                else:
                    # Both serialized outcomes are legitimate revision preconditions.
                    try:
                        cancel(self.tenant, self.identity, 0)
                    except ValueError:
                        cancel(self.tenant, self.identity, 1)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(compete, ["claim", "cancel"]))
        self.assertEqual(self.row().document["status"], "CANCEL_REQUESTED")
        self.assertIsNone(claim(self.tenant, self.identity, 0, WORKER))

    def test_event_failure_rolls_back_attempt_and_run(self) -> None:
        with patch("runtime.control.emit", side_effect=RuntimeError("outbox failure")):
            with self.assertRaises(RuntimeError):
                claim(self.tenant, self.identity, 0, WORKER)
        self.assertEqual(self.row().document["status"], "QUEUED")
        self.assertEqual(RuntimeAttempt.objects.count(), 0)
        self.assertEqual(RunEvent.objects.count(), 1)

    def test_database_blocks_snapshot_update_and_delete(self) -> None:
        changed = self.documents[1]
        with self.assertRaises(IntegrityError):
            InputSnapshot.objects.filter(run_id=self.identity).update(task_input=changed)
        with self.assertRaises(IntegrityError):
            InputSnapshot.objects.filter(run_id=self.identity).delete()

    def test_database_blocks_run_identity_mutation(self) -> None:
        document = self.row().document
        document["input_artifact_id"] = str(uuid4())
        with self.assertRaises(IntegrityError):
            RuntimeRun.objects.filter(pk=self.identity).update(document=document)

    def test_database_blocks_event_update(self) -> None:
        with self.assertRaises(IntegrityError):
            RunEvent.objects.filter(run_id=self.identity).update(sequence=100)

    def test_outer_transaction_rollback_leaves_no_queue_or_event(self) -> None:
        documents = bundle()
        tenant = UUID(documents[0]["tenant_id"])
        with transaction.atomic():
            enqueue(tenant, *documents)
            transaction.set_rollback(True)
        self.assertEqual(RuntimeRun.objects.count(), 1)
        self.assertEqual(InputSnapshot.objects.count(), 1)
        self.assertEqual(RunEvent.objects.count(), 1)

    def test_coordinator_expires_queue_without_worker(self) -> None:
        RuntimeRun.objects.filter(pk=self.identity).update(queue_deadline=db_now() - timedelta(seconds=1))
        recover(self.tenant, self.identity)
        self.assertEqual(self.row().document["status"], "FAILED")
        self.assertEqual(RuntimeAttempt.objects.count(), 0)

    def test_zero_wall_budget_never_means_unlimited(self) -> None:
        documents = bundle()
        documents[3]["limit"]["wall_seconds"] = 0
        tenant = UUID(documents[0]["tenant_id"])
        identity = enqueue(tenant, *documents)
        self.assertIsNone(claim(tenant, identity, 0, WORKER))
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["stop_reason"], "BUDGET_EXHAUSTED")

    def test_retry_keeps_first_start_and_snapshot(self) -> None:
        lease = self.lease()
        started = self.row().first_started_at
        digest = InputSnapshot.objects.get(run_id=self.identity).content_hash
        self.expire(lease)
        recover(self.tenant, self.identity)
        self.available()
        self.assertIsNotNone(claim(self.tenant, self.identity, 1, WORKER))
        self.assertEqual(self.row().first_started_at, started)
        self.assertEqual(InputSnapshot.objects.get(run_id=self.identity).content_hash, digest)

    def test_child_input_stays_disabled(self) -> None:
        documents = bundle()
        documents[0]["is_root"] = False
        documents[0]["parent_run_id"] = str(uuid4())
        tenant = UUID(documents[0]["tenant_id"])
        with self.assertRaisesRegex(ControlError, "FEATURE_DISABLED"):
            enqueue(tenant, *documents)

    def test_mutating_callers_input_does_not_mutate_saved_snapshot(self) -> None:
        self.documents[1]["payload"]["object_version"] = "mutated-caller"
        snapshot = InputSnapshot.objects.get(run_id=self.identity)
        self.assertEqual(snapshot.task_input["payload"]["object_version"], "synthetic-control-only")

    def test_broker_failure_cannot_skip_other_queue_deadlines(self) -> None:
        documents = bundle()
        tenant = UUID(documents[0]["tenant_id"])
        identity = enqueue(tenant, *documents)
        RuntimeRun.objects.filter(pk=identity).update(queue_deadline=db_now() - timedelta(seconds=1))
        with patch("runtime.tasks.app.send_task", side_effect=RuntimeError("broker down")):
            with self.assertRaises(RuntimeError):
                relay_control()
        self.assertEqual(RuntimeRun.objects.get(pk=identity).document["status"], "FAILED")
        self.assertEqual(self.row().document["status"], "QUEUED")

    def test_control_scope_cannot_enable_business_execution_in_database(self) -> None:
        with self.assertRaises(IntegrityError):
            RuntimeRun.objects.filter(pk=self.identity).update(control_only=False)

    def test_unrepresentable_timing_rejected_before_creation(self) -> None:
        documents = bundle()
        documents[2]["retry_policy"]["queue_timeout_seconds"] = 2**53 - 1
        tenant = UUID(documents[0]["tenant_id"])
        with self.assertRaisesRegex(ValueError, "datetime range"):
            enqueue(tenant, *documents)
        self.assertEqual(RuntimeRun.objects.count(), 1)

    def test_schema_rejects_extra_field(self) -> None:
        self.documents[1]["unexpected"] = True
        with self.assertRaises(ValidationError):
            enqueue(self.tenant, *self.documents)

    def test_plugin_config_and_backoff_are_verified(self) -> None:
        self.documents[2]["plugins"][0]["config_sha256"] = "f" * 64
        with self.assertRaisesRegex(ValueError, "config hash"):
            enqueue(self.tenant, *self.documents)
        self.documents[2]["plugins"][0]["config_sha256"] = identity_hash({})
        self.documents[2]["retry_policy"]["backoff_max_seconds"] = 0
        with self.assertRaises(ValidationError):
            enqueue(self.tenant, *self.documents)

    def test_lease_and_heartbeat_windows_match_contract(self) -> None:
        lease = self.lease()
        attempt = RuntimeAttempt.objects.get(pk=lease.attempt_id).document
        self.assertEqual(datetime.fromisoformat(attempt["lease_expires_at"]) - datetime.fromisoformat(attempt["started_at"]), timedelta(seconds=LEASE_SECONDS))
        heartbeat(lease)
        renewed = RuntimeAttempt.objects.get(pk=lease.attempt_id).document
        self.assertEqual(datetime.fromisoformat(renewed["lease_expires_at"]) - datetime.fromisoformat(renewed["heartbeat_at"]), timedelta(seconds=LEASE_SECONDS))
        self.assertLess(HEARTBEAT_SECONDS, LEASE_SECONDS)

    def test_checkpoint_roundtrip_binds_attempt_and_root_epoch(self) -> None:
        lease = self.lease()
        identity = save_checkpoint(lease, self.progress())
        self.assertEqual(RuntimeAttempt.objects.get(pk=lease.attempt_id).document["checkpoint_id"], str(identity))
        body = load_checkpoint(lease, identity)
        self.assertEqual(body["root_epoch"], 0)
        self.assertEqual(body["generation"], 1)
        self.assertEqual(body["strategy_progress"], self.progress()["strategy_progress"])

    def test_checkpoint_requires_complete_progress(self) -> None:
        lease = self.lease()
        with self.assertRaisesRegex(ControlError, "CHECKPOINT_INCOMPLETE"):
            save_checkpoint(lease, {"dsl_hash": "only-one"})
        self.assertEqual(RuntimeCheckpoint.objects.count(), 0)

    def test_checkpoint_survives_crash_retry_without_resetting_usage(self) -> None:
        lease = self.lease()
        run = self.row()
        run.document["budget_usage"]["tokens"] = 25
        save_run(run)
        identity = save_checkpoint(lease, self.progress())
        self.expire(lease)
        recover(self.tenant, self.identity)
        self.available()
        new = claim(self.tenant, self.identity, 1, "worker-B")
        assert new is not None
        with self.assertRaisesRegex(ControlError, "STALE_ATTEMPT"):
            load_checkpoint(lease, identity)
        body = load_checkpoint(new, identity)
        self.assertEqual(body["cumulative_usage"]["tokens"], 25)
        self.assertEqual(self.row().document["budget_usage"]["tokens"], 25)
        self.assertEqual(RuntimeAttempt.objects.count(), 2)

    def test_checkpoint_rejects_environment_data_plugin_or_checksum_change(self) -> None:
        lease = self.lease()
        identity = save_checkpoint(lease, self.progress())
        variants: list[dict[str, object]] = [
            {"environment_digest": identity_hash({"env": "changed"})},
            {"dataset_version_id": str(uuid4())},
            {"plugin_hashes": {}},
            {"checksum": "f" * 64},
        ]
        for changes in variants:
            forged = self.forge_checkpoint(lease, **changes)
            with self.subTest(changes=sorted(changes)):
                with self.assertRaisesRegex(ControlError, "CHECKPOINT_INCOMPATIBLE"):
                    load_checkpoint(lease, forged)
        self.assertEqual(load_checkpoint(lease, identity)["root_epoch"], 0)

    def test_cancelled_root_cannot_resume_from_checkpoint(self) -> None:
        lease = self.lease()
        identity = save_checkpoint(lease, self.progress())
        cancel(self.tenant, self.identity, self.row().document["revision"])
        with self.assertRaisesRegex(ControlError, "ROOT_CANCELLED"):
            load_checkpoint(lease, identity)
        self.assertTrue(RuntimeCheckpoint.objects.filter(pk=identity).exists())

    def test_database_blocks_checkpoint_update_delete_and_foreign_attempt(self) -> None:
        lease = self.lease()
        identity = save_checkpoint(lease, self.progress())
        with self.assertRaises(IntegrityError):
            RuntimeCheckpoint.objects.filter(pk=identity).update(document={})
        with self.assertRaises(IntegrityError):
            RuntimeCheckpoint.objects.filter(pk=identity).delete()
        document = dict(RuntimeCheckpoint.objects.get(pk=identity).document)
        document["attempt_id"] = str(uuid4())
        with self.assertRaises(IntegrityError):
            RuntimeCheckpoint.objects.create(id=uuid4(), run=self.row(), tenant_id=self.tenant,
                attempt_id=lease.attempt_id, document=document, created_at=db_now())


class ChildRunTests(TransactionTestCase):
    """研究子任務的建立、鎖序、取消語意與祖先 fencing；不涉及業務插件執行。"""

    def setUp(self) -> None:
        self.root = research_bundle()
        self.tenant = UUID(self.root[0]["tenant_id"])
        self.identity = enqueue(self.tenant, *self.root, control_only=False)
        lease = claim(self.tenant, self.identity, 0, WORKER)
        assert lease is not None

    def row(self, identity: UUID) -> RuntimeRun:
        return RuntimeRun.objects.get(pk=identity)

    def spawn(self, parent: UUID | None = None) -> tuple[UUID, tuple[dict[str, object], dict[str, object], dict[str, object], dict[str, object]]]:
        documents = child_bundle(self.root, str(parent or self.identity))
        return enqueue_child(self.tenant, *documents), documents

    def test_child_creation_links_root_and_shares_account(self) -> None:
        child_id, _documents = self.spawn()
        self.assertIn(str(child_id), self.row(self.identity).document["child_run_ids"])
        child = self.row(child_id).document
        self.assertFalse(child["is_root"])
        self.assertEqual(child["root_run_id"], str(self.identity))
        self.assertEqual(child["budget_account_id"], self.root[0]["budget_account_id"])
        self.assertEqual(child["research_budget_account_id"], self.root[0]["research_budget_account_id"])
        self.assertTrue(InputSnapshot.objects.filter(run_id=child_id).exists())
        validate(child, "runtime-v2.schema.json", "RunRecord")

    def test_child_creation_replay_is_idempotent(self) -> None:
        identity, documents = self.spawn()
        self.assertEqual(enqueue_child(self.tenant, *documents), identity)
        self.assertEqual(RuntimeRun.objects.filter(document__is_root=False).count(), 1)

    def test_child_requires_running_root(self) -> None:
        cancel(self.tenant, self.identity, self.row(self.identity).document["revision"])
        with self.assertRaisesRegex(ControlError, "DISPATCH_STAGE_VIOLATION"):
            self.spawn()

    def test_child_rejects_cross_root_parent(self) -> None:
        other = research_bundle(tenant_id=str(self.tenant))
        other_id = enqueue(self.tenant, *other, control_only=False)
        documents = child_bundle(self.root, str(other_id))
        with self.assertRaisesRegex(ControlError, "DISPATCH_STAGE_VIOLATION"):
            enqueue_child(self.tenant, *documents)

    def test_child_claim_requires_running_root(self) -> None:
        child_id, _documents = self.spawn()
        cancel(self.tenant, self.identity, self.row(self.identity).document["revision"])
        self.assertIsNone(claim(self.tenant, child_id, 0, WORKER))

    def test_root_cancel_fences_child_submission(self) -> None:
        child_id, _documents = self.spawn()
        lease = claim(self.tenant, child_id, 0, WORKER)
        assert lease is not None
        self.assertEqual(RuntimeAttempt.objects.get(pk=lease.attempt_id).document["root_epoch_at_dispatch"], 0)
        check_submission(lease)
        cancel(self.tenant, self.identity, self.row(self.identity).document["revision"])
        with self.assertRaisesRegex(ControlError, "ROOT_CANCELLED"):
            check_submission(lease)

    def test_child_cannot_be_cancelled_directly(self) -> None:
        child_id, _documents = self.spawn()
        with self.assertRaisesRegex(ControlError, "CHILD_RUN_NOT_CANCELLABLE"):
            cancel(self.tenant, child_id, self.row(child_id).document["revision"])

    def test_child_failure_does_not_close_root_dispatch(self) -> None:
        child_id, _documents = self.spawn()
        RuntimeRun.objects.filter(pk=child_id).update(queue_deadline=db_now() - timedelta(seconds=1))
        recover(self.tenant, child_id)
        self.assertEqual(self.row(child_id).document["status"], "FAILED")
        self.assertEqual(self.row(child_id).document["dispatch_stage"], "SEARCH_OPEN")
        self.assertEqual(self.row(self.identity).document["dispatch_stage"], "SEARCH_OPEN")

    def test_child_is_cancelled_when_root_is_cancelled(self) -> None:
        child_id, _documents = self.spawn()
        cancel(self.tenant, self.identity, self.row(self.identity).document["revision"])
        recover(self.tenant, child_id)
        child = self.row(child_id).document
        self.assertEqual((child["status"], child["stop_reason"]), ("CANCELLED", "USER_CANCELLED"))
        self.assertEqual(child["dispatch_stage"], "SEARCH_OPEN")

    def test_child_is_failed_when_root_failed(self) -> None:
        child_id, _documents = self.spawn()
        root_document = self.row(self.identity).document
        root_document.update(status="FAILED", stop_reason="BUDGET_EXHAUSTED", dispatch_stage="CLOSED")
        RuntimeRun.objects.filter(pk=self.identity).update(document=root_document)
        recover(self.tenant, child_id)
        child = self.row(child_id).document
        self.assertEqual((child["status"], child["stop_reason"]), ("FAILED", "DEPENDENCY_FAILURE"))


class CanonicalTests(TransactionTestCase):
    def test_fixed_unicode_byte_vector(self) -> None:
        self.assertEqual(canonical_bytes({"\U00010000": 2, "\ue000": 1}), '{"\ue000":1,"\U00010000":2}'.encode("utf-8"))

    def test_float_nonfinite_large_integer_and_surrogate_rejected(self) -> None:
        for value in [1.0, float("nan"), float("inf"), 2**53, "\ud800", {1: "key"}]:
            with self.subTest(value=repr(value)):
                with self.assertRaises((ValueError, UnicodeError)):
                    canonical_bytes(value)

    def test_depth_and_bytes_are_bounded(self) -> None:
        value: object = None
        for _ in range(33):
            value = [value]
        with self.assertRaisesRegex(ValueError, "depth"):
            canonical_bytes(value)
        large = "x" * (2 * 1024 * 1024)
        with self.assertRaisesRegex(ValueError, "size"):
            canonical_bytes(large)
