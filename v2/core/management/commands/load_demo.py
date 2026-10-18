"""Fill an EMPTY database with FICTIONAL demo data across every module, one login per role.

Each module contributes <app>/demo.py with run(ctx), called in INSTALLED_APPS order; ctx carries
what earlier modules created (users, departments, projects...). All people, amounts and rules are
invented. Sample tax / insurance / leave figures are labelled SAMPLE and are not legal values.
"""
import random
from importlib import import_module
from types import SimpleNamespace

from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

PASSWORD = "Demo@2026"


class Command(BaseCommand):
    help = "Load fictional demo data into an empty database."

    def handle(self, *args, **options):
        if get_user_model().objects.exists():
            raise CommandError("The database already has users. Demo data only goes into an empty database.")
        call_command("seed_defaults", verbosity=0)
        ctx = SimpleNamespace(today=timezone.localdate(), rng=random.Random(2026), password=PASSWORD,
                              users={}, out=self.stdout)
        with transaction.atomic():
            for cfg in apps.get_app_configs():
                try:
                    module = import_module(f"{cfg.name}.demo")
                except ModuleNotFoundError:
                    continue
                module.run(ctx)
                self.stdout.write(f"  {cfg.verbose_name}: ✓")
        (settings.DATA_DIR / "DEMO").write_text("Fictional demo data. Not for real use.\n", encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Demo data loaded. Password for every login: {PASSWORD}"))
        for username, (label, _user) in ctx.users.items():
            self.stdout.write(f"  {username:<14} {label}")
