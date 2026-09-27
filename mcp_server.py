#!/usr/bin/env python3
"""MCP server exposing the local Google Maps scraper as tools. Stdlib only — no pip install.

Register it (Claude Code):
    claude mcp add gmaps -- python C:/path/to/google-maps-scraper-kit/mcp_server.py
Claude Desktop (claude_desktop_config.json):
    {"mcpServers":{"gmaps":{"command":"python","args":["C:/path/to/mcp_server.py"]}}}

Remote mode (for Paperclip and other clients that want an http URL):
    MCP_TOKEN=secret python mcp_server.py --http      # POST /mcp, port 8081

Self-check:  python mcp_server.py --selfcheck
"""
import json, os, sys, time, csv, io, urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts"))
from scrape import req, geocode, LEAD  # reuse the existing HTTP + geocode helpers

OUT_DIR = os.environ.get("SCRAPER_OUT_DIR", os.path.dirname(os.path.abspath(__file__)))
POLL_BUDGET = int(os.environ.get("SCRAPER_POLL_SECONDS", "240"))  # stay under client timeouts
# Google blocks an IP that runs many scrapes at once, and an agent will happily fire ten in a row.
# One job at a time is the guard; raise it only if you run proxies.
MAX_PARALLEL = int(os.environ.get("SCRAPER_MAX_PARALLEL", "1"))
# Proxies are the real defence for bulk scraping, and an agent has no UI to paste them into.
PROXIES = os.environ.get("SCRAPER_PROXIES", "").replace(",", " ").split()
CSV_ROW_CAP = 200  # ponytail: caps the reply size for remote callers; paginate if that ever bites
HTTP_MODE = False  # set by serve_http: the caller has no access to our filesystem

TOOLS = [
    {
        "name": "scrape_businesses",
        "description": ("Scrape Google Maps business listings (name, phone, email, website, address, "
                        "rating) for one or more search queries. Runs ONE job at a time - put several searches in the "
                        "queries array instead of calling this repeatedly, or Google rate-limits the IP. "
                        "Google Maps only — not social media."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"},
                            "description": 'Searches as typed into Google Maps, e.g. ["dentists in Rotterdam"]'},
                "city": {"type": "string", "description": "City/place to centre the search on. Defaults to the first query."},
                "depth": {"type": "integer", "default": 5, "description": "Scroll depth; ~20 results per level. 1-5 is sane."},
                "emails": {"type": "boolean", "default": True, "description": "Also visit each website to find an email (slower)."},
            },
            "required": ["queries"],
        },
    },
    {
        "name": "check_job",
        "description": "Check a scrape job started earlier and, once finished, save + summarise its results.",
        "inputSchema": {"type": "object", "properties": {"job_id": {"type": "string"}}, "required": ["job_id"]},
    },
]


def _save(job_id):
    """Download a finished job, keep the lead fields, write CSV, return (rows, path)."""
    _, raw = req("GET", f"/api/v1/jobs/{job_id}/download")
    rows = [{k: r.get(k, "") for k in LEAD}
            for r in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")))]
    path = os.path.join(OUT_DIR, f"results-{job_id[:8]}.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LEAD)
        w.writeheader()
        w.writerows(rows)
    return rows, path


def _summary(job_id, rows, path):
    if not rows:
        return (f"Job {job_id} finished with 0 results. That usually means Google is rate-limiting "
                f"this IP - wait a few hours, or add proxies (see examples/proxies.example.txt).")
    if HTTP_MODE:
        # Remote caller (Paperclip etc.) cannot read our disk, so hand back the data itself.
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=LEAD)
        w.writeheader()
        w.writerows(rows[:CSV_ROW_CAP])
        more = f" (first {CSV_ROW_CAP} shown)" if len(rows) > CSV_ROW_CAP else ""
        return f"Done: {len(rows)} businesses (job {job_id}).{more}\n\n{buf.getvalue()}"
    head = "\n".join(f"- {r['title']} | {r['phone'] or '-'} | {r['emails'] or '-'} | {r['website'] or '-'}"
                     for r in rows[:10])
    return (f"Done: {len(rows)} businesses (job {job_id}).\nSaved to {path}"
            f"\n\nFirst results:\n{head}")


def _busy():
    """Jobs the scraper is already chewing on."""
    jobs = json.loads(req("GET", "/api/v1/jobs")[1]) or []
    return [j for j in jobs if j.get("Status") in ("working", "pending")]

def scrape_businesses(queries, city=None, depth=5, emails=True):
    if not queries:
        return "No queries given."
    busy = _busy()
    if len(busy) >= MAX_PARALLEL:
        return (f"Not starting this one - {len(busy)} scrape(s) already running (e.g. {busy[0]['ID']}). "
                f"Running several at once gets the IP blocked by Google, so this tool does one at a time. "
                f"Call check_job on that id; when it says ok, ask again.")
    coords = geocode(city or queries[0])
    if not coords:
        return f"Could not locate '{city or queries[0]}'. Try a clearer city name."
    lat, lon = coords
    warning = ""
    if depth > 10 or len(queries) > 20:
        warning = ("Note: big run (high depth or many searches). It will take a while and can get "
                   "this IP rate-limited by Google; proxies help. Starting it anyway.\n\n")
    body = {"name": "mcp", "keywords": queries, "lang": "en", "zoom": 15, "lat": lat, "lon": lon,
            "fast_mode": False, "radius": 10000, "depth": depth, "email": emails, "max_time": 600}
    if PROXIES:
        body["proxies"] = PROXIES
    job_id = json.loads(req("POST", "/api/v1/jobs", body)[1])["id"]
    deadline = time.time() + POLL_BUDGET
    while time.time() < deadline:
        time.sleep(8)
        status = json.loads(req("GET", f"/api/v1/jobs/{job_id}")[1]).get("Status")
        if status == "ok":
            return warning + _summary(job_id, *_save(job_id))
        if status == "failed":
            return f"Job {job_id} failed — possibly rate-limited. Wait a while or use proxies."
    return (warning + f"Job {job_id} is still running (big jobs take a while). "
            f"Call check_job with job_id={job_id} in a few minutes.")


def check_job(job_id):
    status = json.loads(req("GET", f"/api/v1/jobs/{job_id}")[1]).get("Status")
    if status == "ok":
        return _summary(job_id, *_save(job_id))
    return f"Job {job_id} status: {status}."


CALL = {"scrape_businesses": scrape_businesses, "check_job": check_job}


def handle(msg):
    """JSON-RPC 2.0 over stdio. Returns a response dict, or None for notifications."""
    mid, method = msg.get("id"), msg.get("method")
    if method == "initialize":
        result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                  "serverInfo": {"name": "google-maps-scraper", "version": "1.0"}}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        p = msg.get("params", {})
        fn = CALL.get(p.get("name"))
        if not fn:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown tool {p.get('name')}"}}
        try:
            text = fn(**p.get("arguments", {}))
        except Exception as e:  # surface as tool error, not transport error
            # HTTPError means the scraper answered (bad args / unknown job); anything else = unreachable.
            hint = "" if isinstance(e, urllib.error.HTTPError) else " Is the scraper running? (docker compose up -d)"
            return {"jsonrpc": "2.0", "id": mid,
                    "result": {"content": [{"type": "text", "text": f"Error: {e}.{hint}"}], "isError": True}}
        result = {"content": [{"type": "text", "text": text}]}
    elif mid is None:
        return None  # notification (e.g. notifications/initialized)
    else:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def selfcheck():
    assert handle({"jsonrpc": "2.0", "id": 1, "method": "initialize"})["result"]["protocolVersion"]
    names = [t["name"] for t in handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
    assert names == ["scrape_businesses", "check_job"], names
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    bad = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "nope", "arguments": {}}})
    assert "error" in bad
    assert "error" in handle({"jsonrpc": "2.0", "id": 5, "method": "bogus/method"})
    empty = handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                    "params": {"name": "scrape_businesses", "arguments": {"queries": []}}})
    assert empty["result"]["content"][0]["text"] == "No queries given."

    # concurrency guard must fire without touching the network
    import mcp_server as M
    real_req, real_geo = M.req, M.geocode
    M.req = lambda m, pth, b=None: (200, b'[{"ID":"busy-1","Status":"working"}]')
    M.geocode = lambda place: ("1.0", "2.0")
    try:
        msg = M.scrape_businesses(["cafes in Pune"])
        assert "already running" in msg and "busy-1" in msg, msg
    finally:
        M.req, M.geocode = real_req, real_geo
    print("selfcheck ok")


def serve_http(port=None):
    """Streamable-HTTP MCP: one JSON-RPC message per POST, one JSON response back.
    ponytail: no SSE stream and no sessions — clients that need those will say so."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    global HTTP_MODE
    HTTP_MODE = True
    port = port or int(os.environ.get("MCP_PORT", "8081"))
    token = os.environ.get("MCP_TOKEN", "")
    if not token:
        sys.exit("✗ Refusing to serve without MCP_TOKEN — it would let anyone run scrapes.")

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _send(self, code, obj=None):
            body = b"" if obj is None else json.dumps(obj).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.headers.get("Authorization") != f"Bearer {token}":
                return self._send(401, {"error": "unauthorized"})
            try:
                msg = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
            except ValueError:
                return self._send(400, {"jsonrpc": "2.0", "id": None,
                                        "error": {"code": -32700, "message": "parse error"}})
            resp = handle(msg)
            self._send(202 if resp is None else 200, resp)  # 202 = notification, no body

        def do_GET(self):
            self._send(405, {"error": "POST JSON-RPC to this endpoint"})

        def log_message(self, *a):
            pass

    print(f"MCP over HTTP on 0.0.0.0:{port} (POST, Bearer auth)", file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", port), H).serve_forever()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        resp = handle(json.loads(line))
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        selfcheck()
    elif "--http" in sys.argv:
        serve_http()
    else:
        main()
