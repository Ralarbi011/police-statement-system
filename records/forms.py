import base64
import binascii
import os

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model

from accounts.models import Role

from .models import Attachment, Case, CaseNote, CaseParty, Person, Statement

User = get_user_model()

DATETIME_WIDGET = forms.DateTimeInput(attrs={"type": "datetime-local"}, format="%Y-%m-%dT%H:%M")
MAX_SIGNATURE_BYTES = 300 * 1024


class BootstrapMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                widget.attrs.setdefault("class", "form-check-input")
            elif isinstance(widget, (forms.Select, forms.SelectMultiple)):
                widget.attrs.setdefault("class", "form-select")
            elif not isinstance(widget, forms.HiddenInput):
                widget.attrs.setdefault("class", "form-control")


class PersonForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Person
        fields = [
            "surname", "first_name", "other_names", "gender", "date_of_birth", "nationality",
            "id_type", "id_number", "phone", "email", "residential_address", "hometown",
            "occupation", "education_level",
        ]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "residential_address": forms.Textarea(attrs={"rows": 2}),
        }


class CaseForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Case
        fields = ["title", "offence", "description", "occurred_at", "location"]
        widgets = {"occurred_at": DATETIME_WIDGET, "description": forms.Textarea(attrs={"rows": 5})}


class AssignCaseForm(BootstrapMixin, forms.Form):
    assigned_to = forms.ModelChoiceField(queryset=User.objects.none(), label="Assign to investigator")

    def __init__(self, *args, station=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["assigned_to"].queryset = User.objects.filter(
            station=station, is_active=True, role__in=[Role.INVESTIGATOR, Role.COMMANDER],
        )


class CaseStatusForm(BootstrapMixin, forms.Form):
    status = forms.ChoiceField()
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False,
                             help_text="Required when closing a case.")

    def __init__(self, *args, choices=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["status"].choices = [(c.value, c.label) for c in choices]

    def clean(self):
        data = super().clean()
        if data.get("status") == Case.Status.CLOSED and not data.get("reason", "").strip():
            self.add_error("reason", "Give the reason for closing this case.")
        return data


class CasePartyForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CaseParty
        fields = ["role", "notes"]


class CaseNoteForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CaseNote
        fields = ["text"]
        widgets = {"text": forms.Textarea(attrs={"rows": 3, "placeholder": "Action taken / progress…"})}
        labels = {"text": "Diary entry"}


class StatementForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Statement
        fields = [
            "statement_type", "language", "interpreter_name", "interpreter_contact",
            "place_recorded", "started_at", "ended_at", "caution_administered", "body",
        ]
        widgets = {
            "started_at": DATETIME_WIDGET,
            "ended_at": DATETIME_WIDGET,
            "body": forms.Textarea(attrs={"rows": 18, "class": "form-control statement-body"}),
        }
        labels = {"caution_administered": "The caution was administered and understood"}

    def clean(self):
        data = super().clean()
        start, end = data.get("started_at"), data.get("ended_at")
        if start and end and end < start:
            self.add_error("ended_at", "End time cannot be before the start time.")
        return data


def _validate_signature(value, label):
    if not value:
        return ""
    prefix = "data:image/png;base64,"
    if not value.startswith(prefix):
        raise forms.ValidationError(f"{label}: invalid signature data.")
    try:
        raw = base64.b64decode(value[len(prefix):], validate=True)
    except (binascii.Error, ValueError):
        raise forms.ValidationError(f"{label}: invalid signature data.")
    if not raw.startswith(b"\x89PNG") or len(raw) > MAX_SIGNATURE_BYTES:
        raise forms.ValidationError(f"{label}: invalid or oversized signature image.")
    return value


class SignatureForm(BootstrapMixin, forms.Form):
    deponent_signature = forms.CharField(widget=forms.HiddenInput, required=False)
    deponent_refused_to_sign = forms.BooleanField(required=False, label="The person refused to sign")
    refusal_reason = forms.CharField(required=False, max_length=255)
    officer_signature = forms.CharField(widget=forms.HiddenInput, required=False)
    interpreter_signature = forms.CharField(widget=forms.HiddenInput, required=False)
    independent_witness_name = forms.CharField(required=False, max_length=150)
    independent_witness_signature = forms.CharField(widget=forms.HiddenInput, required=False)
    confirm_read_over = forms.BooleanField(
        required=True,
        label="I confirm the statement was read over to the person, who agreed it is correct (or refused to sign).",
    )

    def clean(self):
        data = super().clean()
        labels = {
            "deponent_signature": "Person's signature",
            "officer_signature": "Officer's signature",
            "interpreter_signature": "Interpreter's signature",
            "independent_witness_signature": "Witness's signature",
        }
        for field, label in labels.items():
            try:
                data[field] = _validate_signature(data.get(field, ""), label)
            except forms.ValidationError as exc:
                self.add_error(None, exc)
        return data


class AttachmentForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Attachment
        fields = ["kind", "file", "description", "statement"]

    def __init__(self, *args, case=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["statement"].queryset = case.statements.all() if case else Statement.objects.none()
        self.fields["statement"].required = False
        self.fields["statement"].label = "Related statement (optional)"

    def clean_file(self):
        f = self.cleaned_data["file"]
        ext = os.path.splitext(f.name)[1].lower().lstrip(".")
        if ext not in settings.ALLOWED_ATTACHMENT_EXTENSIONS:
            raise forms.ValidationError(
                "File type not allowed. Allowed: " + ", ".join(settings.ALLOWED_ATTACHMENT_EXTENSIONS)
            )
        if f.size > settings.MAX_ATTACHMENT_SIZE_MB * 1024 * 1024:
            raise forms.ValidationError(f"File is larger than {settings.MAX_ATTACHMENT_SIZE_MB} MB.")
        return f
