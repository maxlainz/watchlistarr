# watchlistarr

Sync your Letterboxd watchlists and lists straight into Radarr, with a friendly web UI.

Add a Letterboxd username, pick the lists you want, paste a URL into Radarr — done. No API keys, no config files, no scripting. Works with any public Letterboxd profile.

![Docker version](https://img.shields.io/docker/v/maxlainz/watchlistarr?label=docker&sort=semver)
![Docker pulls](https://img.shields.io/docker/pulls/maxlainz/watchlistarr)
![CI](https://img.shields.io/github/actions/workflow/status/maxlainz/watchlistarr/ci.yml?branch=main)
![License](https://img.shields.io/github/license/maxlainz/watchlistarr)

---

## Features

- **Multi-user** — follow as many Letterboxd accounts as you want.
- **Smart custom lists** — merge several lists into one, exclude movies somebody has already watched, filter by rating or release year.
- **Steady rotation** — pick "5 movies a week" and big watchlists trickle into Radarr at your pace instead of all at once.
- **Safe removals** — a movie must disappear from a list several times in a row before it's dropped, so your Radarr library doesn't flicker.
- **Everything in the browser** — add users, toggle lists, build custom lists and watch live activity. Changes apply instantly, no restarts.
- **One small container** — runs anywhere Docker runs, on `amd64` and `arm64`.

## Installation

You need Docker (with Compose) and a Radarr instance reachable on your network.

Add this to your `docker-compose.yml` (or create a new one with just this):

```yaml
services:
  watchlistarr:
    image: maxlainz/watchlistarr:latest
    container_name: watchlistarr
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - ./watchlistarr/data:/data
```

```bash
docker compose up -d
```

Prefer plain `docker run`?

```bash
docker run -d \
  --name watchlistarr \
  --restart unless-stopped \
  -p 8080:8080 \
  -v ./watchlistarr/data:/data \
  maxlainz/watchlistarr:latest
```

Open `http://localhost:8080` in your browser. That's it — everything else is set up from the web UI.

> `:latest` always tracks the newest release. To pin a version, replace it with e.g. `:1.5.2` — available tags on [Docker Hub](https://hub.docker.com/r/maxlainz/watchlistarr/tags). The same image is also published to GitHub Container Registry: `ghcr.io/maxlainz/watchlistarr`.

## First steps

1. In the web UI, go to **Users → Add user** and type a Letterboxd username. Their public lists are discovered automatically.
2. Open the user and toggle on the lists you want to sync.
3. *(Optional)* Go to **Custom Lists** to combine several lists into one, with filters and rotation.
4. Every list has a **Copy URL** button. That URL is what you give to Radarr.

> [!IMPORTANT]
> **The first sync of a big list takes a while.** watchlistarr fetches slowly on purpose to be gentle with Letterboxd — a small list is done in seconds, but a watchlist with thousands of films can take tens of minutes the first time. This is normal: leave it running and watch progress live in the **Activity** tab. Once the first sync finishes, updates only fetch changes and are quick.

## Connecting Radarr

1. In Radarr, go to **Settings → Import Lists → Add (+)** and pick **Custom Lists**.
2. **List URL**: paste the URL you copied from watchlistarr.
3. **Enable Automatic Add**: `Yes`.
4. Pick your **Quality Profile**, **Root Folder** and **Minimum Availability**.
5. Click **Test** → green → **Save**.

These are the URLs watchlistarr serves:

| What you want | URL |
|---|---|
| A user's full watchlist | `http://<host>:8080/<username>/watchlist/` |
| A specific list from a user | `http://<host>:8080/<username>/<list-slug>/` |
| A custom list you built | `http://<host>:8080/lists/<custom-slug>/` |

> If Radarr and watchlistarr run in the same Docker network, use the service name as the host: `http://watchlistarr:8080/...`
> The **StevenLu Custom** list type in Radarr works with the same URLs too.

## Configuration

Day-to-day settings live in the web UI and apply instantly: users, lists, sync intervals, custom list rules.

A few startup options (port, log level, default sync frequencies) can be set as environment variables on the container — see [`.env.example`](.env.example) for the full list. The defaults are sensible, so most setups don't need any of them.

## Updating

```bash
docker compose pull
docker compose up -d
```

Updates are applied automatically — no manual steps.

## Backup

All your data is a single file: `watchlistarr.db` inside the folder you mapped to `/data`. Copy it somewhere safe while the container is stopped, and copy it back to restore.

## Troubleshooting

- **Container won't start** — `docker compose logs watchlistarr`. Usually a typo in an environment variable; durations must look like `15m`, `1h`, `7d`.
- **Radarr's Test button fails** — open the URL in your browser first: you should see a list in brackets (even an empty `[]` is fine). Don't forget the trailing slash.
- **Radarr imports nothing** — check the list's sync status in the watchlistarr UI; toggling the list off and back on forces an immediate full sync.
- **Errors mentioning the database** — check that the folder you mapped to `/data` exists and is writable.
- **Letterboxd errors in the Activity tab** — you may be syncing too often; increase the interval on the noisiest lists.
- **Found a bug?** — [open an issue](https://github.com/maxlainz/watchlistarr/issues).

## License

[GPL-3.0-or-later](LICENSE).

watchlistarr is not affiliated with or endorsed by Letterboxd or Radarr.
