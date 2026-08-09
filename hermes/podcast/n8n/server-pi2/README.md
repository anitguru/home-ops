# pi2 n8n control plane

This stack runs the portable podcast n8n control plane on Raspberry Pi 5
`pi2` at `10.0.70.12`. The external ARM64 JavaScript/Python/CocoIndex task
runner remains on `pi1` and connects to broker port 5679.

Runtime-only files are deliberately outside Git:

- `/etc/n8n/n8n.env` — n8n settings and runner broker token
- `/etc/n8n/n8n-podcast.env` — podcast service secrets
- `/app/data/n8n` — SQLite, credentials, Data Tables, execution history,
  binary evidence, community nodes, and the n8n encryption-key config

The first restore stays pinned to n8n 2.30.7. Import or restore workflows with
all schedules inactive, verify health and the external runner, then hand off
exactly one production schedule from the old control plane.

```bash
cd /app/stacks/n8n
docker compose up -d
docker compose ps
docker compose logs --tail=100 n8n
```

The stack uses `restart: unless-stopped`; a reboot verification is required
before the host is considered recovered.
