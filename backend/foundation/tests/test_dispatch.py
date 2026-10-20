"""Real PostgreSQL transaction and fencing tests; no broker eager mode."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from uuid import UUID, uuid4
from unittest.mock import patch
from django.db import DatabaseError, IntegrityError, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone
from foundation.dispatch import claim, complete, pending_batch, relay
from foundation.models import DispatchProbe, DONE, PENDING, RUNNING
from foundation.tasks import execute_probe


class DispatchTests(TransactionTestCase):
    def setUp(self) -> None:
        self.row = DispatchProbe.objects.create()

    def test_duplicate_delivery_has_one_effect(self) -> None:
        identity = str(self.row.id)
        self.assertTrue(execute_probe(identity, 0))
        self.assertFalse(execute_probe(identity, 0))
        self.row.refresh_from_db()
        self.assertEqual((self.row.state, self.row.completions), (DONE, 1))

    def test_wrong_generation_cannot_claim(self) -> None:
        self.assertIsNone(claim(self.row.id, 1))
        self.row.refresh_from_db()
        self.assertEqual(self.row.state, PENDING)

    def test_wrong_token_cannot_complete(self) -> None:
        self.assertIsNotNone(claim(self.row.id, 0))
        self.assertFalse(complete(self.row.id, 0, uuid4()))
        self.row.refresh_from_db()
        self.assertEqual((self.row.state, self.row.completions), (RUNNING, 0))

    def test_expired_result_rejected_before_and_after_requeue(self) -> None:
        token = claim(self.row.id, 0)
        assert token is not None
        DispatchProbe.objects.filter(pk=self.row.id).update(lease_until=timezone.now() - timedelta(seconds=1))
        self.assertFalse(complete(self.row.id, 0, token))
        self.assertEqual(pending_batch(), [(self.row.id, 1)])
        self.assertFalse(complete(self.row.id, 0, token))
        self.assertIsNone(claim(self.row.id, 0))
        self.assertTrue(execute_probe(str(self.row.id), 1))

    def test_valid_lease_not_requeued(self) -> None:
        self.assertIsNotNone(claim(self.row.id, 0))
        self.assertEqual(pending_batch(), [])

    def test_wrong_generation_cannot_complete(self) -> None:
        token = claim(self.row.id, 0)
        assert token is not None
        self.assertFalse(complete(self.row.id, 1, token))
        self.assertTrue(complete(self.row.id, 0, token))

    def test_completed_probe_not_redispatched(self) -> None:
        execute_probe(str(self.row.id), 0)
        self.assertEqual(pending_batch(), [])

    def test_rolled_back_creation_not_visible_to_relay(self) -> None:
        DispatchProbe.objects.all().delete()
        with transaction.atomic():
            DispatchProbe.objects.create()
            transaction.set_rollback(True)
        self.assertEqual(pending_batch(), [])

    def test_publish_failure_retains_pending_record(self) -> None:
        with patch("foundation.tasks.publish_probe", side_effect=RuntimeError("offline")) as publish:
            with self.assertRaises(RuntimeError):
                relay(publish)
        self.assertEqual(pending_batch(), [(self.row.id, 0)])

    def test_multiple_relay_passes_are_idempotent(self) -> None:
        messages: list[tuple[str, int]] = []
        def publish(identity: str, generation: int) -> None:
            messages.append((identity, generation))
        self.assertEqual(relay(publish), 1)
        self.assertEqual(relay(publish), 1)
        results = [execute_probe(*message) for message in messages]
        self.assertEqual(results, [True, False])

    def test_parallel_claims_have_one_winner(self) -> None:
        identity = self.row.id
        def competing_claim(_index: int) -> UUID | None:
            try:
                return claim(identity, 0)
            finally:
                connections.close_all()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(competing_claim, range(4)))
        self.assertEqual(sum(token is not None for token in results), 1)

    def test_database_rejects_second_completion(self) -> None:
        with self.assertRaises(IntegrityError):
            DispatchProbe.objects.filter(pk=self.row.id).update(completions=2)

    def test_database_rejects_running_without_lease(self) -> None:
        with self.assertRaises(IntegrityError):
            DispatchProbe.objects.filter(pk=self.row.id).update(state=RUNNING)

    def test_database_rejects_done_without_effect(self) -> None:
        with self.assertRaises(IntegrityError):
            DispatchProbe.objects.filter(pk=self.row.id).update(state=DONE)

    def test_health_checks_live_dependencies(self) -> None:
        self.assertEqual(self.client.get("/health/live/").status_code, 200)
        self.assertEqual(self.client.get("/health/ready/").status_code, 200)

    def test_failed_readiness_hides_exception_details(self) -> None:
        with patch("foundation.health.DispatchProbe.objects.exists", side_effect=DatabaseError("private DSN")):
            with self.assertLogs("foundation.health", level="WARNING"):
                response = self.client.get("/health/ready/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.content, b'{"status": "unavailable"}')

    def test_health_endpoints_reject_mutation(self) -> None:
        self.assertEqual(self.client.post("/health/live/").status_code, 405)
        self.assertEqual(self.client.post("/health/ready/").status_code, 405)
