# ReelHarbor

ReelHarbor is a self-hosted website video discovery and download manager. It crawls only the public pages you choose, detects accessible video sources with multiple detector modules, lets you inspect and select results, then queues permitted downloads. It does not bypass DRM or authentication.

## Highlights

- Fast HTTP and JavaScript/Playwright crawl modes
- HTML5, Open Graph, JSON-LD, iframe, script, HLS, DASH, and browser-network detectors
- Scan scope, depth, page, include, exclude, pause, resume, and stop controls
- Visual results, search, resolution/size filters, duplicate flags, previews, details, CSV/JSON export, and aggregate selection size
- Real `yt-dlp` download execution with `ffmpeg`, retry controls, disk threshold enforcement, and a persistent library
- First-run setup, local accounts, signed HTTP-only sessions, CSRF protection, structured logs, and SSRF protection
- Docker Compose deployment with PostgreSQL, Redis, health checks, restart policies, and persistent volumes
- Demo mode with 20 varied media records (`demo` / `reelharbor-demo`)

## Architecture

The browser uses a React/TypeScript single-page app served by Nginx. Nginx proxies `/api` to FastAPI. FastAPI persists users, scans, pages, video candidates, queue entries, schedules, and library items in PostgreSQL. Redis is provisioned for durable multi-worker coordination; the included single API worker uses its local async event bus for low-latency progress events. Crawlers revalidate DNS and redirects before requests. See [ARCHITECTURE.md](ARCHITECTURE.md) for boundaries, schema, detectors, and security details.

## Install on a Traefik-managed Hostinger VPS

Requirements: Docker Engine 25+ with the Compose plugin, an existing Traefik Docker network, at least 4 GB RAM for browser crawling, and sufficient storage for your media.

```bash
cp .env.example .env
# Set APP_DOMAIN to the DNS hostname routed by Traefik.
# Set TRAEFIK_NETWORK, entrypoint, and certificate resolver to match your stack.
# Replace POSTGRES_PASSWORD and SECRET_KEY with strong unique values.
docker compose up -d --build
docker compose ps
```

Open `https://APP_DOMAIN`. ReelHarbor publishes no host port: Traefik reaches Nginx on container port 80 through the configured external network and terminates TLS. With `DEMO_MODE=false`, the first-run wizard creates the administrator and storage policy.

Normal operation requires no command line: use **New Scan**, review **Detected Videos**, select the wanted items, and use **Download Selected**. Scheduled scans only detect by default.

## Configuration

| Variable | Default | Purpose |
|---|---:|---|
| `APP_DOMAIN` | required | DNS hostname used by Traefik and the application origin |
| `TRAEFIK_NETWORK` | `traefik` | Existing external Docker network shared with Traefik |
| `TRAEFIK_ENTRYPOINT` | `websecure` | HTTPS entrypoint configured in Traefik |
| `TRAEFIK_CERT_RESOLVER` | `letsencrypt` | Certificate resolver configured in Traefik |
| `SECRET_KEY` | required | Session and CSRF signing secret |
| `POSTGRES_PASSWORD` | required | Database password |
| `DEMO_MODE` | `false` | Seeds sample media and a demo account |
| `ALLOW_PRIVATE_NETWORKS` | `false` | Explicit admin-only opt-in for trusted LAN crawling |
| `MAX_STORAGE_PERCENT` | `90` | Pauses new downloads at this disk usage |
| `CONCURRENT_DOWNLOADS` | `2` | Intended active download cap |

Private-network access is deliberately disabled. Only enable it on a trusted deployment after considering DNS rebinding, reachable services, and network segmentation. Passwords, cookies, tokens, and authorization headers are not included in crawler logs.

## Scan and download behavior

Fast crawl is best for ordinary HTML. Browser crawl renders JavaScript, scrolls once, and classifies media-related network responses. Choose page, pagination, directory, domain, or pattern scope and set limits. Direct file sizes come from HTTP headers when available; adaptive stream sizes remain estimates or unknown. Metadata failures are reported as unknown.

DRM-marked and unsupported records remain visible but cannot be queued. ReelHarbor uses `yt-dlp` and asks for best video plus audio by default, merging to MP4 without deliberately transcoding. Source terms and copyright law remain the operator's responsibility.

## Development and tests

Backend:

```bash
cd backend
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pytest -q
uvicorn app.main:app --reload
```

Frontend:

```bash
cd frontend
npm install
npm run dev
npm run build
```

The test suite covers URL validation and SSRF blocks, HTML/HLS detection, deduplication, duration/size formatting, filename cleanup, queue breadth, crawl limits, and storage thresholds.

## Upgrade

```bash
docker compose pull
docker compose build --pull
docker compose up -d
docker image prune
```

Back up before upgrades. Database schema creation is additive in this release; for long-lived customized deployments, introduce Alembic migrations before changing models.

## Backup and restore

Create a database dump and archive the named volumes:

```bash
docker compose exec -T postgres pg_dump -U reelharbor reelharbor > reelharbor.sql
docker run --rm -v reelharbor_videos:/source:ro -v "$PWD":/backup alpine tar czf /backup/videos.tgz -C /source .
docker run --rm -v reelharbor_thumbnails:/source:ro -v "$PWD":/backup alpine tar czf /backup/thumbnails.tgz -C /source .
```

Restore into a stopped/fresh deployment:

```bash
cat reelharbor.sql | docker compose exec -T postgres psql -U reelharbor reelharbor
docker run --rm -v reelharbor_videos:/target -v "$PWD":/backup alpine tar xzf /backup/videos.tgz -C /target
```

Test restores periodically and protect backups because the database contains source URLs and local file paths.

## Troubleshooting

- **Target blocked:** the hostname resolves to an internal/special-use address. This is SSRF protection, not a crawler failure.
- **403 or expired URL:** rescan the source page. Do not copy cookies into logs.
- **Browser scan fails:** allow 2–3 GB memory for Chromium and inspect `docker compose logs api`.
- **Download fails:** verify the source remains accessible, then use Retry. `yt-dlp` site support changes over time.
- **Disk threshold reached:** free storage or raise the limit deliberately in Settings.
- **No thumbnail:** the video remains selectable with a safe generic placeholder.

## Production notes

Use HTTPS, strong unique secrets, a host firewall, regular backups, and restricted administrator access. For horizontal scale, replace the in-process task/event runner with Celery/RQ workers backed by the provisioned Redis instance; the detector and normalized persistence boundaries are already isolated for that transition.

If your Traefik network, entrypoint, or certificate resolver uses a different name, change the corresponding environment variable rather than publishing a host port.
