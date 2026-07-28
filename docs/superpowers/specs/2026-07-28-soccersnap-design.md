# SoccerSnap Design

**Date:** 2026-07-28  
**Source:** Consolidated from Traloxolcus-Chat, Traloxolcus-Gemini, Traloxolcus-Claude  
**Product:** SoccerSnap — synchronized sideline capture → local process → watch & search

## Intent

Youth soccer teams need affordable multi-angle game film without a crew. Three camera nodes along the sideline record a synchronized match; a processing station stitches angles and tags events; parents and coaches watch, search (“show me all saves”), and clip highlights from a web portal.

## Approaches considered

1. **Three separate services (Gemini-style)** — faithful to production topology; heavier to run and easier to leave half-wired.  
2. **Monolithic demo only** — fastest demo, weak production shape.  
3. **Unified package with modes (chosen)** — one Python package (`soccersnap`) exposing `rig`, `process`, `portal`, and `demo`. Demo mounts all tiers in one process with simulated cameras so the full loop works without Pi/GPU hardware. Compose can still split services later.

## Architecture

```
Field UI ──► Rig API (×3 logical cams, demo: in-process)
                 │ session manifests + SHA-256 offload
                 ▼
            Process API (ingest → stitch → events → ready)
                 │
                 ▼
            Portal API + Watch UI (auth, games, NL search, clips)
```

### Core library (`soccersnap/protocol`) — prioritized from review

**From Claude PROTOCOL.md + coordinator:**
- Versioned offload protocol: upload → server verifies SHA-256 → confirm → peer compares → mark offloaded
- Nested manifest shape (`recording` / `file` / `video` / `timing` / `checksum` / `device` / `quality`)
- Session IDs `GAME_YYYYMMDD_HHMMSS`; recording IDs `{session}_{CAM_*}`
- Exponential backoff retry on offload (0/5/10/20/40s)
- **Scheduled-start coordinator:** CAM_C broadcasts a future `scheduled_start` ISO timestamp; all cams wait and begin together

**From Chat lean Pydantic models:**
- Small typed models: `DiskStatus`, `SyncStatus`, `Checksum`, `ConfirmRequest`, `RecordingDescriptor`, `StatusResponse`
- Flat Chat-style handoff fields also retained (`offset_ms`, `checksum.algo/value`, `offloaded`) for stitch/ML
- Confirm refuses on checksum mismatch; cleanup only after confirm

- Safety gates as `GateReport(ok, reason)` — never raise for UI refusals
- Keyword NL query ontology (goals, saves, shots, set pieces, half filters, jersey `#N`)

### Rig

- Cameras: `CAM_L`, `CAM_C` (coordinator / time master), `CAM_R`
- Coordinator: preflight, **scheduled start**, stop all, peer status
- Simulated recorder in demo (writes timed media + protocol manifests)
- Framing assist scores (simulated Excellent/Good/Partial/No Field)
- REST under `/api/v1` including PROTOCOL upload/confirm

### Process

- Ingest camera assets + verify checksum
- Stitch: FFmpeg `hstack` when available; otherwise assemble a demo mosaic placeholder
- Event detection: deterministic demo detector producing soccer ontology events (real YOLO is a future plug-in)
- Marks session ready for portal

### Portal

- SQLite by default (zero-config); Postgres-ready URL setting
- Roles: admin, coach, parent
- Team code + password login for watchers
- Games list, video player, event timeline seek, NL search, clip trim metadata
- Seeded demo team/game so first run is immediately usable

### UX

- **Field** (`/field`): mobile-first ops — preflight, 3-cam status, one Record control, framing quality
- **Watch** (`/watch`): brand-first landing, then games / player / search — not a dense dashboard in the hero
- Visual direction: night-pitch green, chalk light type, lime accent, Anton + Figtree (no Inter / purple / cream-serif clichés)

## Data model (v1)

- `User`, `Team`, `Membership` (jersey_number on membership)
- `Game` (session_id, opponent, date, status, video_path)
- `CameraAsset`, `GameEvent`, `Clip`
- Manifest JSON on disk for rig↔process handoff

## Non-goals (v1)

- On-device ML, real-time stitch, cellular backhaul
- TeamSnap live OAuth (schema hooks + docs only)
- Calibrated homography stitch, jersey OCR
- Celery/Redis workers, production OTA updater

## Success criteria

1. `python -m soccersnap demo` serves Field + Watch end-to-end  
2. Coordinator scheduled-start produces shared `scheduled_start` on all cams  
3. Stop writes PROTOCOL nested manifests + Chat flat checksum fields  
4. Process pipeline verifies SHA-256, stitches, tags events  
5. Watch UI plays video, seeks from timeline, answers NL search  
6. Pytest covers protocol/offload/coordinator + full match E2E  
7. Docker Compose one-command demo works

## Testing

- Unit: gates, manifests, checksum, query parser  
- Integration: demo app TestClient — record → process → search  
- Manual: browser Field record + Watch seek
