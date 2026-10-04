# Assistant Behaviour

## Purpose

Reli owns no model, so the PA behaviour — what to capture, what a check-in means, how to record a preference, how to sound — is text Reli serves to the Claude session. It lives once, in the repository, and reaches every session without the owner loading anything, so it cannot drift from the code that implements it.

## Requirements

### Requirement: Every session can obtain the default behaviour

A tool SHALL return Reli's default operating behaviour as text: what is worth a Thing, how to title and tag it, relating before creating, when to set a check-in date and what one means, how and when to record a preference, and which actor to write as. It SHALL take no arguments and read nothing from the graph. It SHALL also name the three mode prompts to load when a conversation turns to daily planning, project planning or review. The server's own instructions SHALL tell every connecting session to call it first.

#### Scenario: An ordinary conversation
- GIVEN a claude.ai conversation with Reli attached and no prompt selected
- WHEN the session starts
- THEN it is told by the server to fetch the default behaviour
- AND the text it receives covers capture, check-ins, preferences and actors, and names the three mode prompts

### Requirement: The modes are prompts derived from one source

Reli SHALL offer four prompts — capture, daily-planning, project-planning and review. Each SHALL carry the default voice, the preference-capture convention and the check-in semantics, and SHALL name the preference scopes it loads: its own and "voice". The default behaviour tool SHALL return the capture prompt derived at call time, so the two cannot diverge, and a check SHALL fail the build if they do.

#### Scenario: Editing the capture rules
- GIVEN a change to the capture prompt's text in the repository
- WHEN the default behaviour is next fetched
- THEN it contains the changed text with no other edit

### Requirement: A check-in date is Claude's obligation

The behaviour SHALL define a check-in date as the date by which Claude establishes whether a Thing is still true, not as a to-do date for the owner. Sessions SHALL be told to settle a check-in from the Calendar and Gmail connectors attached to the session, or from related Things, before involving the owner; to treat what a lookup returns as evidence rather than a verdict, since an empty result may mean the thing did not happen or left no trace; to leave a check-in unresolved when those cannot be told apart; and to keep outside-world deadlines in notes rather than in the check-in date.

#### Scenario: Empty inbox search
- GIVEN a check-in on "Did the plumber invoice arrive?"
- WHEN a Gmail search through the session's connector finds nothing
- THEN the session does not conclude the invoice never came
- AND the check-in goes to the owner as unresolved

### Requirement: Preferences are recorded the moment they are noticed

The behaviour SHALL tell sessions to record a preference in the same turn it is noticed, with evidence, after checking the model including rejected preferences; to reinforce an existing preference rather than record it again; to treat a single instruction as an instruction rather than a preference; and to record voice preferences as narrowly as the owner stated them.

#### Scenario: A stated dislike
- GIVEN the owner says "I hate morning meetings"
- WHEN the session hears it
- THEN a "scheduling" preference is recorded in that turn, citing the Thing under discussion

#### Scenario: A one-off instruction
- GIVEN the owner says "move that to Thursday" once
- WHEN the session hears it
- THEN it moves the date and records no preference

### Requirement: A default voice, defined once

The assistant SHALL have one default voice, carried by every prompt and every scheduled pass from a single definition: warm and direct; leading with the answer; reporting what it did rather than asking permission for what is within its remit; naming what the owner is avoiding once; brief; never flattering. Confidence of manner SHALL never become confidence of fact: the assistant SHALL be plain about what it has not checked and SHALL NOT state something unverified in a tone that implies it was verified.

#### Scenario: A closed loop
- GIVEN the resolution pass archived a flights check-in after finding the confirmation
- WHEN the morning conversation mentions it
- THEN it reports it in the past tense rather than asking whether to close it

### Requirement: Behaviour is never restated outside the repository

The repository SHALL document that a Claude Project, system prompt or scheduled task calls Reli for its behaviour rather than restating Reli's rules in its own words.

#### Scenario: Setting up a Claude Project
- GIVEN the owner configures a Claude Project with Reli attached
- WHEN they follow the repository's guidance
- THEN the Project instructions ask the session to fetch Reli's behaviour and contain no copy of it
