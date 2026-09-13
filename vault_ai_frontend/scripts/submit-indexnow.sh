#!/usr/bin/env bash
# Notify IndexNow participants when SVaultAI public search pages change.

set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd "$script_dir/.." && pwd)"
indexnow_key="d3e731074886067a0a003327df1cbed1"
key_location="https://app.svaultai.com/${indexnow_key}.txt"
sitemap_source="$project_root/web/sitemap.xml"

if [ ! -f "$sitemap_source" ]; then
    echo "[indexnow] ERROR: sitemap missing at $sitemap_source" >&2
    exit 2
fi

if [ "$(curl -sS -o /dev/null -w '%{http_code}' "$key_location")" != "200" ]; then
    echo "[indexnow] ERROR: public verification key is not reachable." >&2
    exit 3
fi

payload="$(python3 - "$sitemap_source" "$indexnow_key" "$key_location" <<'PY'
import json
import sys
import xml.etree.ElementTree as ET

sitemap, key, key_location = sys.argv[1:]
root = ET.parse(sitemap).getroot()
namespace = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
urls = [node.text for node in root.findall('s:url/s:loc', namespace)]
if not urls or any(not url.startswith('https://app.svaultai.com/') for url in urls):
    raise SystemExit('sitemap contains an invalid IndexNow URL')
print(json.dumps({
    'host': 'app.svaultai.com',
    'key': key,
    'keyLocation': key_location,
    'urlList': urls,
}, separators=(',', ':')))
PY
)"

response_file="$(mktemp)"
status_code="$(curl -sS -o "$response_file" -w '%{http_code}' \
    -H 'Content-Type: application/json; charset=utf-8' \
    --data "$payload" \
    https://api.indexnow.org/indexnow)"

case "$status_code" in
    200|202)
        echo "[indexnow] Submitted all canonical sitemap URLs successfully ($status_code)."
        ;;
    *)
        echo "[indexnow] ERROR: submission failed with HTTP $status_code." >&2
        sed -n '1,20p' "$response_file" >&2
        exit 4
        ;;
esac
