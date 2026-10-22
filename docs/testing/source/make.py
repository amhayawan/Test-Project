"""Build one printable PDF test guide per demo login from ../protocol.html.

    python fetch_fonts.py     # once
    python make.py            # writes ../pdf/HAZ-v2 test guide NN - <login>.pdf

Needs: pip install playwright && playwright install chromium (or set CHROMIUM to a Chromium binary).
"""
import os, pathlib, tempfile
from playwright.sync_api import sync_playwright

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE.parent / "pdf"
ORDER = ["director", "admin", "researcher1", "researcher2", "casemanager", "projects", "pm", "fundraiser",
         "procurement", "storekeeper", "accountant", "finmanager", "hrofficer", "hrmanager", "payroll", "sara"]

build = (HERE / "build.js").read_text(encoding="utf-8")

with sync_playwright() as pw, tempfile.TemporaryDirectory(dir=HERE) as tmp:
    tmp = pathlib.Path(tmp)
    (tmp / "fonts").symlink_to(HERE / "fonts", target_is_directory=True)
    browser = pw.chromium.launch(executable_path=os.environ.get("CHROMIUM") or None)
    src = browser.new_page()
    src.goto((HERE.parent / "protocol.html").as_uri())
    pg = browser.new_page()
    OUT.mkdir(exist_ok=True)
    for i, login in enumerate(ORDER, 1):
        f = tmp / f"{login}.html"
        f.write_text(src.evaluate(build, login), encoding="utf-8")
        pg.goto(f.as_uri()); pg.wait_for_load_state("networkidle"); pg.evaluate("document.fonts.ready")
        foot = ('<div style="font:7pt sans-serif;color:#5b6b63;width:100%;padding:0 13mm;display:flex;'
                f'justify-content:space-between"><span>HAZ-v2 test guide · {login}</span><span>Page '
                '<span class="pageNumber"></span> of <span class="totalPages"></span></span></div>')
        pg.pdf(path=str(OUT / f"HAZ-v2 test guide {i:02d} - {login}.pdf"), format="A4", print_background=True,
               display_header_footer=True, header_template="<span></span>", footer_template=foot,
               prefer_css_page_size=True)
        print("written", login)
    browser.close()
