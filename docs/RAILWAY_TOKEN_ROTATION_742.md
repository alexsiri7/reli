# Railway Token Rotation — Issue #742

## Problem

Main CI is red: The staging deployment fails because `RAILWAY_TOKEN` GitHub Actions secret has expired.

**Error**: 
```
RAILWAY_TOKEN is invalid or expired: Not Authorized
```

This is the **third occurrence** (previous: #733, #739).

## Root Cause

The `RAILWAY_TOKEN` used by `.github/workflows/staging-pipeline.yml` has expired.

### Why It Keeps Expiring

When creating tokens on Railway, the default TTL may be short (e.g., 1 day or 7 days). Previous rotations may have used these defaults. **The new token must be created with "No expiration".**

## Resolution

1. **Create a new Railway token** (requires Railway dashboard access at https://railway.com/account/tokens)
   - Name: `github-actions-permanent`
   - **Expiration: No expiration** (critical — do not accept default TTL)

2. **Update the GitHub secret**:
   ```bash
   gh secret set RAILWAY_TOKEN --repo alexsiri7/reli
   # Paste the new token when prompted
   ```

3. **Re-run the failed CI**:
   ```bash
   gh run rerun 25015146868 --repo alexsiri7/reli --failed
   ```

## Impact

- **Blocked**: All automated staging deployments until token is rotated
- **Unblocked**: Manual deployments remain possible
- **Files affected**: `.github/workflows/staging-pipeline.yml` uses the token for deploy and health checks

## References

- Investigation: `/home/asiri/.archon/workspaces/alexsiri7/reli/artifacts/runs/a09df3e83fce8f061c4653b63ae12a2e/investigation.md`
- GitHub issue: #742
- Previous incidents: #733, #739
