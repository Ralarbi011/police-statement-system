"""
Central access rules. Every view goes through these functions so the rules
live in exactly one place.

Role summary
------------
SUPER_ADMIN   Manages users/stations/audit in the admin site. No access to case content.
COMMANDER     Everything at own station: cases, statements, assignment, closing.
INVESTIGATOR  Cases at own station that are assigned to them or that they reported.
FRONT_DESK    Opens cases and records statements at own station; cannot assign or close.
AUDITOR       Read-only: forwarded/closed cases at own station.
"""
from django.core.exceptions import PermissionDenied
from django.db.models import Q

from accounts.models import Role

from .models import Case

OPERATIONAL_ROLES = {Role.COMMANDER, Role.INVESTIGATOR, Role.FRONT_DESK}


def _active_officer(user):
    return user.is_authenticated and user.is_active and user.station_id is not None


def visible_cases(user):
    if not _active_officer(user) or user.is_system_admin:
        return Case.objects.none()
    qs = Case.objects.filter(station_id=user.station_id)
    if user.role == Role.INVESTIGATOR:
        return qs.filter(Q(assigned_to=user) | Q(reporting_officer=user))
    if user.role == Role.AUDITOR:
        return qs.filter(status__in=[Case.Status.FORWARDED, Case.Status.CLOSED])
    if user.role in (Role.COMMANDER, Role.FRONT_DESK):
        return qs
    return Case.objects.none()


def can_view_case(user, case):
    return visible_cases(user).filter(pk=case.pk).exists()


def can_access_people(user):
    return _active_officer(user) and not user.is_system_admin and (
        user.role in OPERATIONAL_ROLES or user.role == Role.AUDITOR
    )


def can_edit_people(user):
    return _active_officer(user) and user.role in OPERATIONAL_ROLES


def can_create_case(user):
    return _active_officer(user) and user.role in OPERATIONAL_ROLES


def can_edit_case(user, case):
    if case.is_closed or not can_view_case(user, case):
        return False
    return user.role in (Role.COMMANDER, Role.INVESTIGATOR) or (
        user.role == Role.FRONT_DESK and case.status == Case.Status.REPORTED
    )


def can_assign_case(user, case):
    return user.role == Role.COMMANDER and can_view_case(user, case) and not case.is_closed


def allowed_status_changes(user, case):
    """Statuses this user may move the case to."""
    if not can_view_case(user, case):
        return []
    S = Case.Status
    if user.role == Role.COMMANDER:
        return [s for s in S if s != case.status]
    if user.role == Role.INVESTIGATOR and not case.is_closed:
        return [s for s in (S.UNDER_INVESTIGATION, S.FORWARDED) if s != case.status]
    return []


def can_record_statement(user, case):
    return user.role in OPERATIONAL_ROLES and not case.is_closed and can_view_case(user, case)


def can_edit_statement(user, statement):
    """Only the recording officer (or commander) may edit, and only while a draft."""
    if statement.is_locked or statement.case.is_closed or not can_view_case(user, statement.case):
        return False
    return statement.recorded_by_id == user.pk or user.role == Role.COMMANDER


def can_add_attachment(user, case):
    return can_record_statement(user, case)


def can_add_note(user, case):
    return user.role in (Role.COMMANDER, Role.INVESTIGATOR) and not case.is_closed and can_view_case(user, case)


def require(condition):
    if not condition:
        raise PermissionDenied
