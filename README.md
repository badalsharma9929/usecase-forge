# UseCaseForge

**Paste a company website and get grounded GenAI/ML use cases, with public datasets to prototype them.**

Five AI agents read the company's own site, draft use cases that cite the passages they're
based on, critique and revise the plan, then search Hugging Face and Kaggle for datasets
that actually fit. It runs as a serverless web app on Vercel, with a live view of every agent.

**Live demo:** _add your Vercel URL here_

---

## How it works

```
           ┌────────────┐   ┌────────────┐   ┌──────────┐   ┌───────────────┐   ┌──────────┐
 URL ────▶ │ Researcher │──▶│ Strategist │──▶│  Critic  │──▶│ Dataset scout │──▶│ Reporter │
           └────────────┘   └────────────┘   └──────────┘   └───────────────┘   └──────────┘
            scrape, chunk,     use cases       score 1-10       HF + Kaggle        Markdown
            embed, retrieve    citing [S#]     < 7: revise ↺    LLM relevance      + JSON
```

| | What it does |
|---|---|
| **Researcher** | Fetches pages (Jina Reader), strips navigation noise, chunks and embeds them (Gemini embeddings), builds a structured company profile, and retrieves the most relevant passages |
| **Strategist** | Writes 4-5 company-specific use cases. Each one cites source IDs, and citations the model invents are removed in code |
| **Critic** | Scores the plan against a rubric (specificity, grounding, feasibility, coverage, impact). Weak plans go back with feedback, with at most 2 revisions |
| **Dataset scout** | Searches Hugging Face and Kaggle per keyword, broadening the query when needed. An LLM keeps only datasets that fit the task |
| **Reporter** | Builds the final report with sources |

## Architecture (Vercel)

```
Browser ──POST /api/runs──▶ FastAPI (Vercel Function) ──send──▶ Vercel Queue
   ▲                              │                                 │
   │                         first snapshot                         ▼
   │                              ▼                      Worker (queue-triggered function)
   └──GET /api/runs/{id}── Vercel Blob ◀── snapshot ──  runs ONE agent step, then enqueues the next
        (polls every 2.5s)   (private)
```

- **One step per message.** Each agent runs in its own short invocation, so a run is never limited by a single function's timeout, and a crash retries only that step.
- **Idempotent.** Each queue message carries the snapshot sequence number it expects; duplicate or stale deliveries are ignored.
- **Immutable snapshots.** Every state change writes a new blob (`runs/<id>/<seq>.<rev>.json`), so reads are never stale and each run keeps a full audit trail.
- **Retries vs. failures.** Gemini overload (503 or per-minute 429) is retried with backoff. Permanent problems (site unreachable, daily quota used up, invalid key) end the run with a clear message.
- **Bring your own key.** Visitors can use their own Gemini key. It is encrypted (Fernet) inside queue messages and never stored or logged.
- **Guardrails.** URL validation rejects private IPs and localhost, there's a per-IP rate limit and a daily cap on the shared key, a strict CSP, and the UI renders text with no `innerHTML`.

The same agents also run locally through a LangGraph `StateGraph`. `graph.py` defines the control flow once and both runners use it.

## Run locally

```bash
python -m venv .venv
.venv\Scripts\activate             # macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env             # add GOOGLE_API_KEY
uvicorn usecase_forge.web:app --reload
```

Open http://localhost:8000. Locally, runs execute in a background thread with in-memory storage, so no cloud setup is needed.

**Demo mode** runs the full UI with canned agent responses and makes no API calls:

```bash
uvicorn usecase_forge.web:app --env-file .env.demo
```

**Command line:**

```bash
usecase-forge https://byjus.com/ --extra https://byjus.com/about-us/
```

**Tests** (offline, no keys needed):

```bash
pytest -q
```

## Deploy to Vercel

1. Import this repository in Vercel. The FastAPI preset is detected from `pyproject.toml`.
2. **Storage → Create → Blob** (private) and connect it to the project. This sets `BLOB_READ_WRITE_TOKEN`.
3. Add environment variables: `GOOGLE_API_KEY`, `RUN_SECRET` (any long random string), and optionally `DAILY_RUN_LIMIT`.
4. Deploy. The queue consumer is declared in `pyproject.toml` (`[[tool.vercel.subscribers]]`).

> **Gemini free tier:** about 20 requests per model per day. A run makes 7-11 requests, so the
> shared key allows only a few runs a day (`DAILY_RUN_LIMIT`). Visitors can add their own free key.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `GOOGLE_API_KEY` | | Shared Gemini key for demo runs |
| `RUN_SECRET` | | Encrypts visitors' own keys in the queue (required on Vercel for that option) |
| `BLOB_READ_WRITE_TOKEN` | | Set by Vercel when a Blob store is connected |
| `DAILY_RUN_LIMIT` | `3` | Runs per day on the shared key |
| `GEMINI_MODEL` / `GEMINI_FALLBACK_MODEL` | `gemini-3.8-flash` / `gemini-3.5-flash` | Main model, plus a backup used when it is overloaded |
| `GEMINI_EMBEDDING_MODEL` | `models/gemini-embedding-001` | Embeddings for retrieval |
| `APPROVAL_SCORE` / `MAX_REVISIONS` | `7` / `2` | Critic threshold and revision budget |
| `KAGGLE_API_TOKEN` | | Enables Kaggle search (Hugging Face works without a key) |

## Project layout

```
usecase_forge/
  agents.py      the five agents and their prompts
  graph.py       control flow: LangGraph runner + single-step runner
  state.py       pipeline state, JSON codec, injected dependencies
  schemas.py     Pydantic models for every LLM output
  rag.py         chunking, vector index, source IDs
  runs.py        web run lifecycle: create, execute step, retries, public view
  store.py       snapshot storage (Vercel Blob / in-memory)
  keyvault.py    encryption for bring-your-own keys
  web.py         FastAPI app
  worker.py      Vercel Queues consumer
  demo.py        offline demo agents
  tools/         page fetching, dataset search
public/          front end (vanilla JS modules, no build step)
tests/           42 offline tests: agents, RAG, run lifecycle, API
legacy/          the original 3-script prototype
```

## Roadmap

- Web-search tool so the researcher can read news and industry reports
- Evaluation set of ~10 companies tracking critic score and citation rate per version
- Streaming LLM tokens to the UI; LangSmith tracing
