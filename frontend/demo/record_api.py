"""Adds API responses the UI crawl (record.spec.ts) can't reach on its own to demo/fixtures.json:
every event, artifact, evidence passage, brief and asset; admin screens; Ask answers; comparisons.

Usage (API running on :8000 with the seeded demo tenant):  python3 demo/record_api.py
"""
import itertools
import json
import pathlib
import re
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8000/api/v1"
OUT = pathlib.Path(__file__).with_name("fixtures.json")
recs = {(r["method"], r["path"], r["query"], r["body"]): r for r in json.loads(OUT.read_text())} if OUT.exists() else {}

QUESTIONS = [
    "What changed this week?",
    "Which competitor trials changed their primary endpoint?",
    "Compare CA-201 and BRV-310",
    "What catalysts are expected in the next 6 months?",
    "What changed in NCT99000001?",
    "How does the NCT99000001 change affect XD-101?",
    "Is CA-201 better than XD-101?",
    "What is the overall survival result for CA-201?",
    "Which programs target Target X in NSCLC?",
    "What is the status of BRV-310?",
]


def call(method, path, query=None, body=None, token=None):
    qs = urllib.parse.urlencode(query or {}, doseq=True)
    data = json.dumps(body, separators=(",", ":")).encode() if body is not None else None
    req = urllib.request.Request(f"{BASE}{path}{'?' + qs if qs else ''}", data=data, method=method)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=120) as res:
            status, ct, text = res.status, res.headers.get("Content-Type", ""), res.read().decode()
    except urllib.error.HTTPError as e:
        status, ct, text = e.code, e.headers.get("Content-Type", ""), e.read().decode()
    query_key = "&".join(f"{k}={v}" for k, v in sorted(urllib.parse.parse_qsl(qs)))
    body_key = data.decode() if data and not path.endswith("/auth/login") else ""
    if "json" in ct or status == 204:
        recs[(method, path, query_key, body_key)] = {"method": method, "path": path, "query": query_key, "body": body_key,
                                                     "status": status, "contentType": ct, "text": text}
    return json.loads(text) if "json" in ct and text else None


def find(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key and isinstance(v, str):
                yield v
            yield from find(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from find(v, key)


def items(page):
    return page.get("items", []) if isinstance(page, dict) else (page or [])


tok = call("POST", "/auth/login", body={"tenant": "demo-oncology", "email": "analyst@demo.example", "password": "ChangeMe-Demo-2026!"})["access_token"]
get = lambda p, **q: call("GET", p, q or None, token=tok)

landscapes = get("/landscapes") or []
lid = landscapes[0]["id"]
if not get("/reports"):  # one executive brief so the Briefs screen has content (written as the CI lead)
    lead = call("POST", "/auth/login", body={"tenant": "demo-oncology", "email": "lead@demo.example", "password": "ChangeMe-Demo-2026!"})
    call("POST", "/reports/briefs", body={"landscape_id": lid}, token=lead["access_token"])
    get("/reports")
    get("/reports", landscape_id=lid)
for p in ["/templates", "/profile-fields", "/alerts/policies", "/admin/users", "/admin/roles", "/admin/proximity-rules",
          "/admin/models", "/admin/settings", "/audit/verify", "/feedback/datasets", "/model-releases"]:
    get(p)
get("/kpis", landscape_id=lid, days=90)
get("/landscapes/" + lid + "/graph", depth=1)
get("/feedback/tuning-suggestions", landscape_id=lid)
get("/admin/usage", days=30)
get("/audit", limit=50, offset=0)
get("/alerts/deliveries", limit=50, offset=0)
get("/alerts/inbox", unread_only="true")
for c in get("/admin/connectors") or []:
    if isinstance(c, dict) and c.get("key"):
        get(f"/admin/connectors/{c['key']}/runs", limit=20, offset=0)

details = []
for e in items(get("/events", limit=200, offset=0, sort="date")):
    d = get(f"/events/{e['id']}")
    details.append(d)
    for a in (d or {}).get("narrative_history", []):
        get(f"/events/{e['id']}/artifacts/{a['id']}")
for r in get("/reports") or []:
    details.append(get(f"/reports/{r['id']}"))
assets = items(get("/assets", limit=200))
for a in assets:
    details.append(get(f"/assets/{a['id']}"))
    get(f"/assets/{a['id']}/profile/versions")

answers = []
for q in QUESTIONS:
    answers.append(call("POST", "/ask", body={"question": q}, token=tok))
for s in get("/ask/sessions") or []:
    get(f"/ask/sessions/{s['id']}")

# Comparisons: the customer asset against every competitor, plus every pair of the first few programs.
internal = [a["id"] for a in assets if a.get("is_internal")]
others = [a["id"] for a in assets if not a.get("is_internal")]
pairs = {tuple(sorted((i, o))) for i in internal for o in others} | {tuple(sorted(p)) for p in itertools.combinations(others[:6], 2)}
for p in sorted(pairs):
    details.append(call("POST", "/comparisons", body={"asset_ids": list(p)}, token=tok))

for cid in sorted({c for d in details + answers for c in find(d, "chunk_id")}):
    get(f"/sources/chunks/{cid}", window=1)

OUT.write_text(json.dumps(list(recs.values())))
print(f"{len(recs)} responses, {OUT.stat().st_size // 1024} KB")
