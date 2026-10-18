# HAZ integrated management system: v2

The new foundation for the association's integrated system: Django 5.2 LTS + PostgreSQL. It is built in phases (see [`../docs/SYSTEM_FRAMEWORK.md`](../docs/SYSTEM_FRAMEWORK.md)). **v1 (the folder above) stays the system in daily use until v2 reaches parity.**

## What exists now (phase 1, step 1: platform core)

| Part | Status |
|---|---|
| Organisation master data: branches, departments / cost centres, projects, funds (unrestricted / restricted / zakat) | ✅ |
| Users and roles (admin, executive director, case manager, field researcher, fundraising officer) with data scopes. Researchers only ever see their assigned cases | ✅ |
| Account lockout (5 wrong passwords → 15 min), 30-minute idle logout, password rules | ✅ |
| **Maker-checker approval engine:** policies per document type and amount, multi-step approvals, maker can never approve their own request, one person per step, reasons required for reject or return, approvals inbox | ✅ |
| Audit trail of every create / update / delete with old → new values, plus logins and approval decisions. Read-only, even for admins | ✅ |
| Official numbering per document type and year (`R-2026-00001` receipts, `C-` cases, `A-` aid) | ✅ |
| Attachments on any record, with file-type checks; access follows the record's own rules | ✅ |
| Arabic (RTL) / English (LTR), switchable per user and remembered | ✅ |
| CRM: donors, donations, **campaigns**, sponsorships, earmarking, zakat-eligibility and zakat-fund rules, volunteers, general-assembly members | ✅ models + back office |
| Cases: research fields, family members, needs, case approval and **aid approval** through the engine (aid ≥ EGP 10,000 needs case manager **and** executive director) | ✅ models + back office |
| **Import from v1**: one command copies all v1 data, keeps passwords, receipt numbers, documents, history, and pending approvals | ✅ |
| Day-to-day screens (like v1's case workspace and forms) | ⏳ next step. For now, use the back office at `/backoffice/` |
| Finance, HR / payroll, supply chain, projects modules | ⏳ later phases |
| Field tablet app | ⏳ phase 3 |
| Cloud deployment (Docker, Egypt-hosted) and Windows desktop client for v2 | ⏳ with the day-to-day screens |

## Running it (developer PC)

```bash
cd v2
pip install -r requirements-dev.txt
python manage.py migrate
python manage.py seed_defaults            # roles, default funds, approval policies
python manage.py createsuperuser
python manage.py import_v1 path/to/v1/crm.db   # optional: bring over all v1 data
HAZ_DEBUG=1 python manage.py runserver
```

Settings come from environment variables (see the top of `haz/settings.py`): `HAZ_DATABASE_URL`, `HAZ_SECRET_KEY`, `HAZ_ALLOWED_HOSTS`, `HAZ_DATA_DIR`, `HAZ_HTTPS`.

## Tests

```bash
python -m pytest -q                                                    # SQLite
HAZ_DATABASE_URL=postgresql://user:pass@localhost/haz_v2 python -m pytest -q   # PostgreSQL
```

CI runs both, checks that no migration is missing, and checks that every phrase has an Arabic translation.

## Translations

Code and templates are written in English; Arabic lives in `locale/ar/LC_MESSAGES/django.po`.

```bash
python tools/i18n.py check     # list phrases without Arabic
python tools/i18n.py compile   # after editing django.po
```

## Layout

| Folder | Contents |
|---|---|
| `haz/` | settings, URLs |
| `accounts/` | users, roles (`roles.py`), login lockout, language preference |
| `core/` | organisation data, numbering, attachments, audit trail, v1 password compatibility, `seed_defaults`, `import_v1` |
| `approvals/` | maker-checker engine (`services.py`), policies, inbox |
| `crm/` | donors, donations, campaigns, sponsorships, volunteers, members |
| `cases/` | cases, family, needs, aid |
