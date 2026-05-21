# watchlistarr

Sync your Letterboxd watchlists and lists straight into Radarr, with a friendly web UI.

watchlistarr watches public Letterboxd accounts and serves them to Radarr as Custom Lists. Add a username, pick which lists to sync, paste the URL into Radarr. No API keys, no scripting.

![Docker version](https://img.shields.io/docker/v/maxlainz/watchlistarr?label=docker&sort=semver)
![Docker pulls](https://img.shields.io/docker/pulls/maxlainz/watchlistarr)
![CI](https://img.shields.io/github/actions/workflow/status/maxlainz/watchlistarr/ci.yml?branch=main)

---

## Features

- **Multi-user** — track lists from as many Letterboxd accounts as you want.
- **Smart custom lists** — combine watchlists with union or intersection, exclude movies others have already watched, and filter by rating or year.
- **Time-based rotation** — pick "5 movies a week" and watchlistarr cycles through your big lists at a steady pace, so Radarr doesn't grab everything at once.
- **Safe by default** — movies aren't dropped after a single hiccup; removal only happens after several confirmations.
- **Live web UI** — add users, toggle lists, build custom lists and watch the activity log in real time. No config files to edit after install.
- **One container, multi-arch** — `linux/amd64` and `linux/arm64`. Runs wherever Docker runs.

## What you need

- Docker and Docker Compose v2
- A Radarr instance reachable on the network
- One or more public Letterboxd usernames

## Quick start

Two ways to install — pick the one that matches your setup.

### Option 1: Add to your `docker-compose.yml` (recommended)

Best if you already run an *-arr stack with Docker Compose. Drop this service into your existing `docker-compose.yml` (or create a new file with just this):

```yaml
services:
  watchlistarr:
    image: maxlainz/watchlistarr:1.0.0
    container_name: watchlistarr
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./watchlistarr/data:/data
```

Then bring it up:

```bash
docker compose up -d watchlistarr
```

> Want to change defaults (port, log level, sync intervals)? Add an `environment:` block to the service, or point `env_file:` at your own `.env`. See [`.env.example`](https://github.com/maxlainz/watchlistarr/blob/main/.env.example) for the full list of options — defaults are sensible, so most setups don't need any of them.

### Option 2: Clone the repo

```bash
git clone https://github.com/maxlainz/watchlistarr.git
cd watchlistarr
cp .env.example .env
docker compose up -d
```

Either way, open `http://localhost:8080` in your browser. That's it — there's nothing else to configure to get going.

> **Versions**: `:1.0.0` is the latest stable release. Check [Docker Hub](https://hub.docker.com/r/maxlainz/watchlistarr/tags) for newer ones, or use `:latest` if you want every `docker compose pull` to bring you the most recent build.

## First-time setup

Once the UI loads:

1. Go to **Users → Add user** and type a Letterboxd username. watchlistarr checks it exists and discovers their public lists in the background.
2. Open that user. Toggle on the lists you want to sync.
3. *(Optional)* Go to **Custom Lists → New custom list** to combine several lists into one URL — union, intersection, filters, rotation.
4. Each active list and custom list shows a **Copy URL** button. That URL is what you paste into Radarr.

> **Heads up — the first sync takes a while.** watchlistarr scrapes Letterboxd politely (one request at a time, with delays to avoid rate limits), so a freshly enabled list can take from a few seconds for a small list to tens of minutes for a watchlist with thousands of films. Once the first sync finishes, subsequent updates are quick because only changes are fetched. You can watch progress live in the **Activity** tab.

## Connecting Radarr

watchlistarr exposes three kinds of URLs you can hand to Radarr:

| What you want | URL |
|---|---|
| A user's full watchlist | `http://<host>:8080/<username>/watchlist/` |
| A specific list from a user | `http://<host>:8080/<username>/<list-slug>/` |
| A custom list you built | `http://<host>:8080/lists/<custom-slug>/` |

In Radarr:

1. **Settings → Import Lists → Add (+) → Custom List**
2. **Name**: whatever you like.
3. **List URL**: one of the URLs above (use the Copy button in watchlistarr's UI).
4. **Enable Automatic Add**: `Yes` (otherwise Radarr only lists candidates instead of importing).
5. Pick your **Quality Profile**, **Root Folder** and **Minimum Availability**.
6. Click **Test** → should turn green. **Save**.

> If watchlistarr and Radarr run in the same Docker network, use the service name as the host: `http://watchlistarr:8080/...`

## Configuration

Most settings live in the web UI and apply instantly — no restart needed:

- Add or remove users
- Enable / disable individual lists
- Per-list sync intervals
- Custom list rules (sources, filters, rotation, sort order)

A few low-level options live in `.env` and require a `docker compose restart` to apply:

| Variable | Default | What it does |
|---|---|---|
| `HTTP_PORT` | `8080` | Port the UI and API listen on. |
| `LOG_LEVEL` | `info` | One of `debug`, `info`, `warning`, `error`. |
| `LOG_FORMAT` | `plain` | Use `json` if you ship logs to a collector. |

The full list — sync frequencies, anti-flap thresholds, user agent — is documented in [`.env.example`](.env.example). The defaults are sensible for most setups.

## Updating

```bash
docker compose pull
docker compose up -d
```

Database migrations run automatically on startup. Before jumping across versions, check the [CHANGELOG](CHANGELOG.md) for breaking changes.

## Backup & restore

Your data lives in `./data/watchlistarr.db` (a single SQLite file).

```bash
# Quick backup
docker compose stop watchlistarr
cp data/watchlistarr.db "data/watchlistarr.db.$(date +%F)"
docker compose start watchlistarr
```

To restore: stop the container, replace `data/watchlistarr.db` with your backup, start it again.

## Troubleshooting

- **Container won't start** — `docker compose logs watchlistarr`. Most issues come from typos in `.env`. Duration values must look like `15m`, `1h`, `7d`.
- **UI loads but `/healthz` returns 503** — the database file isn't writable. Check permissions on the `./data` folder.
- **Radarr's Test button fails** — open the URL in your browser. You should see a JSON list (it can be `[]` if the list is empty). Double-check the trailing slash.
- **Radarr is empty after the import** — open the watchlistarr UI and check the sync status on the list. You can trigger a refresh from the list's ⚙ menu.
- **Letterboxd returns 429** — you're hitting Letterboxd too often. Increase the sync interval on noisy lists from the UI.
- **Live logs** — the **Activity** tab in the UI, or `docker compose logs -f watchlistarr`.

## Development

```bash
uv sync
uv run alembic upgrade head
uv run uvicorn watchlistarr.main:app --reload --port 8080
```

Internal docs (architecture, scraping rules, data model, release process) live in [CLAUDE.md](CLAUDE.md) and [`.claude/`](.claude/).

## Credits

Inspired by [letterboxd-list-radarr](https://github.com/screeny05/letterboxd-list-radarr), which stopped working after Letterboxd's API changes.
