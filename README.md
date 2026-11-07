# ContractIQ

Multi-agent contract intelligence, analysis, and verification platform powered by Band and Hindsight long-term memory.

## Quick Start

```bash
# 1. Install dependencies (requires uv)
uv pip install -e ".[dev]"

# 2. (Optional) Configure Hindsight Cloud
cp .env.example .env
# Edit .env and add your HINDSIGHT_API_KEY

# 3. Run the Streamlit app
streamlit run app.py
```

The app will open at **http://localhost:8501**.

## Features

- **PDF Upload** — Drop any contract PDF for instant analysis
- **Entity Extraction** — Parties, dates, governing law, jurisdiction
- **Commercial Terms** — Payment schedules, fees, late penalties, billing
- **Obligations** — Duties, deliverables, SLAs with responsible parties
- **Risk Analysis** — Liability caps, indemnification, termination risks with severity scoring
- **Source Evidence** — Every finding includes verbatim quotes, page numbers, section references, and confidence scores
- **Verification** — Automated buffer-match verification of extracted citations
- **Hindsight Memory** — Persistent contract memory with cross-contract comparison (local fallback when cloud is unconfigured)

## Architecture

```
PDF Upload
    │
    ▼
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│  ingestion/  │────▶│   analysis/      │────▶│   pipeline.py    │
│  parser.py   │     │   extractor.py   │     │   (orchestrator) │
│  hasher.py   │     │   risk_engine.py │     │                  │
│  models.py   │     │   models.py      │     └────────┬─────────┘
└──────────────┘     └──────────────────┘              │
                                                       ▼
                     ┌──────────────────┐     ┌──────────────────┐
                     │   schemas/       │     │   memory/        │
                     │   contract_*     │     │   hindsight_*    │
                     │   memory_*       │     │   memory_manager │
                     │   verification_* │     └──────────────────┘
                     └──────────────────┘              │
                                                       ▼
                                              ┌──────────────────┐
                                              │   app.py         │
                                              │   (Streamlit UI) │
                                              └──────────────────┘
```

## Running Tests

```bash
python -m pytest tests/ -v
```

## Project Structure

| Directory    | Purpose                                          |
|-------------|--------------------------------------------------|
| `schemas/`  | Pydantic models and JSON schemas                 |
| `ingestion/`| PDF/text parsing, hashing, buffer indexing        |
| `analysis/` | Contract extraction and risk scoring engine       |
| `memory/`   | Hindsight Cloud client and memory manager         |
| `tests/`    | Unit and integration tests                        |
| `samples/`  | Sample contract PDFs for demo                     |
| `pipeline.py` | End-to-end orchestration                       |
| `app.py`    | Streamlit web dashboard                           |
