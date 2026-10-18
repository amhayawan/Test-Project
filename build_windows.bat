@echo off
REM Build HAZ-CRM.exe on a Windows PC (needs Python 3.12 installed).
python -m pip install -r requirements-dev.txt || goto :error
python -m pytest -q || goto :error
python -m PyInstaller --noconfirm --clean --onefile --windowed --name HAZ-CRM ^
  --add-data "crm/templates;crm/templates" --add-data "crm/static;crm/static" ^
  --collect-all psycopg_binary --hidden-import psycopg_binary ^
  haz_crm.py || goto :error
python -m PyInstaller --noconfirm --onefile --console --name HAZ-CRM-Server ^
  --add-data "crm/templates;crm/templates" --add-data "crm/static;crm/static" ^
  --collect-all psycopg_binary --hidden-import psycopg_binary ^
  haz_crm.py || goto :error
echo.
echo Done: dist\HAZ-CRM.exe (desktop) and dist\HAZ-CRM-Server.exe (office server)
goto :eof
:error
echo Build failed.
exit /b 1
