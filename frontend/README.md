# Sketch2Stack frontend

UI shell for the HackUTD project: draw on a 2D board, choose from 3D toy-block interpretations, watch the arm build it live. Everything is mock data for now.

```
cd frontend
npm install
npm run dev     # http://localhost:5173
npm run build
```

## Screens
- `/login`, `/signup`: mock auth (any email + 6-char password). Session in localStorage.
- `/app`: workspace with stepper **Sketch → Choose build → Build live**
  - Sketch: canvas (pen, eraser, widths, undo/redo, clear), templates, optional text prompt
  - Generating: sketch → snap to blocks → 3D animation
  - Choose build: swipeable carousel of interpretations (drag, arrows, keys, dots), Swipe/Orbit toggle, stability score, block inventory, export/share
  - Build live: camera feed placeholder with fake detections, step timeline, target 3D with ghost blocks, Pause/Resume/E-STOP
- Right drawer: past projects (search, filter, open, edit drawing, generate new builds, duplicate, delete)
- Talk orb (bottom right): voice mode (mock transcript) and text chat (mock replies)
- Labs: roadmap ideas

## Where to plug in real stuff
| Placeholder | File |
|---|---|
| Auth | `src/auth/AuthContext.tsx` |
| Generation (sketch → builds) | `mockGenerate()` in `src/pages/Workspace.tsx`, builds in `src/mocks/builds.ts` |
| Camera feed | `src/components/live/CameraFeed.tsx` |
| Robot step progress | interval in `src/components/live/LiveStage.tsx` |
| Agent replies | `src/mocks/chat.ts` |
| Project storage | `src/store/projects.tsx` (localStorage) |
