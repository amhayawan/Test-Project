"""Download the fonts the PDF guides use (IBM Plex Sans/Mono, Noto Kufi Arabic; SIL Open Font Licence) into ./fonts."""
import pathlib, re, urllib.request

HERE = pathlib.Path(__file__).parent / "fonts"
CSS = "https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;600;700&family=IBM+Plex+Mono:wght@500&family=Noto+Kufi+Arabic:wght@400;600&display=swap"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

HERE.mkdir(exist_ok=True)
css = urllib.request.urlopen(urllib.request.Request(CSS, headers=UA)).read().decode()
for i, url in enumerate(sorted(set(re.findall(r"url\((https://[^)]+)\)", css)))):
    (HERE / f"f{i}.woff2").write_bytes(urllib.request.urlopen(url).read())
    css = css.replace(url, f"f{i}.woff2")
(HERE / "local.css").write_text(css)
print("fonts saved to", HERE)
