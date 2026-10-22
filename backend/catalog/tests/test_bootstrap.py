"""重建後帳號 bootstrap 的冪等與 Fail-Closed 契約；不經 HTTP 直接驗命令行為。"""
import json
from io import StringIO
import os
from typing import cast
from unittest import mock
from django.contrib.auth.models import User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from catalog.models import Account, Audit, Tenant
from catalog.management.commands.bootstrap_account import PASSWORD_VARIABLE, TENANT_VARIABLE, USER_VARIABLE


def report(output: StringIO) -> dict[str, object]:
    """命令輸出為單一 JSON 物件；測試只讀已輸出的欄位。"""
    return cast(dict[str, object], json.loads(output.getvalue()))


class BootstrapAccountTests(TestCase):
    def run_bootstrap(self, variables: dict[str, str]) -> dict[str, object]:
        output = StringIO()
        with mock.patch.dict(os.environ, variables, clear=False):
            call_command("bootstrap_account", stdout=output)
        return report(output)

    def test_blank_user_skips_without_writing(self) -> None:
        result = self.run_bootstrap({USER_VARIABLE: "", PASSWORD_VARIABLE: "", TENANT_VARIABLE: ""})
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Tenant.objects.count(), 0)

    def test_missing_or_short_password_is_rejected(self) -> None:
        for password in ("", "too-short"):
            with self.assertRaises(CommandError):
                self.run_bootstrap({USER_VARIABLE: "bootstrap-user", PASSWORD_VARIABLE: password})
        self.assertEqual(User.objects.count(), 0)

    def test_create_is_idempotent_and_keeps_a_changed_password(self) -> None:
        variables = {USER_VARIABLE: "bootstrap-user", PASSWORD_VARIABLE: "Bootstrap-Local-2026", TENANT_VARIABLE: "bootstrap-local"}
        created = self.run_bootstrap(variables)
        self.assertEqual(created["status"], "CREATED")
        user = User.objects.get(username="bootstrap-user")
        self.assertTrue(user.is_active)
        self.assertTrue(user.check_password("Bootstrap-Local-2026"))
        self.assertEqual(Account.objects.get(user=user).enabled, True)
        self.assertEqual(Tenant.objects.get(name="bootstrap-local").id, Account.objects.get(user=user).tenant_id)
        self.assertEqual(Audit.objects.filter(action="BOOTSTRAP_ACCOUNT").count(), 1)
        user.set_password("Changed-On-Host-2026")
        user.save()
        again = self.run_bootstrap(variables)
        self.assertEqual(again["status"], "EXISTS")
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(Account.objects.count(), 1)
        self.assertEqual(Audit.objects.filter(action="BOOTSTRAP_ACCOUNT").count(), 1)
        self.assertTrue(User.objects.get(username="bootstrap-user").check_password("Changed-On-Host-2026"))

    def test_existing_user_without_account_is_repaired(self) -> None:
        User.objects.create_user(username="bootstrap-user", password="Bootstrap-Local-2026")
        result = self.run_bootstrap({USER_VARIABLE: "bootstrap-user", PASSWORD_VARIABLE: "Other-Local-Secret-2026", TENANT_VARIABLE: "bootstrap-local"})
        self.assertEqual(result["status"], "REPAIRED")
        user = User.objects.get(username="bootstrap-user")
        self.assertTrue(user.check_password("Bootstrap-Local-2026"))
        self.assertEqual(Account.objects.get(user=user).tenant_id, Tenant.objects.get(name="bootstrap-local").id)
        self.assertEqual(Audit.objects.filter(action="BOOTSTRAP_ACCOUNT").count(), 1)
