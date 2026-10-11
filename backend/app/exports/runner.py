import json
import os
import sys
from pathlib import Path

from app.exports.render import html_document, markdown_zip


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    target = Path(request["target"])
    result = {}
    try:
        if request["format"] == "markdown":
            target.write_bytes(markdown_zip(request["content"], request["evidence"]))
        else:
            html = html_document(request["content"], request["evidence"])
            if request["format"] == "html":
                target.write_text(html, encoding="utf-8")
            else:
                from playwright.sync_api import sync_playwright

                with sync_playwright() as p:
                    executable = os.environ.get("PDF_CHROMIUM_PATH") or None
                    browser = p.chromium.launch(
                        executable_path=executable,
                        headless=True,
                        args=["--disable-background-networking", "--disable-dev-shm-usage"],
                    )
                    context = browser.new_context(
                        java_script_enabled=False, service_workers="block", offline=True
                    )
                    context.route("**/*", lambda route: route.abort())
                    page = context.new_page()
                    page.set_content(html, wait_until="load", timeout=30000)
                    # Font readiness is evaluated by automation, not by untrusted page scripts.
                    page.evaluate("document.fonts.ready")
                    page.pdf(
                        path=str(target),
                        format="A4",
                        print_background=True,
                        prefer_css_page_size=True,
                        display_header_footer=True,
                        header_template="<span></span>",
                        footer_template='<div style="font-size:9px;width:100%;text-align:center">'
                        'ShopPulse · <span class="pageNumber"></span> / '
                        '<span class="totalPages"></span></div>',
                    )
                    browser.close()
    except Exception:
        result = {"error": "EXPORT_RENDER_FAILED"}
        target.unlink(missing_ok=True)
    Path(sys.argv[2]).write_text(json.dumps(result), encoding="utf-8")


if __name__ == "__main__":
    main()
