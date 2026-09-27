# Deploy to Coolify

Uses `docker-compose.yml` (the default Coolify picks up). The scraper image has **no authentication**, so it never gets a
domain — a Caddy container with a password does, and proxies inward. Do not give the
`google-maps-scraper` service a domain in Coolify.

## Steps
1. **Coolify -> + New -> Public Repository**, point it at this repo.
2. Set **Build Pack** to `Docker Compose`. Leave **Docker Compose Location** at the default
   `/docker-compose.yml` - that file IS the server stack. (The laptop-only version lives in
   `docker-compose.local.yml`, which Coolify must never deploy: it publishes port 8080 on the host and
   will collide with whatever already holds it.) Three services must appear: `google-maps-scraper`,
   `mcp`, `auth`.
3. **Environment Variables**:
   | Name | Value |
   |---|---|
   | `AUTH_USER` | `marketing` |
   | `AUTH_PASS` | the password for the web UI - **avoid the `$` character** |
   | `MCP_TOKEN` | any long random string, for agent platforms - same, no `$` |

   Do not put a bcrypt hash in here. Docker compose treats `$` in an env-file value as a variable
   reference and silently blanks it; Caddy hashes `AUTH_PASS` itself at container start.
4. **Domain**: in the services list, set a domain on the **`auth`** service only, and make sure
   `google-maps-scraper` and `mcp` are **blank**. Coolify pre-fills generated domains for every
   service - a domain left on `google-maps-scraper` publishes the scraper UI and its job API with no
   password at all, which is how scraped contact data leaks. Coolify writes the traefik labels from
   this field; hand-written labels in the compose file cannot use a variable, because Coolify escapes
   `${VAR}` to `$${VAR}` inside labels.
5. Deploy. The `mcp` logs should print `MCP over HTTP on 0.0.0.0:8081`.
   Open the domain -> browser asks for the username/password -> the scraper UI appears.
   Hand those credentials + `HANDOFF.md` to whoever does the research.

## Server requirements
- **2 GB RAM minimum**, 4 GB if you run depth > 5 or email extraction. It drives a real Chromium.
- `shm_size: 1gb` is already set — without it Chromium crashes mid-job on Docker's default 64 MB.
- Volumes `gmaps_data` (results) and `gmaps_cache` (browser, ~400 MB) persist across deploys.

## Bulk scraping and rate limits
Google publishes no limit; it just starts refusing. And a VPS exit IP is a datacenter IP, which
Google throttles far faster than a home or office connection - what worked on your laptop can
start returning empty jobs after a handful of runs on the server. The tell is a job that finishes `ok` with **0 rows**
(or `failed`). It clears by itself in minutes to hours. Nothing in the scraper throttles you, so:

- **One job at a time.** The MCP server enforces this: if a job is `working`, `scrape_businesses`
  refuses and tells the agent to call `check_job` first. Override with `SCRAPER_MAX_PARALLEL`, but only
  once proxies are in place.
- **Bulk = one job with many queries, not many jobs.** The scraper walks the `queries` array
  sequentially inside a single job. Ten searches in one call is fine; ten calls is what gets you blocked.
- **Depth is the real cost knob.** `depth` 1 is ~20 results per query, 5 is ~100. `depth > 10` or more
  than 20 queries triggers a warning in the reply and still runs.
- **`email: true` multiplies the work** - it opens every business website. Slower, and more requests.
- **Proxies** are the only actual fix for sustained volume. Set `SCRAPER_PROXIES` in Coolify
  (space- or comma-separated, `http://user:pass@ip:port` or `socks5://ip:port`); the MCP server attaches
  them to every job. The web UI has its own Proxies box for manual runs.

Rough guide for a single VPS IP without proxies: a few jobs an hour at depth <= 5 is usually fine;
back-to-back jobs, or depth 15+, will start returning empty within an hour or two.

## Using it from Paperclip (or any agent platform)
The `mcp` service serves MCP over HTTP at **`https://<your-domain>/mcp`**, protected by a Bearer
token (`MCP_TOKEN` — any long random string, set it in Coolify).

In Paperclip: **Connectors -> Connect your own MCP server** -> paste `https://<your-domain>/mcp`.
When it asks for credentials, give the `MCP_TOKEN` value as the API key (Paperclip sends it as an
`Authorization` header, which is what the server checks). Then grant the connector to the agent that
does lead research and set its tools to **Allowed** or **Ask first**.

The agent gets two tools: `scrape_businesses` and `check_job`. Over HTTP the rows come back as CSV
text in the reply (up to 200) instead of a file path — the agent has no access to the server's disk.

## Using the MCP server locally against the deployed instance
`mcp_server.py` still runs **locally** (MCP stdio isn't remote); just point it at the server:
```
claude mcp add gmaps   -e SCRAPER_BASE_URL=https://scraper.example.com   -e SCRAPER_BASIC_AUTH=marketing:a-long-password   -- python /path/to/mcp_server.py
```
`SCRAPER_BASIC_AUTH` is `user:password`, not the hash. Credentials in the URL itself
(`https://user:pass@…`) do **not** work — Python's urllib silently ignores them.

## Why there are Dockerfiles
Coolify clones the repo inside a build helper, not onto the deployment host, so a compose bind mount
like `./Caddyfile:/etc/caddy/Caddyfile` points at a path that does not exist - Docker then creates an
empty *directory* there and the container dies with "not a directory". `Dockerfile` (the MCP server)
and `Dockerfile.caddy` (the Caddy config) copy those files into the images instead. Do not turn them
back into bind mounts.

## Not covered
No backups of `gmaps_data` — results are re-scrapable, and the CSVs you keep are the deliverable.
Scraped emails/phones are personal data: a public URL holding them needs a real password, which is
the whole point of the `auth` service. Don't remove it to "make it easier".
