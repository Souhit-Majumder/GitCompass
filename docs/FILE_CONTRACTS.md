# File Contracts

This document provides a comprehensive architectural overview mapping the inputs, core operations, and outputs of every critical file in the GitCompass project across both the frontend and backend.

---

## 🖥 Frontend Client (`client/src/`)

### Core Routing
#### `App.jsx`
- **Inputs:** Supabase authentication state (`session`), browser URL path.
- **Operation:** Manages protected routes and global theme state.
- **Outputs:** Rendered React Router DOM mapping to specific pages and the global Layout wrapper.

### Pages (Views)
#### `pages/Dashboard.jsx`
- **Inputs:** `user` object from session.
- **Operation:** Fetches the list of analyzed repositories associated with the user via `/api/repositories`.
- **Outputs:** Renders a grid/list of repository cards with status indicators.

#### `pages/RepositoryHotspots.jsx`
- **Inputs:** `id` (Repository UUID from URL), React state (filters: `start_date`, `commit_type`, `sortField`).
- **Operation:** Fetches `/api/analytics/{id}/hotspots` and `/api/analytics/{id}/bus-factor`. Sorts and filters the data client-side.
- **Outputs:** Renders a tabular view of volatile files (churn, insertions/deletions, ownership risk). Emits `gitcompass:set_page_context` events for the AI side-panel.

#### `pages/ArchitectureMap.jsx`
- **Inputs:** `id` (Repository UUID from URL).
- **Operation:** Fetches hierarchical repository data.
- **Outputs:** Renders the visual structure of the codebase using D3.js or React Flow components (e.g., `HotspotTreemap`).

### Components
#### `components/HotspotTreemap.jsx`
- **Inputs:** Array of hotspot objects (with file paths and churn metrics).
- **Operation:** Uses D3.js to calculate a hierarchical layout.
- **Outputs:** Interactive SVG DOM elements where node size maps to file size/volume, and color maps to churn/risk.

---

## ⚙️ Backend API Routers (`server/app/routers/`)

#### `routers/repositories.py`
- **Inputs:** HTTP POST containing a `RepositoryCreate` payload (GitHub URL).
- **Operation:** Validates URL, creates an initial database record in Supabase, and hands off the heavy processing to `miner.py` via FastAPI `BackgroundTasks`.
- **Outputs:** HTTP 202 Accepted with a `job_id` and initial repository record.

#### `routers/analytics.py`
- **Inputs:** HTTP GET requests containing `repo_id` (path) and query parameters (`start_date`, `commit_type`, etc.).
- **Operation:** Validates parameters and delegates aggregation logic to `analytics_service.py`.
- **Outputs:** JSON responses serialized via Pydantic schemas (Hotspots, Coupling, Bus Factor).

#### `routers/ai.py`
- **Inputs:** HTTP POST requests containing `repo_id`.
- **Operation:** Triggers the AI intelligence layer to generate architectural narratives based on evidence.
- **Outputs:** JSON responses containing AI-generated text (Summary, Narrative, Shifts).

---

## 🧠 Backend Domain Services (`server/app/services/`)

### Git Extraction Pipeline
#### `services/cloner.py`
- **Inputs:** `github_url` (string), `target_dir` (local absolute path).
- **Operation:** Executes `subprocess.run` to perform a `git clone --filter=blob:none` (blobless clone) to save disk space.
- **Outputs:** The local directory path containing the cloned `.git` folder.

#### `services/extractor.py`
- **Inputs:** `repo_dir` (local path), `repo_id`, `user_id`, `since_sha`.
- **Operation:** Executes `git log --numstat -M` in bulk. Parses standard output, handles file rename mapping (`{old} => {new}`), and filters out deleted/ignored files using `git check-ignore`.
- **Outputs:** Tuple of Python lists containing raw dictionaries for `commits` and `file_diffs`.

#### `services/miner.py`
- **Inputs:** `repo_id`, `github_url`, Supabase `db` client.
- **Operation:** Orchestrator. Calls `cloner.py`, then `extractor.py`, and finally handles bulk upserting the parsed data into Supabase (bypassing RLS with a service key). Executes `shutil.rmtree` cleanup on success or failure.
- **Outputs:** Database mutations (Side effects only).

### Analytics & AI Data Assembly
#### `services/analytics_service.py`
- **Inputs:** Supabase `db` client, `repo_id`, and filtering parameters.
- **Operation:** Executes Supabase REST queries to calculate file churn, temporal coupling matrices, and contributor bus factors.
- **Outputs:** Python dictionaries representing aggregated analytics data.

#### `services/evidence_assembler.py`
- **Inputs:** Supabase `db` client, `repo_id`.
- **Operation:** Collects deterministic evidence from the repository's full history. Identifies top hotspots, calculates accurate bus factors, and determines the technology fingerprint (frameworks/runtimes).
- **Outputs:** A highly structured `RepositoryEvidence` dictionary object (consumed directly by the AI layer).

#### `services/ai_service.py`
- **Inputs:** `repo_name`, `evidence` dictionary (from `evidence_assembler.py`), and `selected_model`.
- **Operation:** Constructs strict system prompts combining the evidence object. Calls `ai_providers.py` to retrieve LLM reasoning.
- **Outputs:** Python dictionaries containing the structural outputs parsed from the AI provider's JSON response.

#### `services/ai_providers.py`
- **Inputs:** `system_prompt`, `user_prompt`, `temperature`, `selected_model`.
- **Operation:** Routes requests to the correct LLM provider (Gemini, Groq). Handles network retries and quota failures.
- **Outputs:** Dictionary containing `{"text": "<generated text>", "provider_name": "<provider used>"}`.
