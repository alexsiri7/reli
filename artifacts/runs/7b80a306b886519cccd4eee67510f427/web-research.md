# Web Research: fix #758

**Researched**: 2026-04-29T08:15:00Z
**Workflow ID**: 7b80a306b886519cccd4eee67510f427

---

## Summary

The "HTTP 000000" error indicates a total failure to establish a valid HTTP connection, often caused by the application not listening on the correct interface/port or crashing before responding. In the context of Railway, this is most commonly caused by a mismatch between the application's listening port (hardcoded to 8000 in the Dockerfile) and the `PORT` environment variable Railway expects the application to use.

---

## Findings

### Railway Health Checks & Networking

**Source**: [Railway Documentation - Healthchecks](https://docs.railway.com/deployments/healthchecks)
**Authority**: Official Platform Documentation
**Relevant to**: Deployment failure and health check configuration.

**Key Information**:
- Railway waits for a `200 OK` from the configured health check path before routing traffic.
- Default timeout is 300 seconds.
- **Healthcheck Hostname**: Requests originate from `healthcheck.railway.app`. If the application uses "Allowed Hosts" (common in Django/FastAPI middleware), this must be permitted.
- **Port Injection**: Railway injects a `PORT` environment variable. Applications **must** listen on this port.

---

### Application Failed to Respond (502/000000)

**Source**: [Railway Documentation - Application Failed to Respond](https://docs.railway.com/networking/troubleshooting/application-failed-to-respond)
**Authority**: Official Troubleshooting Guide
**Relevant to**: Troubleshooting the "000000" / No-response state.

**Key Information**:
- Most common cause: Application not listening on `0.0.0.0`.
- Second most common: Port mismatch (Application listening on port X, Railway expects port Y).
- **Uvicorn Specifics**: `uvicorn` needs explicit flags: `--host 0.0.0.0 --port $PORT`.

---

### Understanding "HTTP 000000"

**Source**: [Common Monitoring Tool Standards (e.g., Uptime Kuma, curl)](https://github.com/louislam/uptime-kuma)
**Authority**: Open source industry standards for uptime monitoring.
**Relevant to**: Interpreting the error message in the issue.

**Key Information**:
- `000` or `000000` is the default value when no status code is returned.
- Indicates "Connection Refused", "Connection Reset", or "Empty Response".
- In Railway, this often happens if the "Target Port" in the service settings is set to something other than what the process is actually using.

---

## Code Examples

### Recommended FastAPI/Uvicorn Start Command
```bash
# Instead of hardcoding 8000
uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Dockerfile Healthcheck Fix
```dockerfile
# Use the internal port for local check, but ensure the app respects Railway's PORT env
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen(f'http://localhost:{os.environ.get(\"PORT\", \"8000\")}/healthz')" || exit 1
```

---

## Gaps and Conflicts

- **Target Port Setting**: It is unknown if the Railway dashboard has a "Target Port" override configured.
- **Logs**: Without access to the Railway Dashboard logs, we cannot confirm if the application is hitting an `ImportError` or `DatabaseConnectionError` during startup, which would also result in a health check failure.

---

## Recommendations

1. **Update Dockerfile**: Change the `CMD` to use the `PORT` environment variable: `CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]`.
2. **Verify Interface**: Ensure `uvicorn` is binding to `0.0.0.0` (it currently is, but verify it's not being overridden by config files).
3. **Internal Health Check**: Update the `HEALTHCHECK` command in the `Dockerfile` to be more resilient or ensure it targets the same port the app is listening on.
4. **Check Railway Dashboard**: Verify that the "Public Networking" settings in Railway point to the correct port (if `PORT` is used, Railway usually handles this automatically unless a custom "Target Port" is set).

---

## Sources

| # | Source | URL | Relevance |
|---|--------|-----|-----------|
| 1 | Railway Healthchecks | https://docs.railway.com/deployments/healthchecks | Core platform behavior |
| 2 | Railway Troubleshooting | https://docs.railway.com/networking/troubleshooting/application-failed-to-respond | Specific error causes |
| 3 | Railway FastAPI Guide | https://docs.railway.com/guides/fastapi | Best practices for the stack |
| 4 | Railway LLMS | https://docs.railway.com/llms.txt | Comprehensive doc structure |
