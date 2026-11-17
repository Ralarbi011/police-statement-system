import mimetypes

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from audit.models import AuditLog
from audit.utils import log_action

from . import permissions as perms
from .forms import (
    AssignCaseForm, AttachmentForm, CaseForm, CaseNoteForm, CasePartyForm, CaseStatusForm,
    PersonForm, SignatureForm, StatementForm,
)
from .models import Attachment, Case, CaseParty, PartyRole, Person, Statement, StatementLockedError

A = AuditLog.Action


def _page(request, qs, per_page=25):
    return Paginator(qs, per_page).get_page(request.GET.get("page"))


def _get_case(request, pk):
    case = get_object_or_404(Case.objects.select_related("station"), pk=pk)
    perms.require(perms.can_view_case(request.user, case))
    return case


def _get_statement(request, pk):
    st = get_object_or_404(Statement.objects.select_related("case", "case__station", "person", "recorded_by"), pk=pk)
    perms.require(perms.can_view_case(request.user, st.case))
    return st


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@login_required
def dashboard(request):
    user = request.user
    if user.is_system_admin:
        return redirect("admin:index")
    cases = perms.visible_cases(user)
    counts = {row["status"]: row["n"] for row in cases.values("status").annotate(n=Count("id"))}
    status_cards = [(s, counts.get(s.value, 0)) for s in Case.Status]
    context = {
        "status_cards": status_cards,
        "total_cases": sum(counts.values()),
        "my_cases": cases.filter(assigned_to=user).exclude(status=Case.Status.CLOSED)[:10],
        "recent_cases": cases.select_related("assigned_to")[:10],
        "my_drafts": Statement.objects.filter(
            recorded_by=user, status=Statement.Status.DRAFT, case__in=cases,
        ).select_related("case", "person")[:10],
        "today_statements": Statement.objects.filter(
            case__in=cases, created_at__date=timezone.localdate(),
        ).count(),
        "can_create_case": perms.can_create_case(user),
    }
    return render(request, "records/dashboard.html", context)


# ---------------------------------------------------------------------------
# People
# ---------------------------------------------------------------------------
@login_required
def person_list(request):
    perms.require(perms.can_access_people(request.user))
    q = request.GET.get("q", "").strip()
    people = Person.objects.all()
    if q:
        terms = q.split()
        for t in terms:
            people = people.filter(
                Q(surname__icontains=t) | Q(first_name__icontains=t) | Q(other_names__icontains=t)
                | Q(id_number__icontains=t) | Q(phone__icontains=t)
            )
        log_action(A.SEARCH, details=f"People search: {q}")
    elif not request.user.is_commander:
        # Non-commanders must search; they don't browse the whole registry.
        people = Person.objects.none()
    return render(request, "records/person_list.html", {
        "page": _page(request, people), "q": q, "can_edit": perms.can_edit_people(request.user),
    })


@login_required
def person_create(request):
    perms.require(perms.can_edit_people(request.user))
    case = None
    role = request.GET.get("role") or request.POST.get("link_role")
    if request.GET.get("case") or request.POST.get("link_case"):
        case = _get_case(request, request.GET.get("case") or request.POST.get("link_case"))
        perms.require(perms.can_record_statement(request.user, case))
        if role not in PartyRole.values:
            role = PartyRole.COMPLAINANT
    form = PersonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        person = form.save(commit=False)
        person.created_by = request.user
        person.created_station = request.user.station
        person.save()
        log_action(A.CREATE, person)
        if case:
            party = CaseParty.objects.create(case=case, person=person, role=role, added_by=request.user)
            log_action(A.UPDATE, case, details=f"Added party: {party}")
            messages.success(request, f"{person} registered and added to the case as {party.get_role_display()}.")
            return redirect(case)
        messages.success(request, f"{person} registered.")
        return redirect(person)
    return render(request, "records/person_form.html", {"form": form, "case": case, "role": role})


@login_required
def person_detail(request, pk):
    perms.require(perms.can_access_people(request.user))
    person = get_object_or_404(Person, pk=pk)
    visible = perms.visible_cases(request.user)
    links = person.case_links.filter(case__in=visible).select_related("case")
    statements = person.statements.filter(case__in=visible).select_related("case")
    log_action(A.VIEW, person)
    return render(request, "records/person_detail.html", {
        "person": person, "links": links, "statements": statements,
        "can_edit": perms.can_edit_people(request.user),
        "other_cases_count": person.case_links.exclude(case__in=visible).count(),
    })


@login_required
def person_edit(request, pk):
    perms.require(perms.can_edit_people(request.user))
    person = get_object_or_404(Person, pk=pk)
    form = PersonForm(request.POST or None, instance=person)
    if request.method == "POST" and form.is_valid():
        changed = ", ".join(form.changed_data)
        form.save()
        log_action(A.UPDATE, person, details=f"Changed: {changed}")
        messages.success(request, "Details updated.")
        return redirect(person)
    return render(request, "records/person_form.html", {"form": form, "person": person})


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
@login_required
def case_list(request):
    cases = perms.visible_cases(request.user).select_related("assigned_to", "reporting_officer")
    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "")
    if q:
        cases = cases.filter(
            Q(case_number__icontains=q) | Q(title__icontains=q) | Q(offence__icontains=q)
            | Q(parties__person__surname__icontains=q) | Q(parties__person__first_name__icontains=q)
        ).distinct()
        log_action(A.SEARCH, details=f"Case search: {q}")
    if status in Case.Status.values:
        cases = cases.filter(status=status)
    return render(request, "records/case_list.html", {
        "page": _page(request, cases), "q": q, "status": status, "statuses": Case.Status.choices,
        "can_create_case": perms.can_create_case(request.user),
    })


@login_required
def case_create(request):
    perms.require(perms.can_create_case(request.user))
    form = CaseForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        case = form.save(commit=False)
        case.station = request.user.station
        case.reporting_officer = request.user
        if request.user.is_investigator:
            case.assigned_to = request.user
        case.save()
        log_action(A.CREATE, case)
        messages.success(request, f"Case {case.case_number} opened. Now add the people involved.")
        return redirect(case)
    return render(request, "records/case_form.html", {"form": form})


@login_required
def case_detail(request, pk):
    case = _get_case(request, pk)
    user = request.user
    log_action(A.VIEW, case)
    status_choices = perms.allowed_status_changes(user, case)
    return render(request, "records/case_detail.html", {
        "case": case,
        "parties": case.parties.select_related("person"),
        "statements": case.statements.select_related("person", "recorded_by"),
        "attachments": case.attachments.select_related("uploaded_by", "statement"),
        "notes": case.notes.select_related("author"),
        "can_edit": perms.can_edit_case(user, case),
        "can_record": perms.can_record_statement(user, case),
        "can_assign": perms.can_assign_case(user, case),
        "can_attach": perms.can_add_attachment(user, case),
        "can_note": perms.can_add_note(user, case),
        "assign_form": AssignCaseForm(station=case.station, initial={"assigned_to": case.assigned_to}),
        "status_form": CaseStatusForm(choices=status_choices) if status_choices else None,
        "note_form": CaseNoteForm(),
        "party_roles": PartyRole.choices,
    })


@login_required
def case_edit(request, pk):
    case = _get_case(request, pk)
    perms.require(perms.can_edit_case(request.user, case))
    form = CaseForm(request.POST or None, instance=case)
    if request.method == "POST" and form.is_valid():
        changed = ", ".join(form.changed_data)
        form.save()
        log_action(A.UPDATE, case, details=f"Changed: {changed}")
        messages.success(request, "Case updated.")
        return redirect(case)
    return render(request, "records/case_form.html", {"form": form, "case": case})


@login_required
@require_POST
def case_assign(request, pk):
    case = _get_case(request, pk)
    perms.require(perms.can_assign_case(request.user, case))
    form = AssignCaseForm(request.POST, station=case.station)
    if form.is_valid():
        case.assigned_to = form.cleaned_data["assigned_to"]
        if case.status == Case.Status.REPORTED:
            case.status = Case.Status.UNDER_INVESTIGATION
        case.save()
        log_action(A.ASSIGN, case, details=f"Assigned to {case.assigned_to}")
        messages.success(request, f"Case assigned to {case.assigned_to}.")
    else:
        messages.error(request, "Choose a valid investigator.")
    return redirect(case)


@login_required
@require_POST
def case_status(request, pk):
    case = _get_case(request, pk)
    choices = perms.allowed_status_changes(request.user, case)
    perms.require(choices)
    form = CaseStatusForm(request.POST, choices=choices)
    if form.is_valid():
        old = case.get_status_display()
        case.status = form.cleaned_data["status"]
        reason = form.cleaned_data["reason"].strip()
        if case.status == Case.Status.CLOSED:
            case.closed_at = timezone.now()
            case.closure_reason = reason
        else:
            case.closed_at = None
        case.save()
        log_action(A.STATUS, case, details=f"{old} → {case.get_status_display()}. {reason}".strip())
        messages.success(request, f"Status changed to {case.get_status_display()}.")
    else:
        for err in form.errors.values():
            messages.error(request, err.as_text())
    return redirect(case)


@login_required
def case_add_party(request, pk):
    case = _get_case(request, pk)
    perms.require(perms.can_record_statement(request.user, case))
    if request.method == "POST":
        person = get_object_or_404(Person, pk=request.POST.get("person"))
        form = CasePartyForm(request.POST)
        if form.is_valid():
            party, created = CaseParty.objects.get_or_create(
                case=case, person=person, role=form.cleaned_data["role"],
                defaults={"notes": form.cleaned_data["notes"], "added_by": request.user},
            )
            if created:
                log_action(A.UPDATE, case, details=f"Added party: {party}")
                messages.success(request, f"{person} added as {party.get_role_display()}.")
            else:
                messages.info(request, "That person is already linked with this role.")
            return redirect(case)
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        results = Person.objects.all()
        for t in q.split():
            results = results.filter(
                Q(surname__icontains=t) | Q(first_name__icontains=t) | Q(id_number__icontains=t) | Q(phone__icontains=t)
            )
        results = results[:30]
        log_action(A.SEARCH, details=f"People search (case {case.case_number}): {q}")
    return render(request, "records/case_add_party.html", {
        "case": case, "q": q, "results": results, "party_roles": PartyRole.choices,
    })


@login_required
@require_POST
def case_add_note(request, pk):
    case = _get_case(request, pk)
    perms.require(perms.can_add_note(request.user, case))
    form = CaseNoteForm(request.POST)
    if form.is_valid():
        note = form.save(commit=False)
        note.case, note.author = case, request.user
        note.save()
        log_action(A.UPDATE, case, details="Diary entry added")
        messages.success(request, "Diary entry added.")
    return redirect(case)


# ---------------------------------------------------------------------------
# Statements
# ---------------------------------------------------------------------------
@login_required
def statement_create(request, case_pk):
    case = _get_case(request, case_pk)
    perms.require(perms.can_record_statement(request.user, case))
    party = get_object_or_404(CaseParty.objects.select_related("person"), case=case, pk=request.GET.get("party"))
    parent = None
    if request.GET.get("parent"):
        parent = get_object_or_404(Statement, pk=request.GET["parent"], case=case, person=party.person)

    initial = {"statement_type": party.role, "place_recorded": case.station.name, "started_at": timezone.localtime()}
    if parent:
        initial.update(language=parent.language, interpreter_name=parent.interpreter_name)
    form = StatementForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        st = form.save(commit=False)
        st.case, st.person, st.parent, st.recorded_by = case, party.person, parent, request.user
        st.caution_text = settings.STATEMENT_CAUTION_TEXT if st.caution_administered else ""
        st.declaration_text = Statement.DEFAULT_DECLARATION.format(language=st.language)
        st.save()
        log_action(A.CREATE, st)
        messages.success(request, f"Statement {st.reference} saved as a draft. Read it over to the person, then sign.")
        return redirect(st)
    return render(request, "records/statement_form.html", {
        "form": form, "case": case, "person": party.person, "parent": parent,
        "caution_text": settings.STATEMENT_CAUTION_TEXT,
    })


@login_required
def statement_detail(request, pk):
    st = _get_statement(request, pk)
    log_action(A.VIEW, st)
    return render(request, "records/statement_detail.html", {
        "st": st,
        "integrity_ok": st.verify_integrity() if st.is_locked else None,
        "can_edit": perms.can_edit_statement(request.user, st),
        "can_record": perms.can_record_statement(request.user, st.case),
        "party": st.case.parties.filter(person=st.person).first(),
        "problems": [] if st.is_locked else st.finalization_problems(),
    })


@login_required
def statement_edit(request, pk):
    st = _get_statement(request, pk)
    perms.require(perms.can_edit_statement(request.user, st))
    form = StatementForm(request.POST or None, instance=st)
    if request.method == "POST" and form.is_valid():
        st = form.save(commit=False)
        st.caution_text = settings.STATEMENT_CAUTION_TEXT if st.caution_administered else ""
        st.declaration_text = Statement.DEFAULT_DECLARATION.format(language=st.language)
        try:
            st.save()
        except StatementLockedError as exc:
            messages.error(request, str(exc))
            return redirect(st)
        log_action(A.UPDATE, st, details=f"Draft edited: {', '.join(form.changed_data)}")
        messages.success(request, "Draft updated.")
        return redirect(st)
    return render(request, "records/statement_form.html", {
        "form": form, "case": st.case, "person": st.person, "parent": st.parent, "st": st,
        "caution_text": settings.STATEMENT_CAUTION_TEXT,
    })


@login_required
def statement_sign(request, pk):
    st = _get_statement(request, pk)
    perms.require(perms.can_edit_statement(request.user, st))
    form = SignatureForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        st.deponent_signature = d["deponent_signature"]
        st.deponent_refused_to_sign = d["deponent_refused_to_sign"]
        st.refusal_reason = d["refusal_reason"]
        st.officer_signature = d["officer_signature"]
        st.interpreter_signature = d["interpreter_signature"]
        st.independent_witness_name = d["independent_witness_name"]
        st.independent_witness_signature = d["independent_witness_signature"]
        try:
            st.finalize(request.user)
        except ValidationError as exc:
            for msg in exc.messages:
                form.add_error(None, msg)
        else:
            log_action(A.FINALIZE, st, details=f"SHA-256 {st.content_hash}")
            messages.success(request, f"Statement {st.reference} signed and locked.")
            return redirect(st)
    return render(request, "records/statement_sign.html", {"st": st, "form": form})


@login_required
def statement_print(request, pk):
    st = _get_statement(request, pk)
    log_action(A.PRINT, st)
    return render(request, "records/statement_print.html", {
        "st": st, "integrity_ok": st.verify_integrity() if st.is_locked else None, "printed_at": timezone.now(),
    })


# ---------------------------------------------------------------------------
# Attachments
# ---------------------------------------------------------------------------
@login_required
def attachment_upload(request, case_pk):
    case = _get_case(request, case_pk)
    perms.require(perms.can_add_attachment(request.user, case))
    form = AttachmentForm(request.POST or None, request.FILES or None, case=case)
    if request.method == "POST" and form.is_valid():
        att = form.save(commit=False)
        att.case, att.uploaded_by = case, request.user
        att.original_name = request.FILES["file"].name[:255]
        att.save()
        log_action(A.CREATE, att, details=f"Case {case.case_number}, SHA-256 {att.sha256}")
        messages.success(request, "File uploaded.")
        return redirect(case)
    return render(request, "records/attachment_form.html", {"form": form, "case": case})


@login_required
def attachment_download(request, pk):
    att = get_object_or_404(Attachment.objects.select_related("case"), pk=pk)
    perms.require(perms.can_view_case(request.user, att.case))
    try:
        fh = att.file.open("rb")
    except FileNotFoundError:
        raise Http404("File missing from storage – report to the system administrator.")
    log_action(A.DOWNLOAD, att, details=f"Case {att.case.case_number}")
    content_type = mimetypes.guess_type(att.original_name)[0] or "application/octet-stream"
    return FileResponse(fh, as_attachment=True, filename=att.original_name, content_type=content_type)


def permission_denied(request, exception=None):
    return render(request, "403.html", status=403)


__all__ = ["PermissionDenied"]
