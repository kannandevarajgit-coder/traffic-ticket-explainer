---
title: Traffic Ticket Explainer
emoji: 🚦
colorFrom: blue
colorTo: green
sdk: docker
app_port: 8501
pinned: false
short_description: Explains traffic tickets in plain English with cited sources
---

# Traffic Ticket Explainer

An AI agent app that explains traffic tickets in plain English. Pick where you got the ticket
(California, New Jersey, New York State, New York City or Vermont), optionally upload the ticket
(PDF, photo, text, CSV or Excel), and ask questions such as "What does VC 22350 mean?" or
"How many points is this and what are my options?". Answers come only from the loaded law documents,
cite their sources, and are fact-checked by a validator agent before you see them.

Built for the Generative AI and ML capstone: LLM (Claude via the Anthropic API) + RAG (Chroma vector
database with local embeddings) + agents (LangGraph: planner, retriever, reasoner, validator).

> General information, not legal advice.

Full documentation (setup, architecture, agent roles, deployment, limitations, challenges):
[docs/DOCUMENTATION.md](docs/DOCUMENTATION.md)

## Run it in VS Code (about 10 minutes)

1. **Install** Python 3.11+ and VS Code with the Python extension.
2. **Open the folder**: unzip the project, then in VS Code choose *File > Open Folder* and pick
   `traffic-ticket-explainer`.
3. **Create the environment**: open the terminal (*Terminal > New Terminal*) and run

   ```bash
   python -m venv .venv
   # Windows
   .venv\Scripts\activate
   # Mac / Linux
   source .venv/bin/activate
   pip install -r requirements-dev.txt
   ```

   If VS Code asks "select interpreter", pick the one in `.venv`.
4. **Add your API key**: create a key at https://platform.claude.com (API usage is billed separately from
   a Claude.ai plan; a few dollars of credit is plenty). Copy `.env.example` to `.env` and paste the key:

   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```

   Never commit or share `.env`.
5. **Run**: press F5 and choose *Run Traffic Ticket Explainer*, or in the terminal run
   `streamlit run app.py`. Your browser opens at http://localhost:8501.
   The first run downloads the 80 MB embedding model once.
6. **Try it**: pick *Sample State*, upload `sample_docs/sample_ticket.pdf`, and click
   "What does my ticket mean and what are my options?".
7. **Tests**: `pytest -q` (25 tests, no API key needed; they use a fake Claude client).

## Add the official law documents

The build environment could not download government files, so add these yourself. Download each PDF and
put it in the matching folder (or use *Law library (admin)* in the app's sidebar). The full list with links
is in [laws/SOURCES.md](laws/SOURCES.md).

| Folder | Download |
| --- | --- |
| `laws/CA` | California Driver's Handbook; your county's Uniform Bail and Penalty Schedule |
| `laws/NY` | NY Driver's Manual (MV-21) |
| `laws/NJ` | NJ Driver Manual |
| `laws/NYC` | NYC parking ticket brochure; optionally the DOF parking violation codes CSV |
| `laws/VT` | Vermont Driver's Manual (VN-007) |

The `_UNOFFICIAL_summary.txt` files are restated summaries of the official points pages, included so the
app works before you add the PDFs. New files are indexed the next time someone selects that state
(or delete the `data/` folder to rebuild everything).

## Project layout

```
app.py                 Streamlit UI (state dropdown, ticket upload, chat, sources, agent trace)
docqa/config.py        Settings from environment variables
docqa/ingest.py        PDF / TXT / CSV / Excel / image loaders and upload validation
docqa/chunking.py      Recursive text splitter with overlap, citation labels
docqa/store.py         Chroma vector store with local all-MiniLM-L6-v2 embeddings
docqa/library.py       Jurisdictions, per-state law library, private per-session uploads
docqa/llm.py           Claude client: structured output, tool calls, refusals, API errors
docqa/prompts.py       Prompts for each agent
docqa/agents.py        LangGraph workflow: guard > planner > retriever > reasoner > validator > finalize
docqa/guardrails.py    Input checks, prompt-injection filter, citation checks, disclaimer
laws/<STATE>/          Law documents per jurisdiction
sample_docs/           A fictional ticket for testing
tests/                 Pytest suite with a fake Claude client
```
