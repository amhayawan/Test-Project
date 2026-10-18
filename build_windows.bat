@echo off
REM Build HAZ-CRM.exe on a Windows PC (needs Python 3.12 installed).
python -m pip install -r requirements-dev.txt || goto :error
python -m pytest -q || goto :error
python -m PyInstaller --noconfirm --clean --onefile --windowed --name HAZ-CRM ^
  --add-data "crm/templates;crm/templates" --add-data "crm/static;crm/static" ^
  haz_crm.py || goto :error
echo.
echo Done: dist\HAZ-CRM.exe
goto :eof
:error
echo Build failed.
exit /b 1
