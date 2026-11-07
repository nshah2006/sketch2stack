# Sketch2Stack frontend

The 3D app for the Sidekick arm: draw on a 2D board, choose from 3D block interpretations, watch the arm build it live.

## Run it

```
# 1. the robot server (from the repo root; simulator until the arm is ready)
python -m sidekick ui --sim --speed 3          # http://localhost:8000

# 2a. use the built app (served by the robot server at http://localhost:8000)
cd frontend && npm install && npm run build

# 2b. or develop with hot reload (proxies /api to the server)
cd frontend && npm run dev                       # http://localhost:5173
```

## What's real and what's still mock

| Feature | Backed by |
|---|---|
| Sketch → builds | `POST /api/generate` (`sidekick/webapi.py`): fills the drawn outline with real block shapes, plus the closest presets; every build is checked by the planner (support, roof, reach, inventory) |
| Stability % and warnings | the planner |
| Blocks needed / owned | `GET /api/info` inventory (`sidekick_data/blocks.json`) |
| Build this | `POST /api/build` → a `run_id` |
| Live view, steps, pickup prompts, safety pause | `GET /api/status`, `GET /api/frame.jpg` |
| Pause / Resume / E-STOP / Build again | `/api/pause`, `/api/resume`, `/api/stop`, `/api/build` |
| Auth, Talk panel, Labs, share link | still mock |

## Stale-state rules
- Every server start has a `server_id`; a stored run from an older server is dropped.
- Every build has a `run_id`. The live view shows only the status of its own run, and the server refuses pause/stop for any other run (409).
- Only one build can start at a time (server lock + a ref guard against double clicks). If the arm is busy, the app attaches to the running build instead.
- Late `/api/generate` answers are ignored (request ids), and leaving the generating screen cancels it.
- Projects store whole builds (`s2s.projects.v2`); the old mock-id format is discarded.
- Reloading or opening a second tab mid-build reattaches to the running build.
