# Validation Results

**Generated**: 2026-05-02 19:12
**Workflow ID**: 71a21444dc75f75167bd149ae06d3f82
**Issue**: #909 — Main CI red: Deploy to staging (62nd `RAILWAY_TOKEN` expiration, 22nd today)
**Status**: ALL_PASS (docs-only diff — code suites N/A)

---

## Summary

| Check | Result | Details |
|-------|--------|---------|
| Diff scope (docs-only) | ✅ | All 4 changed paths are under `artifacts/runs/71a21444dc75f75167bd149ae06d3f82/` |
| No Category 1 rotation file | ✅ | `.github/RAILWAY_TOKEN_ROTATION_909.md` absent |
| Validator code unchanged | ✅ | `.github/workflows/staging-pipeline.yml:49-58` matches the snippet quoted in the investigation |
| Runbook unchanged | ✅ | `docs/RAILWAY_TOKEN_ROTATION_742.md` not in diff |
| Type check | N/A | No source files touched |
| Lint | N/A | No source files touched |
| Format | N/A | No source files touched |
| Tests | N/A | No source files touched |
| Build | N/A | No source files touched |
| Visual regression | N/A | No frontend changes |

---

## Diff Inspection

**Command**: `git diff --name-only origin/main..HEAD`

```
artifacts/runs/71a21444dc75f75167bd149ae06d3f82/implementation.md
artifacts/runs/71a21444dc75f75167bd149ae06d3f82/investigation.md
artifacts/runs/71a21444dc75f75167bd149ae06d3f82/validation.md
artifacts/runs/71a21444dc75f75167bd149ae06d3f82/web-research.md
```

All paths are confined to this run's artifact directory. No `backend/`, `frontend/`, `.github/workflows/`, `docs/`, or `data/` paths are touched — matches the scope declared in `implementation.md` and the Polecat Scope Discipline rule in `CLAUDE.md`.

---

## Category 1 Guardrail (Railway Token Rotation)

**Command**: existence check on `.github/RAILWAY_TOKEN_ROTATION_909.md`
**Result**: ✅ Pass — file does not exist

`CLAUDE.md` § Railway Token Rotation: "Do NOT create a `.github/RAILWAY_TOKEN_ROTATION_*.md` file claiming rotation is done." The runbook for humans remains at `docs/RAILWAY_TOKEN_ROTATION_742.md` (untouched).

---

## Validator Drift Check

**Command**: read `.github/workflows/staging-pipeline.yml` lines 49–58
**Result**: ✅ Identical to the snippet quoted in `investigation.md` § Patterns to Follow.

The validator code that fired the failure on run 25257755620 is byte-for-byte the same as on the prior 61 incidents. This confirms the investigation's claim that the failure mode is credential rejection, not a regression in the validator.

---

## Code Suites

**Command**: N/A
**Result**: N/A

Per `implementation.md` § Validation Results: type / lint / format / test / build suites are not run because the diff contains no source files. The repository's CI is configured to run those suites on changes under `backend/` and `frontend/`; documentation-only PRs do not meaningfully exercise them.

If a future maintainer wants belt-and-suspenders coverage, the safe commands in this repo are:

| Suite | Command | Why N/A here |
|-------|---------|--------------|
| Backend tests | `cd backend && pytest` | No `.py` files changed |
| Frontend type-check | `npm --prefix frontend run type-check` (or `tsc --noEmit`) | No `.ts`/`.tsx` files changed |
| Frontend lint | `npm --prefix frontend run lint` | No `.ts`/`.tsx` files changed |
| Frontend build | `npm --prefix frontend run build` | No `.ts`/`.tsx`/`.css` files changed |
| Visual regression | `npm --prefix frontend run test:screenshots` | No UI changes |

---

## Markdown Sanity Check

| File | Notes |
|------|-------|
| `investigation.md` | Frontmatter, sections, fenced code blocks all balanced |
| `web-research.md` | Frontmatter, sections, fenced code blocks all balanced |
| `implementation.md` | Tables, sections balanced |
| `validation.md` | Tables, sections balanced |

No broken code fences; tables render; cross-references between artifacts (investigation ↔ web-research ↔ implementation ↔ validation) are consistent.

---

## Files Modified During Validation

None. Validation was inspection-only — no fixes were required.

---

## Next Step

Continue to PR creation. The PR body should include `Fixes #909` and route the human operator to `docs/RAILWAY_TOKEN_ROTATION_742.md`, with a pointer to `web-research.md` Recommendations §1 (verify token type — Account vs Project — before another like-for-like rotation, since the chain has now repeated 22 times today).
