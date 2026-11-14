# Service Boundaries

## Purpose

Reli is the memory and obligations layer for a Claude-run PA, measured by one test: MCP plus claude.ai plus scheduled tasks together make a complete PA. These boundaries keep Reli from growing what the session already has — a model, a data integration, a second way in — and keep one person's private data out of a public repository.

## Requirements

### Requirement: No model inside Reli

No LLM call SHALL originate inside the service, and the service's full test and quality gates SHALL pass with no model credential in the environment. Every judgement SHALL happen in the Claude session using Reli.

#### Scenario: Gates without a model key
- GIVEN an environment with no LLM API key
- WHEN the repository's gates run
- THEN they pass

### Requirement: No third-party data integration

Reli SHALL expose no Calendar, Gmail or other third-party data tools and SHALL hold no data-access credential or refresh token. The only Google credential SHALL be the sign-in client identity, used to sign a user in and for nothing else, with nothing derived from it persisted beyond a request. A pass that needs outside data SHALL bring its own connector.

#### Scenario: Listing Reli's tools
- GIVEN a connected MCP session
- WHEN it lists Reli's tools
- THEN none reads Calendar or Gmail

### Requirement: MCP is the only write path

Every change to the graph SHALL arrive through the MCP tools, apart from the web view's preference rejection. There SHALL be no public write API and nothing scheduled SHALL run inside the service.

#### Scenario: Looking for a background job
- GIVEN a running Reli service
- WHEN no client is connected
- THEN nothing in the service changes the graph

### Requirement: No real user data in the public repository

No real user data SHALL be committed to the repository: no graph exports or dumps, no statistics derived from real data, no recorded Gmail or Calendar fixtures, no briefings, preferences or evidence, and no logs with Thing titles or notes. Test fixtures SHALL be synthetic.

#### Scenario: A test needs example Things
- GIVEN a new test
- WHEN it needs Things to work on
- THEN it uses hand-written synthetic data

### Requirement: Automation never reads the graph

No CI workflow or other repository automation SHALL read any route that answers with Things, and GitHub issues SHALL never be an alerting channel for anything touching user data. A check SHALL fail the build if a workflow reads a data route.

#### Scenario: A workflow calling the data API
- GIVEN a workflow change that requests a data route
- WHEN CI runs
- THEN the gate fails

### Requirement: Workflow tokens carry only the grants they declare

Every workflow job SHALL run with `GITHUB_TOKEN` permissions declared either at the top of its workflow or on the job itself, never on the repository's default grants. A check SHALL fail the build if a job declares none.

#### Scenario: A job without a permissions block
- GIVEN a workflow with no top-level permissions and a job that declares none
- WHEN CI runs
- THEN the gate fails naming that job

### Requirement: Deploy notifications travel over https

A workflow step that posts a notification to ntfy SHALL address it with `https://`, because the topic in the URL is the channel's only secret. A check SHALL fail the build if a step reaches ntfy without that scheme.

#### Scenario: A plaintext notification
- GIVEN a workflow step that posts to ntfy with no `https://` scheme
- WHEN CI runs
- THEN the gate fails naming that step

### Requirement: A failing Railway token files an issue

A daily check SHALL verify the Railway deploy token and, when it is missing or the Railway API rejects it, file a GitHub issue pointing at the rotation runbook unless one is already open. The issue SHALL carry no user data.

#### Scenario: An expired Railway token
- GIVEN a Railway token the Railway API rejects
- WHEN the daily token check runs
- THEN it fails and an open issue names the expired token and the rotation runbook

### Requirement: Dependencies install locked and are audited

CI SHALL install backend dependencies from the committed lockfile and refuse a lockfile that disagrees with the manifest. A scheduled scan, and every change to a lockfile, SHALL audit the backend and frontend dependencies the committed lockfiles pin for known vulnerabilities.

#### Scenario: A lockfile change pulls in a vulnerable package
- GIVEN a change to a committed lockfile that pins a package with a known vulnerability
- WHEN the dependency scan runs
- THEN the audit fails

### Requirement: Deployment is safe by default

The service SHALL run on Postgres from a required connection string with no fallback, and SHALL refuse to start without it. It SHALL apply its migrations on boot and fail the boot on a migration failure. Schema changes after the baseline SHALL be additive unless a destructive change explicitly opts in with its data preserved.

#### Scenario: Missing database URL
- GIVEN no database connection string is set
- WHEN the service starts
- THEN it refuses to start with a message naming the missing setting

### Requirement: Every response carries security headers

Every response SHALL carry security headers, including a content security policy restricted to the service's own origin.

#### Scenario: Any response
- GIVEN a running Reli service
- WHEN it answers any request
- THEN the response carries security headers, including a content security policy restricted to its own origin

### Requirement: The image ships only the service

The deployed image SHALL contain only the running service and its web view, not retired reference code.

#### Scenario: Inspecting the deployed image
- GIVEN the image built for deployment
- WHEN its contents are listed
- THEN it holds the running service and its web view and no retired reference code
