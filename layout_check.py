#!/usr/bin/env python3
"""Rendered layout check for the carousel: loads the built HTML in headless
Chrome, measures every slide's content box, and reports any slide whose
content overflows its fixed 1080px frame.

Usage:
    python layout_check.py site/<date>/carousel.html [--payload site/<date>/notify_payload.json]

Always exits 0 (this is a warning gate, not a build breaker). With --payload,
overflow findings are appended to the notify payload's issues list so the
Telegram message carries the warning.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

PROBE = """
<script>
window.addEventListener('load', function () {
  var bad = [];
  var clamped = ['.headline', '.subline', '.hb-text', '.why-desc',
                 '.lesson-txt', '.cta-head', '.next-box .nt', '.mv-note',
                 '.why-title'];
  for (var i = 1; i <= 8; i++) {
    var s = document.getElementById('slide' + i);
    if (!s) { bad.push('slide' + i + ':missing'); continue; }
    // .body is the flex-constrained content box (min-height:0). The slide
    // root is skipped on purpose: the decorative ghost watermark overhangs
    // it by design and would false-positive every dark slide.
    var el = s.querySelector('.body');
    if (el && el.scrollHeight > el.clientHeight + 6) {
      bad.push('slide' + i + ':overflow');
      continue;
    }
    // clamped elements hide spillover instead of overflowing - a larger
    // scrollHeight means the reader is missing words
    var cut = false;
    for (var c = 0; c < clamped.length; c++) {
      var nodes = s.querySelectorAll(clamped[c]);
      for (var n = 0; n < nodes.length; n++) {
        if (nodes[n].scrollHeight > nodes[n].clientHeight + 6) {
          cut = true; break;
        }
      }
      if (cut) break;
    }
    if (cut) bad.push('slide' + i + ':clipped');
  }
  document.title = bad.length ? 'LAYOUT_FAIL:' + bad.join(',') : 'LAYOUT_OK';
});
</script>
</body>"""


def find_chrome():
    for name in ("google-chrome", "google-chrome-stable", "chromium",
                 "chromium-browser", "chrome"):
        p = shutil.which(name)
        if p:
            return p
    return None


def check(html_path):
    chrome = find_chrome()
    if not chrome:
        return None, "no chrome/chromium binary found - check skipped"
    raw = open(html_path, encoding="utf-8").read()
    if "</body>" not in raw:
        return None, "no </body> in html - check skipped"
    probed = raw.replace("</body>", PROBE, 1)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False,
                                     encoding="utf-8") as f:
        f.write(probed)
        tmp = f.name
    try:
        out = subprocess.run(
            [chrome, "--headless=new", "--disable-gpu", "--no-sandbox",
             "--virtual-time-budget=8000", "--dump-dom", "file://" + tmp],
            capture_output=True, text=True, timeout=120).stdout
    finally:
        os.unlink(tmp)
    m = re.search(r"<title>(LAYOUT_[^<]*)</title>", out or "")
    if not m:
        return None, "probe did not report (JS blocked?) - check skipped"
    result = m.group(1)
    if result == "LAYOUT_OK":
        return [], "ok"
    return result.split(":", 1)[1].split(","), "overflow detected"


def main():
    html_path = sys.argv[1]
    payload_path = None
    if "--payload" in sys.argv:
        payload_path = sys.argv[sys.argv.index("--payload") + 1]
    slides, msg = check(html_path)
    if slides is None:
        print(f"[layout] {msg}")
        return
    if not slides:
        print("[layout] all 8 slides fit their frames")
        return
    issue = ("layout overflow on " + ", ".join(sorted(set(slides))) +
             " - text may be clipped; review before posting")
    print(f"[layout] WARNING: {issue}")
    if payload_path and os.path.exists(payload_path):
        p = json.load(open(payload_path, encoding="utf-8"))
        p.setdefault("issues", []).append(issue)
        with open(payload_path, "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False)
        print("[layout] warning added to notify payload")


if __name__ == "__main__":
    main()
