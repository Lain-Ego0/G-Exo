# G-Exo Web Agent Contribution Rules

## Project scope

- `frontend/src/` is the source of truth for the React/Vite cockpit UI.
- `static/` is generated output served by FastAPI. After frontend changes, run `npm run build` from `frontend/` so the generated output is updated.
- The Alloop Ring page is an existing standalone HTML application. Preserve its WebSocket protocol, Web Bluetooth diagnostic behavior, history de-duplication, and CSV export behavior when integrating it.

## Navigation integration

- The unified web entry point exposes two top-level views: `Alloop Ring` and `G-Exo Cockpit`.
- The ring view is hosted same-origin and remains mounted while hidden so its Android Bridge/Web Bluetooth session and in-progress history sync are not torn down by navigation.
- Do not duplicate or reinterpret ring transport protocol messages in the React cockpit.
- Keep the two applications visually and behaviorally isolated unless a change explicitly requires shared state.

## Validation

- Run the narrowest relevant checks after every code change. For frontend changes, run `npm run typecheck` and `npm run build` from `frontend/`.
- Inspect the resulting diff with `git diff --check` and `git status` before committing.
- For navigation changes, manually verify both views, browser back/forward behavior, responsive layout, and that switching away from the ring does not unload its session.

## Git workflow

- Every completed code or documentation modification must be committed immediately with a focused message.
- Push each commit to the configured upstream branch immediately after the relevant checks pass.
- Never include unrelated user changes in a commit. Never rewrite or discard existing history without explicit permission.
- Before pushing, confirm the commit contains only the intended files and does not expose tokens, credentials, or local machine configuration.

## Safety

- Preserve user changes in a dirty worktree.
- Do not change the Alloop Android SDK/AAR or invent a replacement BLE protocol as part of frontend navigation work.
