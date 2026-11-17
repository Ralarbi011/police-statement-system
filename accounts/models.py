from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models


class Station(models.Model):
    name = models.CharField(max_length=150, unique=True)
    code = models.CharField(
        max_length=12, unique=True,
        help_text="Short unique code used in case numbers, e.g. ACC-CEN.",
    )
    region = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.code})"


class Role(models.TextChoices):
    SUPER_ADMIN = "SUPER_ADMIN", "Super Administrator"
    COMMANDER = "COMMANDER", "Station Commander"
    INVESTIGATOR = "INVESTIGATOR", "Investigator"
    FRONT_DESK = "FRONT_DESK", "Front Desk / Charge Office"
    AUDITOR = "AUDITOR", "Auditor / Prosecutor (read-only)"


class User(AbstractUser):
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.FRONT_DESK)
    station = models.ForeignKey(
        Station, null=True, blank=True, on_delete=models.PROTECT, related_name="officers",
        help_text="Required for every role except Super Administrator.",
    )
    service_number = models.CharField(max_length=30, unique=True, null=True, blank=True)
    rank = models.CharField(max_length=60, blank=True)
    phone = models.CharField(max_length=30, blank=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def clean(self):
        super().clean()
        if self.role != Role.SUPER_ADMIN and not self.is_superuser and not self.station_id:
            raise ValidationError({"station": "Officers must be attached to a station."})

    def save(self, *args, **kwargs):
        if self.service_number == "":
            self.service_number = None
        # Only system administrators may enter the Django admin site.
        self.is_staff = self.is_superuser or self.role == Role.SUPER_ADMIN
        super().save(*args, **kwargs)

    # --- admin-site permissions ---------------------------------------------
    # Super Administrators manage users, stations, the audit trail and login
    # lockouts (axes). They get NO permissions on case content ("records").
    ADMIN_APP_LABELS = {"accounts", "audit", "axes"}

    def has_perm(self, perm, obj=None):
        if self.is_active and self.role == Role.SUPER_ADMIN and perm.split(".", 1)[0] in self.ADMIN_APP_LABELS:
            return True
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        if self.is_active and self.role == Role.SUPER_ADMIN and app_label in self.ADMIN_APP_LABELS:
            return True
        return super().has_module_perms(app_label)

    # --- role helpers -------------------------------------------------------
    @property
    def is_system_admin(self):
        return self.is_superuser or self.role == Role.SUPER_ADMIN

    @property
    def is_commander(self):
        return self.role == Role.COMMANDER

    @property
    def is_investigator(self):
        return self.role == Role.INVESTIGATOR

    @property
    def is_front_desk(self):
        return self.role == Role.FRONT_DESK

    @property
    def is_auditor(self):
        return self.role == Role.AUDITOR

    @property
    def display_name(self):
        name = self.get_full_name() or self.username
        return f"{self.rank} {name}".strip()

    def __str__(self):
        sn = f" [{self.service_number}]" if self.service_number else ""
        return f"{self.display_name}{sn}"
