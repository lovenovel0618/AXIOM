"""真實 SEARCH→FIT 隔離重放、帳本、授權與取消；不使用 final labels。"""
import json
from unittest.mock import patch
from uuid import UUID, uuid4
from django.test import override_settings
from django.db import transaction
from catalog.fit import attach, fit_tick, recover_fit
from catalog.models import Candidate, FitRun, Reservation, ResearchBudget
from catalog.tasks import relay_fit
from catalog.tests.test_search import SearchFixture, LIMITS
from catalog.validation import ApiError
from runtime.control import cancel
from runtime.models import InputSnapshot, RuntimeAttempt, RuntimeRun, ValidationRun
from runtime.records import db_now


@override_settings(FIT_ENABLED=True, FIT_LIMITS_JSON=json.dumps(LIMITS))
class FitTests(SearchFixture):
    def fitted(self) -> FitRun:
        search = self.enqueue()
        self.assertTrue(self.execute(search))
        candidate = Candidate.objects.filter(search_run_id=search).order_by("development_rank").first()
        assert candidate is not None
        return FitRun.objects.get(pk=UUID(candidate.document["fit_run_ids"][0]))

    def test_real_fit_records_two_splits_and_authorized_readback(self) -> None:
        fit = self.fitted()
        self.assertTrue(attach(self.actor.tenant_id, fit.run_id))
        snapshot = InputSnapshot.objects.get(run_id=fit.run_id)
        self.assertEqual(snapshot.task_input["payload"]["fit_row_ids"], self.version.document["observation_split"]["fit"])
        self.assertNotIn("final_test", snapshot.task_input["payload"])
        self.assertTrue(fit_tick(str(self.actor.tenant_id), str(fit.run_id), 0))
        fit.run.refresh_from_db()
        self.assertEqual((fit.run.document["status"], fit.run.document["phase"]), ("SUCCEEDED", "FITTING"))
        results = list(ValidationRun.objects.filter(run_id=fit.run_id))
        self.assertEqual({row.split_role for row in results}, {"FIT", "DEVELOPMENT"})
        for row in results:
            self.assertEqual(row.document["selected_count"], len(self.version.document["observation_split"][row.split_role.lower()]))
            self.assertEqual(row.document["valid_coverage"], 1)
            self.assertEqual(row.document["metrics"]["mae"], 0)
            self.assertEqual(row.document["outcome_status"], "INSUFFICIENT_EVIDENCE")
            self.assertEqual(self.client.get(f"/api/v2/validation-runs/{row.id}").status_code, 200)
            from django.contrib.auth.models import User
            other = User.objects.create(username=uuid4().hex)
            with transaction.atomic():
                from catalog.models import Account
                Account.objects.create(user=other, tenant=self.actor.tenant)
            self.client.force_login(other)
            self.assertEqual(self.client.get(f"/api/v2/validation-runs/{row.id}").status_code, 404)
            self.client.force_login(self.actor.user)
        self.assertEqual(Reservation.objects.get(root__run_id=fit.run_id).state, "RELEASED")
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document["status"], "CLOSING")
        candidate = Candidate.objects.get(document__fit_run_ids__contains=[str(fit.id)])
        response = self.client.get(f"/api/v2/runs/{candidate.search_run_id}/candidates")
        rendered = next(row for row in response.json()["items"] if row["id"] == str(candidate.id))
        self.assertEqual(rendered["validation_status"], "FINISHED")
        self.assertEqual(set(rendered["validation_run_ids"]), {str(row.id) for row in results})

    def test_duplicate_attach_and_delivery_do_not_duplicate_cost_or_results(self) -> None:
        fit = self.fitted()
        attach(self.actor.tenant_id, fit.run_id)
        self.assertTrue(attach(self.actor.tenant_id, fit.run_id))
        fit_tick(str(self.actor.tenant_id), str(fit.run_id), 0)
        account = ResearchBudget.objects.get(research_version=self.version).document
        self.assertFalse(fit_tick(str(self.actor.tenant_id), str(fit.run_id), 0))
        self.assertEqual(ValidationRun.objects.filter(run_id=fit.run_id).count(), 2)
        self.assertEqual(RuntimeAttempt.objects.filter(run_id=fit.run_id).count(), 1)
        self.assertEqual(ResearchBudget.objects.get(research_version=self.version).document, account)

    def test_disabled_and_wrong_tenant_cannot_execute(self) -> None:
        fit = self.fitted()
        with self.settings(FIT_ENABLED=False):
            self.assertEqual(relay_fit(), 0)
            self.assertFalse(fit_tick(str(self.actor.tenant_id), str(fit.run_id), 0))
            with self.assertRaises(ApiError):
                attach(self.actor.tenant_id, fit.run_id)
        self.assertFalse(fit_tick(str(uuid4()), str(fit.run_id), 0))
        self.assertFalse(InputSnapshot.objects.filter(run_id=fit.run_id).exists())

    def test_only_one_fit_can_hold_memory_and_relay_uses_dedicated_queue(self) -> None:
        self.fitted()
        with patch("catalog.tasks.app.send_task") as send:
            self.assertGreater(relay_fit(), 0)
        self.assertEqual(InputSnapshot.objects.filter(run__document__type="FIT").count(), 1)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(send.call_args.kwargs["queue"], "fit")

    def test_cancel_queued_fit_releases_reservation(self) -> None:
        fit = self.fitted()
        attach(self.actor.tenant_id, fit.run_id)
        cancel(self.actor.tenant_id, fit.run_id, 0)
        recover_fit(self.actor.tenant_id, fit.run_id)
        self.assertEqual(RuntimeRun.objects.get(pk=fit.run_id).document["status"], "CANCELLED")
        self.assertEqual(Reservation.objects.get(root__run_id=fit.run_id).state, "RELEASED")
        self.assertFalse(ValidationRun.objects.filter(run_id=fit.run_id).exists())

    def test_source_failure_never_submits_results_and_cost_is_settled(self) -> None:
        fit = self.fitted()
        attach(self.actor.tenant_id, fit.run_id)
        with patch("catalog.fit.inspect_research", side_effect=ApiError("UPLOAD_OBJECT_CHANGED", 409)):
            self.assertTrue(fit_tick(str(self.actor.tenant_id), str(fit.run_id), 0))
        self.assertEqual(RuntimeRun.objects.get(pk=fit.run_id).document["status"], "FAILED")
        self.assertFalse(ValidationRun.objects.filter(run_id=fit.run_id).exists())
        self.assertEqual(Reservation.objects.get(root__run_id=fit.run_id).state, "RELEASED")

    def test_expired_queue_does_not_execute_or_leak_reservation(self) -> None:
        from datetime import timedelta
        fit = self.fitted()
        attach(self.actor.tenant_id, fit.run_id)
        RuntimeRun.objects.filter(pk=fit.run_id).update(queue_deadline=db_now() - timedelta(seconds=1))
        recover_fit(self.actor.tenant_id, fit.run_id)
        self.assertEqual(RuntimeRun.objects.get(pk=fit.run_id).document["status"], "FAILED")
        self.assertEqual(Reservation.objects.get(root__run_id=fit.run_id).state, "RELEASED")
