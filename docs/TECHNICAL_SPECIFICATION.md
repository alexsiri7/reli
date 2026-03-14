# Reli: Technical Specification v1.0

## 1. Executive Summary
Reli is a conversation-driven, AI-first personal information manager. It is built on the concept of the **"Universal Thing"**—a schemaless, flexible unit of data that can represent tasks, notes, projects, ideas, or goals. The system prioritizes interaction through natural language, using a multi-agent pipeline to ensure storage accuracy and reliable user feedback.

## 2. Core Architecture: The Universal Thing
Instead of rigid tables for "Tasks" or "Notes," Reli uses a single polymorphic entity called a **Thing**.

### 2.1 Schema (SQLite + JSON)
The backend uses SQLite with a JSON column for flexibility while maintaining fixed columns for core indexing.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | UUID (PK) | Unique identifier. |
| `title` | TEXT | Primary display name. |
| `type_hint` | TEXT | Cosmetic label (e.g., "Task", "Idea") with emoji. |
| `parent_id` | UUID | Self-referencing FK for nesting (Projects/Subtasks). |
| `checkin_date`| TIMESTAMP | When the user should next see/interact with this. |
| `priority` | INTEGER | Simple ranking (1-5). |
| `active` | BOOLEAN | Soft-delete/Archive status. |
| `data` | JSON | Flexible fields (URLs, detailed notes, specific metadata). |
| `created_at` | TIMESTAMP | Creation record. |
| `updated_at` | TIMESTAMP | Last modification record. |

## 3. The Subagent Pipeline (Interaction Flow)
To ensure reliability, every user message passes through a three-stage pipeline before a response is rendered.

### 3.1 Stage 1: Context Agent
*   **Input:** User Message + Recent Conversation History.
*   **Action:** Generates search queries and filters to retrieve relevant "Things" from SQLite and ChromaDB (Vector Store).
*   **Output:** Search parameters.

### 3.2 Stage 2: Reasoning Agent
*   **Input:** User Message + History + Retrieved Relevant Things.
*   **Action:** Decides what changes need to happen in storage. It **only** outputs structured data.
*   **Output (JSON):**
    ```json
    {
      "storage_changes": {
        "create": [{"title": "...", "data": {...}}],
        "update": [{"id": "...", "changes": {...}}],
        "delete": ["id1", "id2"]
      },
      "questions_for_user": ["Which project should this link to?"],
      "reasoning_summary": "Brief internal note explaining the intent."
    }
    ```

### 3.3 Stage 3: Validation & Execution
*   The Backend validates the JSON output (schema checks, link integrity).
*   Changes are committed to SQLite and Vector Store.
*   **Rule:** Apply confident changes first; ask remaining questions afterward.

### 3.4 Stage 4: Response Agent
*   **Input:** Reasoning Summary + Applied Changes + Original Message.
*   **Action:** Translates the technical state change into a natural, friendly confirmation.
*   **Output:** "I've updated your 'Server Logs' check-in to tomorrow."

## 4. Technical Stack (Local Workstation)
*   **Backend:** FastAPI (Python 3.10+)
*   **Database:** SQLite (Primary Storage) + ChromaDB (Vector Search / RAG)
*   **LLM Gateway:** OpenRouter / Requesty (to access Gemini 1.5/2.0 Pro)
*   **Frontend:** React (Vite) + Tailwind CSS + Lucide Icons (for UI type-hints)
*   **State Management:** Zustand (for lightweight UI updates)

## 5. Deployment Model
Reli is designed to run locally on an internal workstation.
*   **Containerization:** Single `docker-compose.yml` (App + SQLite volume).
*   **Network:** Localhost access only by default.

## 6. Context Management & RAG Strategy
*   **Under 500 Things:** Full metadata summary injected into the Reasoning Agent's context.
*   **Over 500 Things:** Vector-based retrieval (ChromaDB) to pull the top 10-20 most relevant Things based on cosine similarity to the user's intent.
*   **Hierarchy:** Always include the immediate parent/children of any retrieved Thing to maintain context.
