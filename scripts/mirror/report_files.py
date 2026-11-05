"""Read-only online copy: the report documents its pages link to (scripts/mirror/build.sh, step 4).

Some figures link to the copy of a report that Paladex kept when it read it (/api/reports/<id>/file),
because the publisher's own address is reused for the next issue (the USDA National Honey Report
"latest" PDF is overwritten every month). On the computer the application serves that kept file;
the online copy has no application behind it, so each such link found in the recorded answers is
served from a file of the copy instead:

    python report_files.py http://127.0.0.1:PORT SITE_DIR > redirect-rules.txt

  * the kept document is saved as SITE_DIR/files/report-<id>.<ext>, exactly as downloaded, and the
    rule "/api/reports/<id>/file  /files/report-<id>.<ext>  200" serves it at the same address;
  * when no copy was kept, the application answers with the publisher's address (HTTP 307) and the
    rule sends the visitor there, as the application itself would.

Only official documents the application already publishes on its pages are copied (never anything
private: quotes, alerts and settings have no files). Prints the Netlify rules on stdout.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

LINK = re.compile(r"/api/reports/(\d+)/file")
EXT = {
    "application/pdf": "pdf", "text/html": "html", "text/plain": "txt", "text/csv": "csv",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
MAX_BYTES = 25 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):  # noqa: D401 - keep the 307 as the answer
        return None


def main(base: str, site: Path) -> int:
    ids: set[int] = set()
    for f in sorted((site / "mirror").glob("*.json")):
        ids.update(int(m) for m in LINK.findall(f.read_text(encoding="utf-8", errors="replace")))
    opener = urllib.request.build_opener(_NoRedirect)
    out = site / "files"
    rules: list[str] = []
    for rid in sorted(ids):
        url = f"{base.rstrip('/')}/api/reports/{rid}/file"
        try:
            with opener.open(url, timeout=60) as r:
                ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
                body = r.read(MAX_BYTES + 1)
        except urllib.error.HTTPError as e:
            loc = e.headers.get("location") if e.code in (301, 302, 303, 307, 308) else None
            if loc and loc.startswith(("https://", "http://")):
                rules.append(f"/api/reports/{rid}/file  {loc}  302")
            else:
                print(f"report {rid}: HTTP {e.code}, not in the copy", file=sys.stderr)
            continue
        if len(body) > MAX_BYTES:
            print(f"report {rid}: larger than {MAX_BYTES // 1024 ** 2} MB, not in the copy", file=sys.stderr)
            continue
        name = f"report-{rid}.{EXT.get(ctype, 'bin')}"
        out.mkdir(exist_ok=True)
        (out / name).write_bytes(body)
        rules.append(f"/api/reports/{rid}/file  /files/{name}  200")
    print("\n".join(rules))
    print(json.dumps({"report_links": len(ids), "served": len(rules)}), file=sys.stderr)
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    sys.exit(main(sys.argv[1], Path(sys.argv[2])))
