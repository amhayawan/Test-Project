from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = _("Users and roles")

    def ready(self):
        from django.db.models.signals import m2m_changed

        from .models import User

        def roles_grant_backoffice(sender, instance, action, **kwargs):
            # Anyone holding a role may open the back office; their role still limits what they see there.
            if action == "post_add" and isinstance(instance, User) and not instance.is_staff:
                User.objects.filter(pk=instance.pk).update(is_staff=True)
                instance.is_staff = True

        m2m_changed.connect(roles_grant_backoffice, sender=User.groups.through, weak=False,
                            dispatch_uid="roles-backoffice")
