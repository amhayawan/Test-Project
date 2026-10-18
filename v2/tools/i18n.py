"""Collect translatable text and compile the Arabic translation (no gettext tools needed).

    python tools/i18n.py check     # list English phrases that have no Arabic translation yet
    python tools/i18n.py compile   # write locale/ar/LC_MESSAGES/django.mo from django.po

Source text is English in the code ( _("...") / {% translate "..." %} ); Arabic lives in
locale/ar/LC_MESSAGES/django.po.
"""
import re
import sys
from pathlib import Path

from babel.messages.catalog import Catalog
from babel.messages.mofile import write_mo
from babel.messages.pofile import read_po, write_po

ROOT = Path(__file__).resolve().parent.parent
PO = ROOT / "locale" / "ar" / "LC_MESSAGES" / "django.po"
MO = PO.with_suffix(".mo")
SKIP = {"migrations", "tests", "tools", "data"}

PY = re.compile(r"""\b_\(\s*(?P<q>["'])(?P<s>(?:\\.|(?!(?P=q)).)*)(?P=q)\s*[,)]""")
TPL = re.compile(r"""\{%\s*translate\s+(?P<q>["'])(?P<s>.*?)(?P=q)""")
BLOCK = re.compile(r"""\{%\s*blocktranslate[^%]*%\}(?P<s>.*?)\{%\s*endblocktranslate\s*%\}""", re.S)


def collect():
    found = {}
    for path in ROOT.rglob("*"):
        if any(part in SKIP for part in path.relative_to(ROOT).parts) or not path.is_file():
            continue
        if path.suffix == ".py":
            text = path.read_text(encoding="utf-8")
            for m in PY.finditer(text):
                found.setdefault(m.group("s").encode().decode("unicode_escape"), str(path.relative_to(ROOT)))
        elif path.suffix == ".html":
            text = path.read_text(encoding="utf-8")
            for m in TPL.finditer(text):
                found.setdefault(m.group("s"), str(path.relative_to(ROOT)))
            for m in BLOCK.finditer(text):
                s = re.sub(r"\{\{\s*(\w+)\s*\}\}", r"%(\1)s", m.group("s"))
                found.setdefault(s, str(path.relative_to(ROOT)))
    return found


def load():
    if PO.exists():
        with PO.open("rb") as fh:
            return read_po(fh, locale="ar")
    return Catalog(locale="ar")


def main(cmd):
    catalog = load()
    found = collect()
    for msgid, where in found.items():
        if msgid not in catalog:
            catalog.add(msgid, "", locations=[(where, 0)])
    missing = [m.id for m in catalog if m.id and not m.string and m.id in found]
    PO.parent.mkdir(parents=True, exist_ok=True)
    with PO.open("wb") as fh:
        write_po(fh, catalog, width=0, sort_output=True)
    if cmd == "check":
        for m in missing:
            print(m)
        print(f"{len(found)} phrases, {len(missing)} without Arabic", file=sys.stderr)
        return 1 if missing else 0
    with MO.open("wb") as fh:
        write_mo(fh, catalog)
    print(f"compiled {MO.relative_to(ROOT)} ({len(found) - len(missing)} translated, {len(missing)} missing)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "check"))
