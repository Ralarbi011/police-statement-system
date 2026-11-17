from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from accounts.models import Role, Station, User


class Command(BaseCommand):
    help = "Create a demo station and one user per role (DEVELOPMENT / TRAINING ONLY)."

    def add_arguments(self, parser):
        parser.add_argument("--password", required=True, help="Password given to every demo account.")

    def handle(self, *args, password, **options):
        if not settings.DEBUG:
            raise CommandError("Refusing to create demo accounts when DEBUG is off (production).")
        station, _ = Station.objects.get_or_create(
            code="DEMO", defaults={"name": "Demo Police Station", "region": "Demo Region", "district": "Demo District"},
        )
        demo = [
            ("admin", Role.SUPER_ADMIN, None, "System", "Admin", ""),
            ("commander", Role.COMMANDER, station, "Ama", "Asante", "Supt."),
            ("investigator", Role.INVESTIGATOR, station, "Kwame", "Owusu", "D/Insp."),
            ("frontdesk", Role.FRONT_DESK, station, "Efua", "Mensah", "Sgt."),
            ("auditor", Role.AUDITOR, station, "Yaw", "Boateng", ""),
        ]
        for username, role, st, first, last, rank in demo:
            user, created = User.objects.get_or_create(
                username=username,
                defaults={"role": role, "station": st, "first_name": first, "last_name": last, "rank": rank},
            )
            user.set_password(password)
            user.save()
            self.stdout.write(f"{'Created' if created else 'Updated'} {username} ({user.get_role_display()})")
        self.stdout.write(self.style.SUCCESS("Demo data ready."))
