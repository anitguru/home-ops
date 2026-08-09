# CocoIndex-capable n8n task runner

This directory builds a pinned external n8n task-runner image with CocoIndex
and psycopg available to Python Code nodes. It is intentionally a runner
sidecar, not an API service, and connects directly to n8n's task broker.

The runtime secret file is `/etc/n8n-runner-cocoindex.env` and is never stored
in Git. It must contain:

```dotenv
N8N_RUNNERS_AUTH_TOKEN=<n8n runner broker token>
N8N_RUNNERS_TASK_BROKER_URI=http://<n8n-host>:5679
```

Build and validate imports:

```bash
docker compose build
docker run --rm --entrypoint /opt/runners/task-runner-python/.venv/bin/python \
  local/n8n-runners-cocoindex:2.30.7-cocoindex0.3.9 \
  -c 'import cocoindex, psycopg; print("imports-ok")'
```

Start and inspect:

```bash
docker compose up -d
docker compose ps
docker compose logs --tail=100 task-runners
```

The image tag must remain aligned with the n8n server version. Supabase holds
the persistent topic/message index; the runner itself is disposable compute.

The launcher config is bind-mounted read-only so allowlist changes do not
require rebuilding the compiled CocoIndex image. `abc` must remain in the
stdlib allowlist: n8n's Python sandbox sanitizes `sys.modules`, and removing
`abc` while retaining `typing` creates a second `ABCMeta` identity that breaks
packages using `Protocol`. Transitive imports are enabled only for the two
explicit roots (`cocoindex` and `psycopg`) and their dependencies.

When another external runner is connected to the same broker, it must not
advertise Python unless it carries this exact environment. The temporary
CT143 runner is therefore JavaScript-only via `ct143-js-only.conf`; Python
tasks deterministically execute on this ARM64 image.
