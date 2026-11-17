import base64
import struct
import tempfile
import zlib

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import Role, Station, User
from audit.models import AuditLog

from .models import Attachment, Case, CaseParty, PartyRole, Person, Statement, StatementLockedError


def tiny_png_data_url():
    """A valid 1x1 PNG, used as a signature in tests."""
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode()


SIG = tiny_png_data_url()
PASSWORD = "Str0ng-test-pass!"


class BaseTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.station = Station.objects.create(name="Central Police Station", code="cen")
        cls.other_station = Station.objects.create(name="North Police Station", code="NTH")

        def make(username, role, station):
            u = User(username=username, role=role, station=station, first_name=username.title(), last_name="Officer")
            u.set_password(PASSWORD)
            u.save()
            return u

        cls.admin = make("sysadmin", Role.SUPER_ADMIN, None)
        cls.commander = make("commander", Role.COMMANDER, cls.station)
        cls.investigator = make("investigator", Role.INVESTIGATOR, cls.station)
        cls.investigator2 = make("investigator2", Role.INVESTIGATOR, cls.station)
        cls.frontdesk = make("frontdesk", Role.FRONT_DESK, cls.station)
        cls.auditor = make("auditor", Role.AUDITOR, cls.station)
        cls.outsider = make("outsider", Role.COMMANDER, cls.other_station)

        cls.person = Person.objects.create(
            surname="Mensah", first_name="Kofi", id_type=Person.IdType.NATIONAL_ID, id_number="GHA-123",
            created_by=cls.frontdesk, created_station=cls.station,
        )
        cls.case = Case.objects.create(
            station=cls.station, title="Theft of phone", offence="Stealing", description="Phone stolen at market",
            reporting_officer=cls.frontdesk, assigned_to=cls.investigator,
        )
        cls.party = CaseParty.objects.create(case=cls.case, person=cls.person, role=PartyRole.COMPLAINANT,
                                             added_by=cls.frontdesk)

    def new_statement(self, **kw):
        data = dict(case=self.case, person=self.person, statement_type=PartyRole.COMPLAINANT,
                    body="I was at the market when...", recorded_by=self.frontdesk)
        data.update(kw)
        return Statement.objects.create(**data)

    def sign(self, st):
        st.deponent_signature = SIG
        st.officer_signature = SIG
        st.finalize(self.frontdesk)
        return st


class CaseNumberTests(BaseTestCase):
    def test_case_numbers_are_sequential_per_station(self):
        c2 = Case.objects.create(station=self.station, title="t", offence="o", description="d",
                                 reporting_officer=self.frontdesk)
        c3 = Case.objects.create(station=self.other_station, title="t", offence="o", description="d",
                                 reporting_officer=self.outsider)
        self.assertTrue(self.case.case_number.startswith("CEN-"))
        self.assertTrue(self.case.case_number.endswith("00001"))
        self.assertTrue(c2.case_number.endswith("00002"))
        self.assertTrue(c3.case_number.startswith("NTH-") and c3.case_number.endswith("00001"))

    def test_statement_sequence_within_case(self):
        a, b = self.new_statement(), self.new_statement()
        self.assertEqual((a.sequence, b.sequence), (1, 2))
        self.assertEqual(a.reference, f"{self.case.case_number}/S01")


class StatementLockingTests(BaseTestCase):
    def test_cannot_finalize_without_signatures(self):
        st = self.new_statement()
        with self.assertRaises(ValidationError):
            st.finalize(self.frontdesk)

    def test_suspect_statement_requires_caution(self):
        st = self.new_statement(statement_type=PartyRole.SUSPECT)
        st.deponent_signature = st.officer_signature = SIG
        with self.assertRaises(ValidationError) as ctx:
            st.finalize(self.frontdesk)
        self.assertIn("caution", " ".join(ctx.exception.messages))

    def test_refusal_to_sign_requires_independent_witness(self):
        st = self.new_statement(deponent_refused_to_sign=True, refusal_reason="Declined", officer_signature=SIG)
        with self.assertRaises(ValidationError):
            st.finalize(self.frontdesk)
        st.independent_witness_name, st.independent_witness_signature = "Ama Owusu", SIG
        st.finalize(self.frontdesk)
        self.assertTrue(st.is_locked)

    def test_finalized_statement_cannot_be_edited_or_deleted(self):
        st = self.sign(self.new_statement())
        st.body = "changed"
        with self.assertRaises(StatementLockedError):
            st.save()
        with self.assertRaises(StatementLockedError):
            Statement.objects.get(pk=st.pk).delete()

    def test_integrity_hash_detects_tampering(self):
        st = self.sign(self.new_statement())
        self.assertTrue(Statement.objects.get(pk=st.pk).verify_integrity())
        # Simulate someone bypassing the application and editing the DB directly.
        Statement.objects.filter(pk=st.pk).update(body="Tampered text")
        self.assertFalse(Statement.objects.get(pk=st.pk).verify_integrity())


class AuditLogTests(BaseTestCase):
    def test_audit_entries_are_immutable(self):
        entry = AuditLog.objects.create(action=AuditLog.Action.VIEW, username="x")
        entry.details = "edited"
        with self.assertRaises(PermissionError):
            entry.save()
        with self.assertRaises(PermissionError):
            entry.delete()

    def test_login_and_failed_login_are_logged(self):
        self.client.post(reverse("login"), {"username": "frontdesk", "password": "wrong"})
        self.client.post(reverse("login"), {"username": "frontdesk", "password": PASSWORD})
        actions = list(AuditLog.objects.filter(username="frontdesk").values_list("action", flat=True))
        self.assertIn(AuditLog.Action.LOGIN_FAILED, actions)
        self.assertIn(AuditLog.Action.LOGIN, actions)


class AccessControlTests(BaseTestCase):
    def get_as(self, user, url):
        self.client.force_login(user)
        return self.client.get(url)

    def test_login_required(self):
        resp = self.client.get(reverse("case_detail", args=[self.case.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_role_visibility_of_case(self):
        url = reverse("case_detail", args=[self.case.pk])
        self.assertEqual(self.get_as(self.commander, url).status_code, 200)
        self.assertEqual(self.get_as(self.frontdesk, url).status_code, 200)
        self.assertEqual(self.get_as(self.investigator, url).status_code, 200)   # assigned
        self.assertEqual(self.get_as(self.investigator2, url).status_code, 403)  # not assigned
        self.assertEqual(self.get_as(self.outsider, url).status_code, 403)       # other station
        self.assertEqual(self.get_as(self.admin, url).status_code, 403)          # sys admin: no case content
        self.assertEqual(self.get_as(self.auditor, url).status_code, 403)        # not yet forwarded

    def test_auditor_sees_forwarded_case_read_only(self):
        Case.objects.filter(pk=self.case.pk).update(status=Case.Status.FORWARDED)
        self.assertEqual(self.get_as(self.auditor, reverse("case_detail", args=[self.case.pk])).status_code, 200)
        resp = self.client.get(reverse("statement_create", args=[self.case.pk]) + f"?party={self.party.pk}")
        self.assertEqual(resp.status_code, 403)

    def test_only_commander_can_assign_and_close(self):
        url = reverse("case_assign", args=[self.case.pk])
        self.client.force_login(self.frontdesk)
        self.assertEqual(self.client.post(url, {"assigned_to": self.investigator2.pk}).status_code, 403)
        self.client.force_login(self.commander)
        self.client.post(url, {"assigned_to": self.investigator2.pk})
        self.case.refresh_from_db()
        self.assertEqual(self.case.assigned_to, self.investigator2)

        status_url = reverse("case_status", args=[self.case.pk])
        self.client.post(status_url, {"status": Case.Status.CLOSED, "reason": ""})
        self.case.refresh_from_db()
        self.assertNotEqual(self.case.status, Case.Status.CLOSED)  # reason required
        self.client.post(status_url, {"status": Case.Status.CLOSED, "reason": "Withdrawn by complainant"})
        self.case.refresh_from_db()
        self.assertEqual(self.case.status, Case.Status.CLOSED)

    def test_super_admin_is_staff_others_are_not(self):
        self.assertTrue(self.admin.is_staff)
        self.assertFalse(self.commander.is_staff)


class StatementWorkflowTests(BaseTestCase):
    def test_full_flow_create_sign_print(self):
        self.client.force_login(self.frontdesk)
        resp = self.client.post(
            reverse("statement_create", args=[self.case.pk]) + f"?party={self.party.pk}",
            {"statement_type": PartyRole.COMPLAINANT, "language": "Twi", "interpreter_name": "",
             "place_recorded": "CID office", "started_at": "2026-11-17T09:00", "body": "My phone was taken."},
        )
        st = Statement.objects.get(case=self.case)
        self.assertRedirects(resp, st.get_absolute_url())
        self.assertIn("Twi", st.declaration_text)

        sign_url = reverse("statement_sign", args=[st.pk])
        resp = self.client.post(sign_url, {"officer_signature": SIG, "confirm_read_over": "on"})
        self.assertEqual(resp.status_code, 200)  # missing deponent signature
        st.refresh_from_db()
        self.assertFalse(st.is_locked)

        resp = self.client.post(sign_url, {"deponent_signature": SIG, "officer_signature": SIG, "confirm_read_over": "on"})
        st.refresh_from_db()
        self.assertTrue(st.is_locked)
        self.assertTrue(st.verify_integrity())
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.FINALIZE, object_id=str(st.pk)).exists())

        # Locked: edit is forbidden, print works and is audited.
        self.assertEqual(self.client.get(reverse("statement_edit", args=[st.pk])).status_code, 403)
        self.assertEqual(self.client.get(reverse("statement_print", args=[st.pk])).status_code, 200)
        self.assertTrue(AuditLog.objects.filter(action=AuditLog.Action.PRINT, object_id=str(st.pk)).exists())

    def test_rejects_non_png_signature(self):
        st = self.new_statement()
        self.client.force_login(self.frontdesk)
        self.client.post(reverse("statement_sign", args=[st.pk]), {
            "deponent_signature": "data:image/png;base64,PHNjcmlwdD4=", "officer_signature": SIG, "confirm_read_over": "on",
        })
        st.refresh_from_db()
        self.assertFalse(st.is_locked)

    def test_other_officer_cannot_edit_someone_elses_draft(self):
        st = self.new_statement()
        self.client.force_login(self.investigator)
        self.assertEqual(self.client.get(reverse("statement_edit", args=[st.pk])).status_code, 403)


@override_settings(MEDIA_ROOT=tempfile.mkdtemp())
class AttachmentTests(BaseTestCase):
    def test_upload_hash_and_protected_download(self):
        self.client.force_login(self.frontdesk)
        f = SimpleUploadedFile("photo.jpg", b"fake-jpeg-bytes", content_type="image/jpeg")
        self.client.post(reverse("attachment_upload", args=[self.case.pk]), {"kind": "PHOTO", "file": f, "description": "Scene"})
        att = Attachment.objects.get(case=self.case)
        self.assertEqual(len(att.sha256), 64)
        self.assertEqual(self.client.get(reverse("attachment_download", args=[att.pk])).status_code, 200)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("attachment_download", args=[att.pk])).status_code, 403)

    def test_disallowed_extension_rejected(self):
        self.client.force_login(self.frontdesk)
        f = SimpleUploadedFile("run.exe", b"MZ", content_type="application/octet-stream")
        self.client.post(reverse("attachment_upload", args=[self.case.pk]), {"kind": "OTHER", "file": f})
        self.assertFalse(Attachment.objects.exists())


class PageSmokeTests(BaseTestCase):
    """Every page renders without template errors for an operational user."""

    def test_all_pages_render(self):
        st = self.sign(self.new_statement(interpreter_name="Yaw Boateng", interpreter_signature=SIG))
        draft = self.new_statement()
        self.client.force_login(self.commander)
        urls = [
            reverse("dashboard"), reverse("case_list"), reverse("case_list") + "?q=phone&status=REPORTED",
            reverse("case_create"), reverse("case_detail", args=[self.case.pk]), reverse("case_edit", args=[self.case.pk]),
            reverse("case_add_party", args=[self.case.pk]) + "?q=mensah",
            reverse("person_list"), reverse("person_list") + "?q=kofi", reverse("person_create"),
            reverse("person_create") + f"?case={self.case.pk}&role=WITNESS",
            reverse("person_detail", args=[self.person.pk]), reverse("person_edit", args=[self.person.pk]),
            reverse("statement_create", args=[self.case.pk]) + f"?party={self.party.pk}",
            reverse("statement_create", args=[self.case.pk]) + f"?party={self.party.pk}&parent={st.pk}",
            reverse("statement_detail", args=[st.pk]), reverse("statement_detail", args=[draft.pk]),
            reverse("statement_edit", args=[draft.pk]), reverse("statement_sign", args=[draft.pk]),
            reverse("statement_print", args=[st.pk]), reverse("statement_print", args=[draft.pk]),
            reverse("attachment_upload", args=[self.case.pk]), reverse("password_change"),
        ]
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.client.force_login(self.admin)
        self.assertRedirects(self.client.get(reverse("dashboard")), reverse("admin:index"))
        self.assertEqual(self.client.get(reverse("admin:index")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:audit_auditlog_changelist")).status_code, 200)


class SuperAdminScopeTests(BaseTestCase):
    def test_super_admin_manages_users_but_not_case_content(self):
        self.assertTrue(self.admin.has_perm("accounts.add_user"))
        self.assertTrue(self.admin.has_perm("audit.view_auditlog"))
        self.assertFalse(self.admin.has_perm("records.view_statement"))
        self.assertFalse(self.commander.has_perm("accounts.add_user"))
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("admin:accounts_user_add")).status_code, 200)
        self.assertEqual(self.client.get(reverse("admin:accounts_station_changelist")).status_code, 200)
