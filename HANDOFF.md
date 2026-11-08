# Handoff: Sachin's work (branch `Sachin`, from `feature/sachin`)

Written 2026-11-07. Everything here is what exists in this branch plus the local-only settings that are NOT in git.

## 1. What this branch adds

### Dictation (backend only; `frontend/` is owned by a teammate)
- `POST /api/dictate` turns text like "put a plank and a roof on top" into a build from the real block catalog. The UI shows it on the Choose screen. **Dictation never starts the arm.**
- `sidekick/dictation.py`: rule-based grammar (items `{tid, n, color, ref}`, connectors side / on_next / on_prev / beside_r), support tree, roof across several stacks, left/right, presets first ("make a house"), edits ("taller", "fewer blocks"), stock allocated in spoken order, fit-to-strip trimming with a note when blocks are dropped.
- OpenAI chat (`gpt-4o-mini`, JSON mode) is the backup parser. Guards: unrequested block types are rejected (falls back to rules), roofs can't support, cycles removed, color words normalised (wood/wooden/brown/plain -> `natural`).
- `sidekick/webapi.py` `dictate()`, `sidekick/server.py` `App.dictate` (under `_gen_lock`).
- Voice: `POST /api/transcribe` (raw audio body, 5 MB cap, OpenAI `whisper-1`, `sidekick/speech.py`). The teammate's new UI currently uses browser speech recognition and calls `/api/dictate`, so `/api/transcribe` is unused by the UI (weak in Safari). Switching is a frontend change for the UI owner.
- Stock rules: natural (unpainted) wood is called `natural`, about 10 per shape; each painted color has 2 per shape. Counts come only from the catalog/database.

### Database counts (read-only)
- `sidekick/inventory_db.py`: reads `public.block_inventory` (`type_id`, `color`, `quantity`) from Supabase with a read-only publishable key; 4 s timeout; falls back to the local catalog if unreachable.
- `sidekick/catalog.py` overrides only each type's `colors` from those counts. See `DATABASE.md`.
- `SIDEKICK_NO_DB=1` disables it (selftest sets it).

### Environment
- `.env` (gitignored, never commit): `OPENAI_API_KEY`, `SUPABASE_URL`, `SUPABASE_KEY`. Template in `.env.example`. `SIDEKICK_NO_LLM=1` disables OpenAI.
- Paste only the bare Supabase key (no `<>`).

### xArm
- Merged from `feature/xarm`: `sidekick/xarm_driver.py` (selected by `arm_type: "xarm"`), plus camera/calibration changes (`calib-table`, `marker_forward`).
- `xarm_jog1.py` and `xarm_test.py` in the repo root are hardware scripts. **They move the arm and have never been run by me.** Have the E-stop or battery switch within reach and use low speed.

## 2. Local-only settings (`sidekick_data/config.json`, gitignored, per machine)
These are NOT in git. Copy them by hand on another machine.

| Setting | Value |
|---|---|
| `use_sim` | `false` |
| `arm_type` | `"xarm"` |
| `layout.work_area` | `[50, 28]` |
| `layout.markers` | `{"0": [0, 0], "1": [50, 0], "2": [50, 28], "3": [0, 28]}` |
| `layout.base` | `[25, 44]` |
| `marker_to_fingertip` | `18.8` |
| `marker_forward` | `5.6` |
| `babble_range` | `200` |
| `babble_min_height` | `5` |
| `babble_step` | `80` |
| `arm_lengths` | `[7.24, 10.16, 10.16, 16.76]` |
| `us_per_degree` | `8` |
| `camera_correct` | `false` |
| `joint_min[1]` (shoulder) | `950` (was 1146) |

Known inconsistencies: `layout.base` y=44, `supply` zones (y 28-34), `pickup` (y 31) and `build_area` (y up to 35) still use the old values and lie outside or on the edge of the new 28 cm work area. Update them, then redo calibration with the new marker positions.

## 3. Known issues and open items
- **Selftest:** `python -m sidekick selftest` passes 7/9 with this machine's real-arm config; the failures are the body-model test and the full simulated build ("arm can't reach the place point"). They come from the hardware config above (the sim uses it): with an empty data dir (`SIDEKICK_DATA=<empty dir>`) both pass (body model held-out 0.27 cm, House build done), and only the camera-classification test fails (1079/1500, because the default catalog has the same-color ambiguity listed below). With this machine's own `blocks.json` it passes 396/400. Re-check after the layout is fixed.
- Camera ambiguity: with `use_color` true, same-color shapes with the same top view (cube/pillar, short/tall cylinder, arch/roof in natural) look identical; natural has no HSV range in `config.py`. `use_color: false` (pickup-spot mode) avoids it.
- "Blocks needed" panel shows per-type totals, not per-color (frontend).
- Real-arm to-do (from CLAUDE.md): jog limits and poses, calibration, babble + train, `reach`, goto/pick tests.

## 4. Working rules
- Never command moves without the E-stop or battery switch within reach; low speed first.
- `python -m sidekick selftest` before pushing.
- Branch per person, PR into `main`. Do not edit `frontend/` (teammate's). Do not commit `sidekick_data/`, `.env`, `venv/`.
