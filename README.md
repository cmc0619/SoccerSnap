# SoccerSnap

Synchronized sideline capture → local processing → watch & search.

SoccerSnap consolidates the best ideas from three Traloxolcus prototypes into one finished product:

| Source | Kept |
|--------|------|
| **Claude** | `PROTOCOL.md` offload flow, nested manifests, **scheduled-start coordinator** |
| **Chat** | Lean Pydantic status/confirm models, checksum-gated offload, safety gates |
| **Gemini** | Three-tier product loop (rig → process → portal), TeamSnap-ready membership model |

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
# Local demo uses SOCCERSNAP_DEMO_MODE=true defaults (override secrets for anything exposed).
soccersnap demo
```

Open [http://127.0.0.1:7420](http://127.0.0.1:7420)

| Surface | URL | Purpose |
|---------|-----|---------|
| Landing | `/` | Brand entry |
| Field Ops | `/field/` | Preflight, scheduled Record, Process |
| Watch | `/watch/` | Team login, timeline, NL search |
| API docs | `/docs` | OpenAPI |

**Demo login:** team code `SNAP26` · `parent` / `parent` · `coach` / `coach`

Ops (confirm/cleanup/upload/process) require header `X-SoccerSnap-Key` (see `/api/demo/info` in demo, or `SOCCERSNAP_OPS_API_KEY`). Watch routes use a signed server session cookie after login.

### Docker

Compose binds `127.0.0.1:7420` and requires unique secrets:

```bash
export SOCCERSNAP_SECRET_KEY=$(openssl rand -hex 32)
export SOCCERSNAP_OPS_API_KEY=$(openssl rand -hex 16)
export SOCCERSNAP_ADMIN_PASSWORD=$(openssl rand -hex 12)
docker compose up --build
```

## Match loop

1. **Field → Preflight** — disk, sync, framing, battery/temp gates  
2. **Record** — CAM_C schedules a shared `scheduled_start`; L/C/R begin together  
3. **Stop** — writes PROTOCOL nested manifests + media + SHA-256  
4. **Process** — upload/verify/confirm → FFmpeg stitch → event tags → portal ready  
5. **Watch** — seek timeline, search `saves`, `goals`, `#9`, `first half`

One-shot API:

```bash
curl -X POST 'http://127.0.0.1:7420/api/demo/run-match?duration_sec=4'
```

## Protocol highlights

See [`PROTOCOL.md`](PROTOCOL.md).

- Nested manifest (`recording` / `file` / `video` / `timing` / `checksum` / …)  
- Chat `ConfirmRequest` with `{ algo, value }` — mismatch refuses delete  
- Retry backoff 0 / 5 / 10 / 20 / 40s  

## Develop

```bash
pytest
```

Layout:

```
src/soccersnap/
  protocol/   # manifests, checksum, offload, gates, NL query, lean schemas
  rig/        # fleet + scheduled-start coordinator + API
  process/    # ingest, stitch, events
  portal/     # auth, games, search, clips
  demo/       # unified app + seed
  web/        # Field + Watch UI
```

## Non-goals (v1)

Live TeamSnap OAuth, calibrated homography, on-device ML, cellular backhaul.
