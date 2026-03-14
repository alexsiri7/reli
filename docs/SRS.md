# Reli: Software Requirements Specification (SRS) v1.0

## 1. Introduction
Reli is a personal information manager designed for cognitive ease. It replaces fragmented task lists, note-taking apps, and project trackers with a unified, conversational interface powered by large language models (LLMs).

## 2. Problem Statement
Traditional productivity tools require users to:
*   Pre-categorize information (Is this a task? A note? A project?).
*   Manually manage deadlines, which often lead to "overdue" anxiety.
*   Search across multiple apps to find context.

## 3. The "Reli" Solution: Key Principles

### 3.1 The Universal Thing
Every piece of information is a **Thing**.
*   **Requirement:** Users can create a Thing simply by talking to the UI.
*   **Visual Typing:** The UI will automatically assign an icon (e.g., 📋, 📝, 💡) based on the AI's inference, but the underlying data structure remains flexible.
*   **Nesting:** Every Thing can have a `parent_id`, allowing for arbitrary hierarchies (e.g., a "Task" inside a "Project" inside a "Goal").

### 3.2 CheckinDate-over-Deadlines
Reli moves away from hard deadlines to a **Check-in** system.
*   **Requirement:** Every Thing has a `checkin_date`.
*   **Behavior:** On the specified date, the Thing "surfaces" in the daily brief. The user can then interact with it, snoozing it to a later date or marking it as "complete/archive".
*   **Goal:** Reduce anxiety by focusing on *when to look at it* rather than *when it's too late*.

### 3.3 AI-First Interaction
*   **Requirement:** A persistent chat interface is the primary way to interact with the system.
*   **Requirement:** Commands like "Move my 'Server Logs' check-in to tomorrow" or "What did I think about X last week?" must be handled accurately.
*   **Reliability:** The system must validate AI-proposed changes against the actual state of the database before confirming them to the user.

## 4. Functional Requirements

### 4.1 Chat & Commands
*   **FR-1:** System must support natural language creation of Things.
*   **FR-2:** System must support batch updates via chat (e.g., "Archive all completed tasks").
*   **FR-3:** System must provide a "Daily Briefing" that summarizes all Things whose `checkin_date` is today or earlier.

### 4.2 Storage & Search
*   **FR-4:** System must support full-text search across all Things.
*   **FR-5:** System must use vector-based fuzzy search for "meaning-based" retrieval (RAG).
*   **FR-6:** System must support attachments/URLs within the `data` JSON blob.

### 4.3 UI/UX
*   **FR-7:** Visual distinction between different "types" of Things using icons and colors.
*   **FR-8:** A sidebar or dashboard showing "Active Things" and "Upcoming Check-ins."
*   **FR-9:** "Snooze" functionality for easy check-in rescheduling.

## 5. Non-Functional Requirements

### 5.1 Privacy & Security
*   **NFR-1:** All data must be stored locally on the user's workstation.
*   **NFR-2:** LLM calls must be encrypted and sent via a secure API gateway.

### 5.2 Performance
*   **NFR-3:** Chat responses (Reasoning + Validation + Response) should ideally complete within 3-5 seconds.
*   **NFR-4:** Search results must be near-instant (< 200ms).

## 6. User Personas
*   **The Overwhelmed Professional:** Needs to capture thoughts quickly without thinking about where they go.
*   **The Researcher:** Needs to link disparate ideas and notes over long periods.
*   **The Minimalist:** Wants one tool to replace three.

## 7. Future Scope
*   Multi-user support with role-based access.
*   Mobile companion app for quick capture.
*   Integration with external calendars (Google/Outlook).
