"""真實 PostgreSQL 下的公式版本落庫：身分去重、租戶分區與不可改寫防線。"""
from collections.abc import Callable
from uuid import UUID, uuid4
from django.contrib.auth.models import User
from django.db import IntegrityError, connection, transaction
from django.test import TransactionTestCase
from catalog.equations import document_for, register, registered
from catalog.models import Account, EquationVersion, Tenant
from catalog.validation import ApiError
from mathematics.compiler import Plan, compile_dsl
from runtime.contracts import JsonObject, canonical_bytes, identity_hash
from runtime.records import db_now

DOMAIN: list[JsonObject] = [{"name": "x", "lower": {"numerator": "-10", "denominator": "1"},
    "upper": {"numerator": "10", "denominator": "1"}, "lower_closed": True, "upper_closed": True}]


def plan(coefficient: str) -> Plan:
    """固定形狀的已知公式；只有常數值不同，用來驗證身分與去重。"""
    document: JsonObject = {"dsl_version": "1.0", "variables": [{"name": "x", "unit": [0]*7}],
        "parameters": [{"name": "c0", "unit": [0]*7, "lower": coefficient, "upper": coefficient}], "domain": DOMAIN,
        "root": {"op": "add", "args": [{"op": "param", "name": "c0"}, {"op": "var", "name": "x"}]}}
    return compile_dsl(canonical_bytes(document))


def enforce(action: Callable[[], object]) -> None:
    with transaction.atomic():
        action()
        connection.check_constraints()


class EquationVersionTests(TransactionTestCase):
    def setUp(self) -> None:
        self.tenant = Tenant.objects.create(name="equation-synthetic")
        self.other_tenant = Tenant.objects.create(name="equation-other")
        self.actor = self.account(self.tenant)
        self.other = self.account(self.other_tenant)
        self.plan = plan("1")

    def account(self, tenant: Tenant) -> Account:
        user = User.objects.create(username=uuid4().hex, password="!")
        return Account.objects.create(user=user, tenant=tenant)

    def test_registration_is_immutable_and_a_repeat_fit_reads_the_same_row(self) -> None:
        created = db_now()
        first = register(self.actor, self.plan, created)
        second = register(self.actor, self.plan, created)
        self.assertEqual(EquationVersion.objects.count(), 1)
        self.assertEqual((first.id, second.id), (first.id, first.id))
        self.assertEqual((first.identity_hash, first.dsl_version), (self.plan.identity_hash, "1.0"))
        self.assertEqual(first.document, second.document)
        self.assertEqual(first.document["identity_hash"], identity_hash(first.document["dsl"]))
        read_back = registered(self.tenant.id, self.plan.identity_hash)
        self.assertEqual(read_back.id, first.id)
        self.assertEqual(read_back.document["dsl"], first.document["dsl"])

    def test_tenants_do_not_share_an_identity_and_unknown_hashes_are_not_found(self) -> None:
        mine = register(self.actor, self.plan, db_now())
        theirs = register(self.other, self.plan, db_now())
        self.assertNotEqual(mine.id, theirs.id)
        self.assertEqual(EquationVersion.objects.count(), 2)
        with self.assertRaises(ApiError) as missing:
            registered(self.tenant.id, "0" * 64)
        self.assertEqual((missing.exception.code, missing.exception.status), ("NOT_FOUND", 404))
        self.assertEqual(registered(self.other_tenant.id, self.plan.identity_hash).id, theirs.id)

    def test_database_rejects_a_document_that_disagrees_with_its_columns(self) -> None:
        identity, created = uuid4(), db_now()
        document = document_for(identity, self.tenant.id, self.plan, created)
        broken: list[JsonObject] = [document | {"kind": "Candidate"}, document | {"schema_version": "1.0"},
            document | {"identity_hash": "0" * 64}, document | {"dsl": document["dsl"] | {"dsl_version": "2.0"}},
            document | {"created_at": "2000-01-01T00:00:00+00:00"}]
        for index, candidate in enumerate(broken):
            with self.subTest(index=index):
                with self.assertRaises(IntegrityError):
                    enforce(lambda: EquationVersion.objects.create(id=identity, tenant_id=self.tenant.id, created_at=created,
                        identity_hash=self.plan.identity_hash, dsl_version="1.0", document=candidate))
        with self.assertRaises(IntegrityError):
            enforce(lambda: EquationVersion.objects.create(id=identity, tenant_id=self.tenant.id, created_at=created,
                identity_hash="0" * 64, dsl_version="1.0", document=document))
        self.assertFalse(EquationVersion.objects.exists())

    def test_database_rejects_duplicate_identity_and_unknown_dsl_version(self) -> None:
        register(self.actor, self.plan, db_now())
        other_row = uuid4(), db_now()
        with self.assertRaises(IntegrityError):
            enforce(lambda: EquationVersion.objects.create(id=other_row[0], tenant_id=self.tenant.id, created_at=other_row[1],
                identity_hash=self.plan.identity_hash, dsl_version="1.0", document=document_for(other_row[0], self.tenant.id, self.plan, other_row[1])))
        with self.assertRaises(IntegrityError):
            enforce(lambda: EquationVersion.objects.create(id=uuid4(), tenant_id=self.tenant.id, created_at=db_now(),
                identity_hash=self.plan.identity_hash, dsl_version="9.9", document=document_for(uuid4(), self.tenant.id, self.plan, db_now())))

    def test_database_rejects_any_update_or_delete(self) -> None:
        row = register(self.actor, self.plan, db_now())
        rows = EquationVersion.objects.filter(pk=row.id)
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.update(dsl_version="1.0"))
        with self.assertRaises(IntegrityError):
            enforce(lambda: rows.delete())
        self.assertEqual(EquationVersion.objects.get(pk=row.id).identity_hash, self.plan.identity_hash)
        self.assertNotEqual(register(self.actor, plan("2"), db_now()).identity_hash, row.identity_hash)

    def test_different_formulas_are_stored_as_different_identities(self) -> None:
        first = register(self.actor, plan("1"), db_now())
        second = register(self.actor, plan("2"), db_now())
        self.assertNotEqual(first.identity_hash, second.identity_hash)
        self.assertEqual(EquationVersion.objects.count(), 2)
        self.assertEqual(UUID(str(second.document["id"])), second.id)
