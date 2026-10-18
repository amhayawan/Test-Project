# نظام إدارة علاقات جمعية حسن عباس زكي — HAZ-CRM

A Windows desktop CRM for the Hassan Abbas Zaki Association. Arabic, right-to-left, and works fully offline.

## What it manages

| Module | Arabic | Key features |
|---|---|---|
| Donors | المتبرعون | Individuals and companies, with each donor's full giving history and total |
| Donations | التبرعات | Automatic receipt numbers (`R-2026-00001`), purpose (zakat, sadaqa, orphans…), payment method (cash, InstaPay, wallet…), printable receipt |
| Beneficiaries | المستفيدون / الحالات | 14-digit national ID check, duplicate national IDs blocked, category, family size, income, case status (under study / approved / rejected / suspended) |
| Aid disbursed | المساعدات المصروفة | Linked to each beneficiary, with their total aid received |
| Volunteers | المتطوعون | Skills, availability, status |
| General-assembly members | أعضاء الجمعية العمومية | Membership no., dues paid-until year, members behind on dues flagged on the dashboard |
| Dashboard | لوحة التحكم | Donations this month and year, aid disbursed, monthly donations vs aid, totals by purpose |

Also included:
- Search on every list, plus **Export to Excel** (CSV with Arabic encoding preserved).
- Users with two roles. **Admin** can delete records, manage users, download backups, and view the audit log. **Staff** can add and edit records.
- **Security features:** an audit log (سجل العمليات) of every login and every add, edit, or delete, with old and new values. Five failed logins lock the account for 15 minutes. Sessions time out after 30 minutes. Passwords need at least 8 characters.
- **Automatic daily backups** (the last 30 are kept), plus a one-click backup download.
- **Choice of database:** a local file (SQLite) or a cloud PostgreSQL database. → **[docs/DATABASE_AND_SECURITY.md](docs/DATABASE_AND_SECURITY.md)** explains which to choose and how to set up each.

## Running it on Windows

1. Download the files from the latest **Build Windows app** run in this repo's GitHub **Actions** tab (under *Artifacts*). There are two:
   - `HAZ-CRM.exe`: the desktop program, for a single PC.
   - `HAZ-CRM-Server.exe`: the office server. Other PCs open it in a browser.
2. Double-click it. On first run, create the admin account.
3. Data is stored in `%APPDATA%\HAZ-CRM\crm.db` on that PC.

Requirements: Windows 10 or 11. The window uses Microsoft Edge WebView2, which both already include.

### Several PCs sharing the same data

Pick one PC as the server and run `HAZ-CRM-Server.exe` on it.

It shows an address such as `http://192.168.1.20:8080`. Open that address in a browser on the other office PCs. Keep the server PC on and its window open. You may need to allow the app through Windows Firewall the first time.

> ⚠️ If each PC runs `HAZ-CRM.exe` on its own, each PC keeps its **own separate data**. Choose one setup and stick with it.

For access from home, branches, or several places, use the cloud setup (HTTPS + PostgreSQL via Docker). See [docs/DATABASE_AND_SECURITY.md](docs/DATABASE_AND_SECURITY.md).

### Options

```
HAZ-CRM.exe [--server] [--port 8080] [--data D:\HAZ-CRM-Data]
            [--database-url postgresql://user:pass@host/db] [--backup-dir E:\Backups]
            [--migrate-to postgresql://...]
```

- `--data`: the folder for the local database, settings, and backups.
- `--backup-dir`: where daily backups go. Point it at a USB drive or a synced folder.
- `--database-url`: use a PostgreSQL database instead of the local file. You can also put this in `settings.ini`.
- `--migrate-to`: copy all data into another, empty database, then exit.

## Building the .exe yourself

Every push runs the GitHub Actions workflow `.github/workflows/build-windows.yml`, which tests, builds, and smoke-tests the exe on Windows. To build locally on a Windows PC with Python 3.12, run:

```
build_windows.bat
```

## Development (any OS)

```
pip install -r requirements-dev.txt
python -m pytest                       # SQLite only
HAZ_TEST_PG_URL=postgresql://postgres@localhost/hazcrm_test python -m pytest   # also PostgreSQL
python haz_crm.py            # desktop window (falls back to the browser if pywebview isn't installed)
python haz_crm.py --server   # browser / network mode
```

Code layout: `crm/models.py` holds the database tables. `crm/entities.py` holds the fields, Arabic labels, and dropdown choices; add or change a field there plus its column in `models.py`. `crm/app.py` holds the routes. `crm/storage.py` handles database selection, backups, and migration. `crm/templates/` holds the pages.
