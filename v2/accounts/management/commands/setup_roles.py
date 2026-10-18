from fnmatch import fnmatch

from django.contrib.auth.models import Group, Permission
from django.core.management.base import BaseCommand

from accounts.roles import ROLES


class Command(BaseCommand):
    help = "Create or refresh the standard roles (groups) and their permissions."

    def handle(self, *args, **options):
        all_perms = list(Permission.objects.select_related("content_type"))
        for code, (_label, patterns) in ROLES.items():
            group, _created = Group.objects.get_or_create(name=code)
            chosen = [p for p in all_perms
                      if any(fnmatch(f"{p.content_type.app_label}.{p.codename}", pat) for pat in patterns)]
            group.permissions.set(chosen)
            self.stdout.write(f"{code}: {len(chosen)} permissions")
