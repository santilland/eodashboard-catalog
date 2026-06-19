#!/usr/bin/env python3

import os
import sys
import json
import argparse
import requests
import html
import urllib3
import random
import time
from curl_cffi import requests as cffi_requests
from datetime import datetime, timezone
from urllib.parse import urlparse
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib3.exceptions import InsecureRequestWarning

urllib3.disable_warnings(InsecureRequestWarning)

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
COLLECTIONS_PATH = REPO_ROOT / "collections"
INDICATORS_PATH = REPO_ROOT / "indicators"
OUTPUT_HTML = SCRIPT_DIR / "link_check_report.html"

# History
HISTORY_DIR = Path(os.environ.get("HISTORY_DIR", REPO_ROOT / "health_history"))
HISTORY_PREFIX = "health_report_"

TIMEOUT = 10
MAX_WORKERS = 20

RUN_URL = os.environ.get("GITHUB_RUN_URL", "")


# -------------------------------------------------------------------
# Normalize URL
# -------------------------------------------------------------------
def normalize(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url.strip())
    if not url.startswith("http"):
        return ""
    p = urlparse(url)
    netloc = p.netloc.lower().replace("www.", "")
    path = p.path.rstrip("/")
    return f"{netloc}{path}"


# -------------------------------------------------------------------
# Browser-like request helpers (bypass naive bot detection)
# -------------------------------------------------------------------
UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.5 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) "
    "Gecko/20100101 Firefox/127.0",
]


def browser_headers(url: str, ua: str) -> dict:
    parsed = urlparse(url)

    return {
        "User-Agent": ua,
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/avif,"
            "image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Sec-Fetch-User": "?1",
        "Upgrade-Insecure-Requests": "1",
        "Referer": f"{parsed.scheme}://{parsed.netloc}/",
        "DNT": "1",
        # Only request first byte
        "Range": "bytes=0-0",
    }


def _do_request(url, ua, use_cffi=False):
    headers = browser_headers(url, ua)

    if use_cffi:
        return cffi_requests.get(
            url,
            headers=headers,
            allow_redirects=True,
            timeout=TIMEOUT,
            verify=False,
            impersonate="chrome124",
        )

    session = requests.Session()

    return session.get(
        url,
        headers=headers,
        allow_redirects=True,
        timeout=TIMEOUT,
        verify=False,
    )


# -------------------------------------------------------------------
# Check URL
# -------------------------------------------------------------------
def check_url(task):
    file_key, name, url = task

    last_status = "ERR"
    last_final = url

    attempts = [
        (False, UAS[0]),
        (False, UAS[1]),
        (True, UAS[0]),
    ]

    for i, (use_cffi, ua) in enumerate(attempts):
        try:
            r = _do_request(
                url,
                ua,
                use_cffi=use_cffi,
            )

            last_final = str(r.url)

            status = 200 if r.status_code == 206 else r.status_code

            last_status = status

            if status not in (
                403,
                405,
                429,
                503,
            ):
                return (
                    file_key,
                    name,
                    last_final,
                    status,
                )

        except Exception:
            last_status = "ERR"

        if i < len(attempts) - 1:
            time.sleep(0.3 + random.random() * 0.4)

    return (
        file_key,
        name,
        last_final,
        last_status,
    )


# -------------------------------------------------------------------
# Extract links recursively
# -------------------------------------------------------------------
def extract_links(
    data, skip_keys=["resources", "process", "baselayers", "overlaylayers"]
):
    results = []
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in skip_keys:
                continue
            if isinstance(value, str) and value.startswith("http"):
                results.append((key, value))
            results.extend(extract_links(value, skip_keys))
    elif isinstance(data, list):
        for item in data:
            results.extend(extract_links(item, skip_keys))
    return results


# -------------------------------------------------------------------
# HTML writer
# -------------------------------------------------------------------
def write_html(groups, prev_broken=None):
    prev_broken = prev_broken or set()
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write("""
<html>
<head>
<meta charset="UTF-8">
<title>Link Checker Report</title>
<style>
body {
    font-family: Arial, sans-serif;
    line-height: 1.5;
    padding: 20px;
}
.file {
    font-weight: bold;
    font-size: 1.2em;
    margin-top: 25px;
    border-bottom: 1px solid #ddd;
    padding-bottom: 5px;
}
.entry {
    margin-left: 15px;
    padding: 2px 0;
}
.green { color: green; }
.red { color: red; }
.gold { color: goldenrod; }
.purple { color: purple; font-weight: bold; }
</style>
</head>
<body>
<h2>Link Checker Report</h2>
<p>
Purple = newly broken link<br>
Red = already known broken link
</p>
""")
        for file, entries in groups.items():
            f.write(f'<div class="file">{html.escape(file)}</div>\n')
            for name, url, status in entries:
                normalized = normalize(url)
                known_broken = status != 200 and normalized in prev_broken
                newly_broken = status != 200 and normalized not in prev_broken

                if status == 200:
                    color = "green"
                    tag = ""
                elif newly_broken:
                    color = "purple"
                    tag = " ⚠️ NEW"
                elif known_broken:
                    color = "red"
                    tag = ""
                elif status in (301, 302, 307, 308, 403, 405):
                    color = "gold"
                    tag = ""
                else:
                    color = "red"
                    tag = ""

                text = f"{name}: {url} [{status}]{tag}"
                f.write(
                    f'<div class="entry {color}">' f"{html.escape(text)}" f"</div>\n"
                )
        f.write("</body></html>")


# -------------------------------------------------------------------
# Collect tasks
# -------------------------------------------------------------------
def collect(path):
    tasks = []
    if not path.exists():
        return tasks
    for root, _, files in os.walk(path):
        for file in files:
            if not file.endswith(".json"):
                continue
            fp = os.path.join(root, file)
            try:
                with open(fp, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                continue
            for name, url in extract_links(data):
                tasks.append((file, name, url))
    return tasks


def collect_from_files(file_paths):
    tasks = []
    for fp in file_paths:
        p = Path(fp)
        if not p.exists() or not p.is_file():
            print(f"⚠️ Skipping missing file: {fp}")
            continue
        if p.suffix.lower() != ".json":
            continue
        parts = {part.lower() for part in p.parts}
        if "collections" not in parts and "indicators" not in parts:
            continue
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            print(f"⚠️ Could not parse {fp}: {e}")
            continue
        for name, url in extract_links(data):
            tasks.append((p.name, name, url))
    return tasks


# -------------------------------------------------------------------
# History helpers
# -------------------------------------------------------------------
def load_previous_report():
    if not HISTORY_DIR.exists():
        return None
    files = sorted(HISTORY_DIR.glob(f"{HISTORY_PREFIX}*.json"))
    if not files:
        return None
    try:
        with open(files[-1], "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️ Could not read previous report: {e}")
        return None


def write_new_report(
    total_checked,
    broken_links,
    ok_links,
):
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S_UTC")
    path = HISTORY_DIR / f"{HISTORY_PREFIX}{ts}.json"
    payload = {
        "timestamp_utc": ts,
        "total_checked": total_checked,
        "errors": len(broken_links),
        "html_report_workflow_run": RUN_URL,
        "html_report_note": (
            "Download the colour-coded HTML report "
            "from the workflow artifacts on the page above."
        ),
        "broken_links": sorted(broken_links),
        "ok_links": sorted(ok_links),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    print(f"📝 Wrote {path}")
    return path


# -------------------------------------------------------------------
# Main
# -------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Link checker")
    parser.add_argument(
        "--files",
        nargs="*",
        default=None,
        help="Specific JSON files to check (PR mode)",
    )
    args = parser.parse_args()

    full_audit_env = os.environ.get("FULL_AUDIT", "").strip() == "1"
    is_pr_mode = args.files is not None and not full_audit_env

    print("\n🚀 Running link checker")
    print(f"📂 Repo root: {REPO_ROOT}")
    print(f"📂 Collections path: {COLLECTIONS_PATH}")
    print(f"📂 Indicators path: {INDICATORS_PATH}")
    print(f"📂 History dir: {HISTORY_DIR}")

    prev = load_previous_report()
    prev_ok = set(prev.get("ok_links", [])) if prev else set()
    prev_broken = set(prev.get("broken_links", [])) if prev else set()

    # ---------------------------------------------------------------
    # PR MODE
    # ---------------------------------------------------------------
    if is_pr_mode:
        print(f"📄 PR mode — checking " f"{len(args.files)} changed file(s)")
        tasks = collect_from_files(args.files)
        print(f"\n🔗 Total links in changed files: {len(tasks)}")

        if not prev:
            print("ℹ️ No previous baseline found.")

        groups = {}
        regressions = []
        new_broken = []

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            futures = [ex.submit(check_url, t) for t in tasks]
            for future in as_completed(futures):
                file, name, url, status = future.result()
                groups.setdefault(file, []).append((name, url, status))
                normalized = normalize(url)
                if status != 200:
                    if normalized in prev_ok:
                        regressions.append((file, name, url, status))
                        print(f"❌ REGRESSION: " f"{status} {url}")
                    elif normalized not in prev_broken:
                        new_broken.append((file, name, url, status))
                        print(f"⚠️ NEW BROKEN LINK: " f"{status} {url}")

        write_html(groups, prev_broken)

        print("\n--- PR check summary ---")
        print(f"Regressions:      {len(regressions)}")
        print(f"New broken links: {len(new_broken)}")
        if regressions or new_broken:
            raise SystemExit(1)
        print("✅ OK: no regressions.")
        return

    # ---------------------------------------------------------------
    # FULL AUDIT MODE
    # ---------------------------------------------------------------
    print("📂 Full audit mode — checking " "collections/ and indicators/")
    tasks = collect(COLLECTIONS_PATH) + collect(INDICATORS_PATH)
    print(f"\n🔗 Total links: {len(tasks)}")

    if not tasks:
        print("✅ Nothing to check.")
        write_html({})
        return

    groups = {}
    broken_links = set()
    ok_links = set()

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(check_url, t) for t in tasks]
        for future in as_completed(futures):
            file, name, url, status = future.result()
            groups.setdefault(file, []).append((name, url, status))
            normalized = normalize(url)
            if status == 200:
                ok_links.add(normalized)
            else:
                broken_links.add(normalized)

    write_html(groups, prev_broken)
    write_new_report(
        total_checked=len(tasks),
        broken_links=broken_links,
        ok_links=ok_links,
    )

    curr_errors = len(broken_links)
    newly_broken = broken_links - prev_broken
    fixed = prev_broken - broken_links

    print("\n--- Health trend ---")
    print(f"Previous errors: " f"{prev.get('errors') if prev else 'n/a'}")
    print(f"Current errors:  {curr_errors}")
    print(f"Fixed links:     {len(fixed)}")
    print(f"Newly broken:    " f"{len(newly_broken)}")

    if newly_broken:
        print("\n--- Newly broken links ---")
        for u in sorted(newly_broken):
            print(f"  • {u}")

    # Pipeline fails if current errors exceed previous errors
    prev_errors = prev.get("errors") if prev else None
    if isinstance(prev_errors, int) and curr_errors > prev_errors:
        print(
            f"\n❌ Failing: current broken links ({curr_errors}) "
            f"exceed previous ({prev_errors})."
        )
        sys.exit(1)

    print("\n✅ Full audit complete.")


if __name__ == "__main__":
    main()
