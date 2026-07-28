# SoccerSnap Implementation Plan

> **For agentic workers:** Execute task-by-task. Steps use checkbox syntax.

**Goal:** Ship a finished SoccerSnap product: simulated 3-cam capture → process → watch/search.

**Architecture:** Unified FastAPI package with `demo` mode mounting rig + process + portal; SQLite; FFmpeg stitch; keyword NL search.

**Tech Stack:** Python 3.12, FastAPI, Uvicorn, Pydantic v2, SQLAlchemy, SQLite, FFmpeg, vanilla HTML/CSS/JS, pytest, Docker.

## Global Constraints

- Package name: `soccersnap`
- Cameras: `CAM_L`, `CAM_C`, `CAM_R` only
- Demo must run without Pi/GPU: `python -m soccersnap demo`
- Default ports: demo `7420`
- No TeamSnap live OAuth in v1
- Brand fonts: Anton + Figtree; palette night-pitch / chalk / lime

---

### Task 1: Package skeleton + protocol library

**Files:**
- Create: `pyproject.toml`, `src/soccersnap/{__init__,__main__,config}.py`
- Create: `src/soccersnap/protocol/{__init__,gates,manifests,checksum,query}.py`
- Create: `tests/test_protocol.py`

- [ ] Implement gates, manifests, sha256, NL query
- [ ] Pytest green
- [ ] Commit

### Task 2: Database + portal models

**Files:**
- Create: `src/soccersnap/db.py`, `src/soccersnap/models.py`
- Create: `tests/test_db.py`

- [ ] SQLAlchemy models + engine helpers
- [ ] Seed helper for demo team/game
- [ ] Commit

### Task 3: Rig API + simulator

**Files:**
- Create: `src/soccersnap/rig/{__init__,app,coordinator,recorder,framing}.py`
- Create: `tests/test_rig.py`

- [ ] Status, preflight, record start/stop, listings, confirm/cleanup
- [ ] Commit

### Task 4: Process pipeline

**Files:**
- Create: `src/soccersnap/process/{__init__,app,ingest,stitcher,events,pipeline}.py`
- Create: `tests/test_process.py`

- [ ] Ingest + checksum, FFmpeg stitch, demo events, ready
- [ ] Commit

### Task 5: Portal API + auth

**Files:**
- Create: `src/soccersnap/portal/{__init__,app,auth,routes}.py`
- Create: `tests/test_portal.py`

- [ ] Login, games, events, search, clips, media
- [ ] Commit

### Task 6: Demo app + web UIs

**Files:**
- Create: `src/soccersnap/demo/{__init__,app,seed}.py`
- Create: `src/soccersnap/web/field/*`, `src/soccersnap/web/watch/*`
- Create: `tests/test_e2e.py`

- [ ] Mount all + seed + Field/Watch UIs
- [ ] E2E: record → process → search
- [ ] Commit

### Task 7: Docker, README, polish

**Files:**
- Create: `Dockerfile`, `docker-compose.yml`, `README.md`, `.gitignore`, `.env.example`
- [ ] Verify demo + tests
- [ ] Commit + push + PR
