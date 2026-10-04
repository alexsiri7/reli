# Web View

## Purpose

The web view is for looking, not doing: it shows the owner the shape of what Reli holds so they can trust it. Every change goes through Claude over MCP, which keeps one write path and one story in the journal — with a single exception, rejecting a preference.

## Requirements

### Requirement: The view is read-only with one exception

The web view SHALL offer no chat, no create or edit affordance and no action button, except rejecting a preference. Its data routes SHALL be read-only apart from that one, and an unknown data route SHALL answer 404 rather than the page.

#### Scenario: Looking for an edit button
- GIVEN a signed-in owner on a Thing's detail
- WHEN they look for a way to change it
- THEN there is none

### Requirement: Tree view

The view SHALL show the active Things as a ChildOf tree, expandable one level at a time, each row with its title and key tags, most important first. The top level SHALL be the active Things no active Thing claims as a child, excluding the "#User" anchor, preferences and observations. A row SHALL offer expansion only when it has active children.

#### Scenario: Expanding a project
- GIVEN a project with two active children and one archived
- WHEN the owner expands it
- THEN the two active children are shown

### Requirement: Thing detail with history

The view SHALL show everything on one Thing — description, notes, tags, urls, check-in date, priority — with every relationship as a navigable link labelled with its type and direction, and the Thing's journal history showing each change's actor, operation and before and after state.

#### Scenario: How did this get here
- GIVEN a Thing created by an interactive session and re-dated by the resolution pass
- WHEN the owner opens its detail
- THEN the history shows the creation by "claude_interactive" and the re-dating by "claude_scheduled"

### Requirement: The user model with its evidence

The view SHALL show every preference with its scope, its evidence as links and its evidence count, including rejected preferences shown as visibly distinct. Each live preference SHALL offer a reject action that records the rejection as the owner ("user") and journals it.

#### Scenario: Rejecting a wrong preference
- GIVEN a preference "Avoids Friday meetings" with four pieces of evidence
- WHEN the owner rejects it in the view
- THEN it is shown as rejected with its evidence still visible
- AND the journal attributes the rejection to "user"
