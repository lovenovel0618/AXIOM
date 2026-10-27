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
from catalog.management.commands.bootstrap_account import ACCOUNTS_VARIABLE, TENANT_VARIABLE


def accounts(*pairs: tuple[str, str]) -> str:
    """把 (user, password) 清單編成 AXIOM_BOOTSTRAP_ACCOUNTS 的 JSON 陣列。"""
    return json.dumps([{"user": user, "password": password} for user, password in pairs])


def report(output: StringIO) -> dict[str, object]:
    """命令輸出為單一 JSON 物件；測試只讀已輸出的欄位。"""
    return cast(dict[str, object], json.loads(output.getvalue()))


class BootstrapAccountTests(TestCase):
    def run_bootstrap(self, variables: dict[str, str]) -> dict[str, object]:
        output = StringIO()
        with mock.patch.dict(os.environ, variables, clear=False):
            call_command("bootstrap_account", stdout=output)
        return report(output)

    def account_statuses(self, result: dict[str, object]) -> dict[str, object]:
        rows = cast(list[dict[str, object]], result["accounts"])
        return {cast(str, row["username"]): row["status"] for row in rows}

    def test_blank_accounts_skips_without_writing(self) -> None:
        result = self.run_bootstrap({ACCOUNTS_VARIABLE: "", TENANT_VARIABLE: ""})
        self.assertEqual(result["status"], "SKIPPED")
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Tenant.objects.count(), 0)

    def test_malformed_configuration_is_rejected(self) -> None:
        rejected = [
            "not-json",
            '{"user": "bootstrap-user", "password": "Bootstrap-Local-2026"}',
            "[]",
            '[{"user": "bootstrap-user", "secret": "Bootstrap-Local-2026"}]',
            '[{"user": "bootstrap-user", "password": "too-short"}]',
            accounts(("bootstrap-user", "Bootstrap-Local-2026"), ("bootstrap-user", "Other-Local-Secret-2026")),
        ]
        for value in rejected:
            with self.assertRaises(CommandError):
                self.run_bootstrap({ACCOUNTS_VARIABLE: value})
        self.assertEqual(User.objects.count(), 0)
        self.assertEqual(Tenant.objects.count(), 0)

    def test_all_accounts_share_one_tenant_and_creation_is_idempotent(self) -> None:
        variables = {
            ACCOUNTS_VARIABLE: accounts(("admin", "Admin-Local-2026"), ("dino", "Bootstrap-Local-2026")),
            TENANT_VARIABLE: "bootstrap-local",
        }
        created = self.run_bootstrap(variables)
        self.assertEqual(created["status"], "APPLIED")
        self.assertEqual(self.account_statuses(created), {"admin": "CREATED", "dino": "CREATED"})
        tenant = Tenant.objects.get(name="bootstrap-local")
        self.assertEqual(Account.objects.filter(tenant=tenant).count(), 2)
        self.assertTrue(User.objects.get(username="admin").check_password("Admin-Local-2026"))
        self.assertTrue(User.objects.get(username="dino").check_password("Bootstrap-Local-2026"))
        self.assertEqual(Audit.objects.filter(action="BOOTSTRAP_ACCOUNT").count(), 2)

        dino = User.objects.get(username="dino")
        dino.set_password("Changed-On-Host-2026")
        dino.save()
        again = self.run_bootstrap(variables)
        self.assertEqual(self.account_statuses(again), {"admin": "EXISTS", "dino": "EXISTS"})
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(Account.objects.count(), 2)
        self.assertEqual(Audit.objects.filter(action="BOOTSTRAP_ACCOUNT").count(), 2)
        self.assertTrue(User.objects.get(username="dino").check_password("Changed-On-Host-2026"))

    def test_existing_user_without_account_is_repaired(self) -> None:
        User.objects.create_user(username="dino", password="Bootstrap-Local-2026")
        result = self.run_bootstrap({
            ACCOUNTS_VARIABLE: accounts(("dino", "Other-Local-Secret-2026")),
            TENANT_VARIABLE: "bootstrap-local",
        })
        self.assertEqual(self.account_statuses(result), {"dino": "REPAIRED"})
        user = User.objects.get(username="dino")
        self.assertTrue(user.check_password("Bootstrap-Local-2026"))
        self.assertEqual(Account.objects.get(user=user).tenant_id, Tenant.objects.get(name="bootstrap-local").id)
        self.assertEqual(Audit.objects.filter(action="BOOTSTRAP_ACCOUNT").count(), 1)
