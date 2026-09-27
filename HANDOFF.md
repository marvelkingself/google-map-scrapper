# Lead Research Tool — user guide (no terminal knowledge needed)

## One-time setup
1. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and start it.
2. Download this folder (Code → Download ZIP) and unzip it.
3. Open the folder, right-click → "Open in Terminal", and run:
   ```
   docker compose -f docker-compose.local.yml up -d
   ```
   First run downloads ~1 GB. After that it starts in seconds and restarts with your PC.

## Daily use
Open **http://localhost:8080** in your browser.

1. **Job Name** — anything, e.g. `dentists-rotterdam`. It's just a label in the list.
2. **Keywords** — one search per line, exactly as you'd type it into Google Maps:
   ```
   dentists in Rotterdam
   dental clinic Amsterdam
   ```
3. **Depth** — how far to scroll each search. `1` ≈ 20 results, `5` ≈ 100. Start at 1–2.
4. **Fetch Emails** — on = also opens each business website to look for an email. Much slower, much more useful.
5. **Latitude / Longitude / Zoom** — the map centre for the search. Fine to leave at defaults if the city is in the keyword. Leave **Max job time**, **Language**, **Fast Mode** and **Radius** alone.
6. Click **Start Scraping**, then watch the job table below. Status goes `pending` → `working` → `ok`.
7. When it's `ok`, click **Download** for the CSV. Open it in Excel.

## Rules of thumb
- One job at a time, depth ≤ 5. Google rate-limits an IP that hammers it; if results suddenly come back empty, stop for a few hours.
- Big run = many keywords × high depth × emails on. Expect minutes to hours, and leave the PC on.
- The CSV holds business contact data (emails, phones). That's personal data under GDPR — keep it in your CRM, don't forward the raw file around.

## Trouble
- Page won't load → Docker Desktop isn't running. Start it, wait 30s, refresh.
- Job stuck on `working` for ages with emails on → normal, it's visiting websites one by one.
- Everything empty → rate-limited. Wait, or ask IT about proxies (`examples/proxies.example.txt`).
