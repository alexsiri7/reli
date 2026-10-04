# Access Control

## Purpose

Reli holds one person's whole life and is reachable from the public internet, so there is exactly one way in: signing in with the owner's Google account. The same sign-in admits a browser to the web view and a claude.ai connector to the MCP endpoint, and nothing is ever open by default.

## Requirements

### Requirement: Google sign-in is the only way in

Every route that serves graph data — the web view's data routes and the MCP endpoint — SHALL admit a request only on a credential minted after a Google sign-in by an allowlisted account. There SHALL be no password, no shared bearer token and no other credential. The sign-in SHALL request only the openid, email and profile scopes.

#### Scenario: A shared token is presented
- GIVEN a request to the MCP endpoint carrying a static token
- WHEN it arrives
- THEN it is refused with 401

### Requirement: Only allowlisted accounts are admitted

Only Google accounts on the configured allowlist SHALL be admitted; an empty allowlist SHALL admit nobody. An account outside it SHALL be refused with a clear sentence rather than a blank failure. The allowlist SHALL be checked again on every token issuance, so removing an address ends that account's existing connector sessions at their next refresh.

#### Scenario: A stranger signs in
- GIVEN an account not on the allowlist
- WHEN it completes Google sign-in on the web view
- THEN the view shows that Reli is invite-only
- AND no session is created

#### Scenario: Address removed
- GIVEN a connector with a live refresh chain for an allowlisted address
- WHEN the address is removed from the allowlist and the connector next refreshes
- THEN the refresh is refused and the chain is ended

### Requirement: A claude.ai connector authorises through Google

The MCP endpoint SHALL be protected by an OAuth 2.1 authorization server that a connector can discover, register with dynamically, and complete through a Reli-hosted consent page naming the client followed by Google sign-in, receiving short-lived access tokens and rotating refresh tokens. Stored authorization codes and refresh tokens SHALL be held only as digests. A bare and a trailing-slash endpoint address SHALL both work without a redirect.

#### Scenario: Adding the connector
- GIVEN the owner adds Reli's MCP URL in claude.ai with no token
- WHEN the connector discovers, registers and the owner signs in with the allowlisted account
- THEN the connector can call Reli's tools

### Requirement: The web view signs in with a session cookie

Opening the web view SHALL present Google sign-in. A successful sign-in SHALL set a secure, http-only, host-bound session cookie valid for seven days and return to the view; the view SHALL offer a "who am I" probe and sign-out. A refusal SHALL never trigger a browser credential prompt.

#### Scenario: Signed out
- GIVEN a browser with no session
- WHEN it opens the web view
- THEN it sees Google sign-in and no graph data

### Requirement: Failures name the human step

Every refusal SHALL say what a human or the connector must do next: an expired token SHALL say to refresh or re-authorise; a token Reli did not issue SHALL say to authorise against Google; a Google refusal at the code exchange SHALL name the cause and the human step; and missing sign-in settings SHALL be named individually.

#### Scenario: Redirect URI not registered
- GIVEN the Google client does not list Reli's callback address
- WHEN a sign-in returns
- THEN the response names the redirect URI mismatch as the step to fix

### Requirement: Unconfigured means closed, and the deploy stays healthy

When the signing secret is missing or shorter than 32 bytes, or any sign-in setting is missing, the graph routes and the MCP endpoint SHALL refuse every request and a warning SHALL be logged at startup. The health check SHALL stay green regardless, so a missing secret cannot roll a deploy back.

#### Scenario: Secret too short
- GIVEN a signing secret of 16 bytes
- WHEN the service boots
- THEN the MCP endpoint refuses every request
- AND the health check reports healthy
