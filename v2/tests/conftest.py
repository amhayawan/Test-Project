import pytest
from django.contrib.auth.models import Group
from django.core.management import call_command


@pytest.fixture(autouse=True)
def _media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path / "media"


@pytest.fixture
def seeded(db):
    import io
    call_command("seed_defaults", stdout=io.StringIO())
    return True


@pytest.fixture
def make_user(seeded, django_user_model):
    def make(username, *roles, staff=False):
        user = django_user_model.objects.create_user(username, "", "Str0ng-pass!", name_ar=username)
        user.is_staff = staff
        user.save()
        for role in roles:
            user.groups.add(Group.objects.get(name=role))
        return django_user_model.objects.get(pk=user.pk)  # fresh permission cache
    return make


@pytest.fixture(autouse=True)
def _fast_passwords(settings):
    # Real installs use PBKDF2; tests use a fast hasher (and keep the v1 importer hasher).
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher",
                                 "core.hashers.WerkzeugImportedHasher"]
