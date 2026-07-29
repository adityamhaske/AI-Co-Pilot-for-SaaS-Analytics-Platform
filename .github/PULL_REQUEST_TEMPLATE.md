## What and why

<!-- What changes, and what problem it solves. Link the issue if there is one. -->

## Checklist

- [ ] `pytest`, `ruff check .` and `black --check .` pass in `backend/`
- [ ] `tsc -b --noEmit`, `npm run lint` and `npm run build` pass in `frontend/`
- [ ] New or changed behaviour has a test

If this touches any of the following, please say how it was handled:

- [ ] **Metrics** — changed via YAML definitions, with a test asserting an exact number
- [ ] **Queries** — tenant scoping preserved, with a test in the isolation group
- [ ] **Permissions** — both gates considered (tool shape and metric `minimum_role`)
- [ ] **Errors** — no exception detail reaches the client or the model
- [ ] **UI** — semantic tokens only, verified in both themes, no fabricated placeholder data
- [ ] **Tool descriptions** — `python -m evals.runner --category direct` was run

## Verification

<!-- What you actually ran or looked at. Screenshots for UI changes, in both themes. -->
