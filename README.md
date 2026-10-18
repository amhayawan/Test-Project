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
- Users with two roles. **Admin** can delete records, manage users, and download backups. **Staff** can add and edit records.
- Each donation and aid record stores which user entered it.
- A one-click **backup** (نسخة احتياطية) downloads a copy of the database.

## Running it on Windows

1. Download `HAZ-CRM.exe` from the latest **Build Windows app** run in this repo's GitHub **Actions** tab (under *Artifacts*).
2. Double-click it. On first run, create the admin account.
3. Data is stored in `%APPDATA%\HAZ-CRM\crm.db` on that PC.

Requirements: Windows 10 or 11. The window uses Microsoft Edge WebView2, which both already include.

### Several PCs sharing the same data

Pick one PC as the server and run:

```
HAZ-CRM.exe --server
```

It prints an address such as `http://192.168.1.20:8080`. Open that address in a browser on the other office PCs. Keep the server PC on and its window open. You may need to allow the app through Windows Firewall the first time.

> ⚠️ Without `--server`, each PC keeps its **own separate data**. Choose one mode and stick with it.

### Options

```
HAZ-CRM.exe [--server] [--port 8080] [--data D:\HAZ-CRM-Data]
```

`--data` sets the database folder. Use it to keep the data on a drive that gets backed up.

## Building the .exe yourself

Every push runs the GitHub Actions workflow `.github/workflows/build-windows.yml`, which tests, builds, and smoke-tests the exe on Windows. To build locally on a Windows PC with Python 3.12, run:

```
build_windows.bat
```

## Development (any OS)

```
pip install -r requirements-dev.txt
python -m pytest
python haz_crm.py            # desktop window (falls back to the browser if pywebview isn't installed)
python haz_crm.py --server   # browser / network mode
```

Code layout: `crm/models.py` holds the database tables. `crm/entities.py` holds the fields, Arabic labels, and dropdown choices; add or change a field there plus its column in `models.py`. `crm/app.py` holds the routes, and `crm/templates/` holds the pages.
