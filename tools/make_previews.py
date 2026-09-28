"""Build a self-contained preview of the real UI (design/preview-current.html).

Inlines app.css + fonts + the preview mock + app.js into one file so it opens
anywhere without the app or earbuds. (style-A/B/C-*.html in design/ are the
original three candidates the user chose from and are kept as a record.)

    .venv\\Scripts\\python.exe tools\\make_previews.py
"""

from __future__ import annotations

import base64
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UI = ROOT / "src" / "wireless_limitless" / "ui"
OUT = ROOT / "design"

def build() -> list[Path]:
    html = (UI / "index.html").read_text(encoding="utf-8")
    css = (UI / "app.css").read_text(encoding="utf-8")
    js = (UI / "app.js").read_text(encoding="utf-8")
    mock = (Path(__file__).with_name("preview_mock.js")).read_text(encoding="utf-8")

    # Fonts are referenced relative to ui/; embed them so the preview is portable.
    for font in sorted((UI / "fonts").glob("*.woff2")):
        data = base64.b64encode(font.read_bytes()).decode("ascii")
        css = css.replace(f'url("fonts/{font.name}")', f'url("data:font/woff2;base64,{data}")')

    # The preview is a static document; drop the app CSP so inline code runs.
    head_csp_start = html.index('<meta http-equiv="Content-Security-Policy"')
    head_csp_end = html.index(">", head_csp_start) + 1
    base = html[:head_csp_start] + html[head_csp_end:]
    base = base.replace('<link rel="stylesheet" href="app.css">', f"<style>\n{css}\n</style>")
    base = base.replace('<script src="app.js"></script>', f"<script>\n{mock}\n</script>\n<script>\n{js}\n</script>")

    OUT.mkdir(exist_ok=True)
    path = OUT / "preview-current.html"
    path.write_text(base, encoding="utf-8")
    written = [path]
    return written


if __name__ == "__main__":
    for p in build():
        print(p.relative_to(ROOT))
