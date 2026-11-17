import hashlib
import json
import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

from accounts.models import Station


class StatementLockedError(Exception):
    """Raised when someone tries to modify or delete a finalized statement."""


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
class Person(models.Model):
    class Gender(models.TextChoices):
        MALE = "M", "Male"
        FEMALE = "F", "Female"
        UNKNOWN = "U", "Not stated"

    class IdType(models.TextChoices):
        NATIONAL_ID = "NATIONAL_ID", "National ID card"
        PASSPORT = "PASSPORT", "Passport"
        DRIVERS_LICENCE = "DRIVERS_LICENCE", "Driver's licence"
        VOTER_ID = "VOTER_ID", "Voter ID"
        OTHER = "OTHER", "Other"
        NONE = "NONE", "No ID presented"

    surname = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    other_names = models.CharField(max_length=150, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, default=Gender.UNKNOWN)
    date_of_birth = models.DateField(null=True, blank=True)
    nationality = models.CharField(max_length=60, blank=True)
    id_type = models.CharField(max_length=20, choices=IdType.choices, default=IdType.NONE)
    id_number = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    residential_address = models.TextField(blank=True)
    hometown = models.CharField(max_length=100, blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    education_level = models.CharField(max_length=60, blank=True)

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_station = models.ForeignKey(Station, null=True, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["surname", "first_name"]
        verbose_name_plural = "people"
        constraints = [
            models.UniqueConstraint(
                fields=["id_type", "id_number"],
                condition=~models.Q(id_number=""),
                name="unique_person_id_document",
            )
        ]

    def clean(self):
        self.id_number = self.id_number.strip().upper()
        if self.id_type not in (self.IdType.NONE,) and not self.id_number:
            raise ValidationError({"id_number": "Enter the ID number or choose 'No ID presented'."})
        if self.id_type == self.IdType.NONE:
            self.id_number = ""

    @property
    def full_name(self):
        return " ".join(p for p in [self.first_name, self.other_names, self.surname] if p)

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        today = timezone.localdate()
        dob = self.date_of_birth
        return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))

    def get_absolute_url(self):
        return reverse("person_detail", args=[self.pk])

    def __str__(self):
        return self.full_name


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
class CaseCounter(models.Model):
    """Per-station, per-year sequence used to build case numbers safely."""

    station = models.ForeignKey(Station, on_delete=models.CASCADE)
    year = models.PositiveIntegerField()
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = [("station", "year")]


class Case(models.Model):
    class Status(models.TextChoices):
        REPORTED = "REPORTED", "Reported"
        UNDER_INVESTIGATION = "UNDER_INVESTIGATION", "Under investigation"
        FORWARDED = "FORWARDED", "Forwarded for prosecution"
        CLOSED = "CLOSED", "Closed"

    case_number = models.CharField(max_length=40, unique=True, editable=False)
    station = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="cases")
    title = models.CharField(max_length=200, help_text="Short description, e.g. 'Theft of motorbike at Madina'.")
    offence = models.CharField(max_length=150)
    description = models.TextField(help_text="Summary of the complaint as first reported.")
    occurred_at = models.DateTimeField(null=True, blank=True, help_text="When the incident happened (if known).")
    location = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=25, choices=Status.choices, default=Status.REPORTED, db_index=True)
    reporting_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="reported_cases",
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_cases",
    )
    closure_reason = models.TextField(blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @classmethod
    def next_case_number(cls, station):
        year = timezone.localdate().year
        with transaction.atomic():
            counter, _ = CaseCounter.objects.select_for_update().get_or_create(station=station, year=year)
            counter.last_number += 1
            counter.save(update_fields=["last_number"])
        return f"{station.code}-{year}-{counter.last_number:05d}"

    def save(self, *args, **kwargs):
        if not self.case_number:
            self.case_number = self.next_case_number(self.station)
        super().save(*args, **kwargs)

    @property
    def is_closed(self):
        return self.status == self.Status.CLOSED

    def get_absolute_url(self):
        return reverse("case_detail", args=[self.pk])

    def __str__(self):
        return f"{self.case_number} – {self.title}"


class PartyRole(models.TextChoices):
    COMPLAINANT = "COMPLAINANT", "Complainant"
    VICTIM = "VICTIM", "Victim"
    WITNESS = "WITNESS", "Witness"
    SUSPECT = "SUSPECT", "Suspect"
    ACCUSED = "ACCUSED", "Accused"


class CaseParty(models.Model):
    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="parties")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="case_links")
    role = models.CharField(max_length=20, choices=PartyRole.choices)
    notes = models.CharField(max_length=255, blank=True)
    added_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [("case", "person", "role")]
        ordering = ["role", "added_at"]
        verbose_name_plural = "case parties"

    def __str__(self):
        return f"{self.person} – {self.get_role_display()}"


class CaseNote(models.Model):
    """Investigation diary of action. Append-only."""

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="notes")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    text = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("Case diary entries cannot be edited.")
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------
class Statement(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        FINALIZED = "FINALIZED", "Signed & locked"

    DEFAULT_DECLARATION = (
        "This statement has been read over to me in the {language} language. "
        "I understand it, and it is true and correct to the best of my knowledge and belief."
    )

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="statements")
    person = models.ForeignKey(Person, on_delete=models.PROTECT, related_name="statements")
    statement_type = models.CharField(max_length=20, choices=PartyRole.choices)
    sequence = models.PositiveIntegerField(editable=False, help_text="Statement number within the case.")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="additional_statements",
        help_text="Set when this is an additional statement correcting/adding to an earlier one.",
    )

    language = models.CharField(max_length=60, default="English")
    interpreter_name = models.CharField(max_length=150, blank=True)
    interpreter_contact = models.CharField(max_length=100, blank=True)
    place_recorded = models.CharField(max_length=150, blank=True)
    started_at = models.DateTimeField(default=timezone.now)
    ended_at = models.DateTimeField(null=True, blank=True)

    caution_administered = models.BooleanField(default=False)
    caution_text = models.TextField(blank=True)
    body = models.TextField(help_text="The statement exactly as given.")
    declaration_text = models.TextField(blank=True)

    # Signatures are stored as PNG data URLs so they are part of the hashed record.
    deponent_signature = models.TextField(blank=True)
    deponent_refused_to_sign = models.BooleanField(default=False)
    refusal_reason = models.CharField(max_length=255, blank=True)
    officer_signature = models.TextField(blank=True)
    interpreter_signature = models.TextField(blank=True)
    independent_witness_name = models.CharField(max_length=150, blank=True)
    independent_witness_signature = models.TextField(blank=True)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT, db_index=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="recorded_statements")
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, help_text="SHA-256 of the locked statement.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["case", "sequence"]
        unique_together = [("case", "sequence")]

    # --- immutability -------------------------------------------------------
    def _stored_status(self):
        if not self.pk:
            return None
        return Statement.objects.filter(pk=self.pk).values_list("status", flat=True).first()

    def save(self, *args, **kwargs):
        if self._stored_status() == self.Status.FINALIZED:
            raise StatementLockedError("This statement is signed and locked. Record an additional statement instead.")
        if not self.sequence:
            with transaction.atomic():
                # Lock the parent case row so two officers can't get the same number.
                Case.objects.select_for_update().filter(pk=self.case_id).first()
                last = Statement.objects.filter(case_id=self.case_id).aggregate(m=models.Max("sequence"))["m"] or 0
                self.sequence = last + 1
                super().save(*args, **kwargs)
            return
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self._stored_status() == self.Status.FINALIZED:
            raise StatementLockedError("Signed statements can never be deleted.")
        return super().delete(*args, **kwargs)

    @property
    def is_locked(self):
        return self.status == self.Status.FINALIZED

    @property
    def reference(self):
        return f"{self.case.case_number}/S{self.sequence:02d}"

    # --- integrity ----------------------------------------------------------
    def canonical_payload(self):
        """Everything that makes up the legal content of the statement."""
        fmt = lambda dt: dt.isoformat() if dt else None  # noqa: E731
        return {
            "case_number": self.case.case_number,
            "sequence": self.sequence,
            "parent_id": self.parent_id,
            "person_id": self.person_id,
            "statement_type": self.statement_type,
            "language": self.language,
            "interpreter_name": self.interpreter_name,
            "place_recorded": self.place_recorded,
            "started_at": fmt(self.started_at),
            "ended_at": fmt(self.ended_at),
            "caution_administered": self.caution_administered,
            "caution_text": self.caution_text,
            "body": self.body,
            "declaration_text": self.declaration_text,
            "deponent_signature": self.deponent_signature,
            "deponent_refused_to_sign": self.deponent_refused_to_sign,
            "refusal_reason": self.refusal_reason,
            "officer_signature": self.officer_signature,
            "interpreter_signature": self.interpreter_signature,
            "independent_witness_name": self.independent_witness_name,
            "independent_witness_signature": self.independent_witness_signature,
            "recorded_by_id": self.recorded_by_id,
            "finalized_by_id": self.finalized_by_id,
            "finalized_at": fmt(self.finalized_at),
        }

    def compute_hash(self):
        data = json.dumps(self.canonical_payload(), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def verify_integrity(self):
        return bool(self.content_hash) and self.content_hash == self.compute_hash()

    def finalization_problems(self):
        problems = []
        if not self.body.strip():
            problems.append("The statement text is empty.")
        if self.statement_type in (PartyRole.SUSPECT, PartyRole.ACCUSED) and not self.caution_administered:
            problems.append("A suspect/accused statement requires the caution to be administered.")
        if not self.deponent_signature and not (self.deponent_refused_to_sign and self.refusal_reason.strip()):
            problems.append("The person giving the statement must sign, or a refusal reason must be recorded.")
        if self.deponent_refused_to_sign and not (
            self.independent_witness_name.strip() and self.independent_witness_signature
        ):
            problems.append("When the person refuses to sign, an independent witness must sign.")
        if not self.officer_signature:
            problems.append("The recording officer must sign.")
        if self.interpreter_name.strip() and not self.interpreter_signature:
            problems.append("The interpreter must sign.")
        return problems

    def finalize(self, user):
        problems = self.finalization_problems()
        if problems:
            raise ValidationError(problems)
        now = timezone.now()
        self.ended_at = self.ended_at or now
        self.finalized_by = user
        self.finalized_at = now
        self.status = self.Status.FINALIZED
        self.content_hash = self.compute_hash()
        self.save()

    def get_absolute_url(self):
        return reverse("statement_detail", args=[self.pk])

    def __str__(self):
        return f"{self.reference} – {self.person} ({self.get_statement_type_display()})"


# ---------------------------------------------------------------------------
# Attachments (documents, photos, audio/video recordings)
# ---------------------------------------------------------------------------
def attachment_path(instance, filename):
    ext = os.path.splitext(filename)[1].lower()
    return f"cases/{instance.case.case_number}/{uuid.uuid4().hex}{ext}"


class Attachment(models.Model):
    class Kind(models.TextChoices):
        DOCUMENT = "DOCUMENT", "Document"
        PHOTO = "PHOTO", "Photograph"
        AUDIO = "AUDIO", "Audio recording"
        VIDEO = "VIDEO", "Video recording"
        SCANNED_STATEMENT = "SCANNED_STATEMENT", "Scanned signed statement"
        OTHER = "OTHER", "Other"

    case = models.ForeignKey(Case, on_delete=models.PROTECT, related_name="attachments")
    statement = models.ForeignKey(
        Statement, null=True, blank=True, on_delete=models.PROTECT, related_name="attachments",
    )
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.DOCUMENT)
    file = models.FileField(upload_to=attachment_path)
    original_name = models.CharField(max_length=255)
    description = models.CharField(max_length=255, blank=True)
    size_bytes = models.PositiveBigIntegerField(default=0)
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-uploaded_at"]

    def save(self, *args, **kwargs):
        if self.pk:
            raise PermissionError("Attachments cannot be modified once uploaded.")
        if not self.sha256:
            digest = hashlib.sha256()
            for chunk in self.file.chunks():
                digest.update(chunk)
            self.sha256 = digest.hexdigest()
            self.size_bytes = self.file.size
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Attachments cannot be deleted.")

    def __str__(self):
        return self.original_name
