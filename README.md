# Company AI Assistant

A multi-tenant AI assistant platform for companies. Upload your docs, ask
questions, and let an agent crew generate blogs, social posts, and emails
grounded in your company's voice and knowledge.

## What it does

- **Company Brain (RAG)** — upload PDFs/DOCXs/MDs, get a private FAISS
  vector index per tenant.
- **Multi-Agent Pipeline** — Strategist → Researcher → Writer → Reviewer →
  Communicator, orchestrated by LangGraph with conditional revision loops.
- **Smart LLM Routing** — fast generation goes to Groq, sensitive review
  goes to local Ollama. Fallback + circuit breaker on both sides.
- **Email with human approval** — every AI-drafted email goes through a
  pending → approved → sent gate. Nothing leaves your account without a
  human click.

## Stack

| Layer | Tech |
|---|---|
| Backend | FastAPI, async SQLAlchemy, asyncpg |
| Agents | LangGraph |
| LLMs | Groq (cloud) + Ollama (local) |
| Vector DB | FAISS (per-company namespace) |
| Embeddings | sentence-transformers (local, free) |
| Frontend | Streamlit |
| DB | PostgreSQL (RDS in prod) |
| Cloud | AWS (EC2, S3, SES) |

## Quick start (local, with Docker)

```bash
# Prereqs: Docker Desktop, a Groq API key
git clone https://github.com/yourname/company-ai-assistant.git
cd company-ai-assistant

cp backend/.env.example backend/.env
# Edit backend/.env — at minimum set GROQ_API_KEY
# (DATABASE_URL and OLLAMA_BASE_URL are overridden by docker-compose; ignore.)

make dev
```

Then open:
- **App**: http://localhost:8501
- **API docs**: http://localhost:8000/docs

First run downloads ~5GB for the Ollama model — be patient. Afterwards it's instant.

## Quick start (local, without Docker)

You'll need: Python 3.11, PostgreSQL running, Ollama running with `llama3.1:8b` pulled.

```bash
# Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in DATABASE_URL + GROQ_API_KEY
uvicorn app.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Deploy to AWS

See **[`docs/aws_setup.md`](docs/aws_setup.md)** for the full step-by-step.
Short version:

```bash
cd infra/aws
./setup_s3.sh                          # bucket
KEY_NAME=mykey ./setup_ec2.sh          # instance + IAM role
APP_SG_ID=sg-xxx ./setup_rds.sh        # RDS in private subnet
SENDER=noreply@yours.com ./setup_ses.sh

# Then on the EC2 box:
git clone <repo> && cd company-ai-assistant
cp backend/.env.example backend/.env.production
# Fill in DATABASE_URL (RDS), GROQ_API_KEY, S3_BUCKET_DOCS, SES_SENDER_EMAIL
make prod-up
make migrate-prod
```

## Project structure

```
.
├── backend/              FastAPI + agents + RAG + LLM router
│   ├── app/              All Python code
│   │   ├── routes/       HTTP layer (thin)
│   │   ├── services/     Business logic
│   │   ├── agents/       LangGraph nodes + graph
│   │   ├── llm_router/   Groq + Ollama with retry/fallback
│   │   ├── rag/          Chunker + embedder + FAISS
│   │   ├── db/           ORM tables + async session
│   │   ├── models/       Pydantic request/response
│   │   └── utils/        Security (JWT, bcrypt) + exceptions
│   ├── migrations/       Alembic
│   ├── Dockerfile
│   └── requirements.txt
│
├── frontend/             Streamlit MVP
│   ├── streamlit_app.py
│   ├── components/       Auth, API client, UI helpers
│   ├── pages/            Multi-page nav
│   └── Dockerfile
│
├── infra/
│   ├── aws/              Bootstrap scripts (S3, RDS, SES, EC2) + IAM
│   ├── nginx/            Reverse proxy + TLS config
│   ├── systemd/          Service files (alternative to Docker on EC2)
│   ├── docker-compose.yml          Local dev
│   └── docker-compose.prod.yml     Production overlay
│
├── docs/
│   └── aws_setup.md      Deployment guide
│
├── Makefile              `make help`
└── README.md
```

## Common tasks

```bash
make dev              # start everything locally
make logs             # tail container logs
make db-shell         # psql into the dev DB
make backend-shell    # bash into the backend container
make migrate          # apply migrations to dev DB
make migrate-create m="add user role"
make test             # run pytest
make clean            # tear down + wipe volumes
```

## Architecture decisions worth knowing

1. **Per-company FAISS folders**, not metadata-filtered global index. Faster, simpler offboarding (`rm -rf data/faiss/{id}`), trade-off is more inodes.
2. **Async everywhere**. SQLAlchemy + asyncpg, agent calls, LLM router. CPU work (FAISS, embeddings) goes through `asyncio.to_thread` to keep the event loop responsive.
3. **Stateless agents**. Each LangGraph node returns a partial state update; nothing held in memory between calls. Easy to reason about, easy to scale horizontally.
4. **Human approval gate is data-layer enforced**. Email rows transition `pending_approval → approved → sent`. The SES call only happens inside the approve handler — no other path can trigger it.
5. **Groq for fast & reasoning, Ollama for sensitive**. The router picks based on `TaskType` declared by each agent. Never silently fails — typed `AllProvidersFailedError` if every fallback's down.
6. **IAM Instance Profile in prod, no AWS keys in env**. The S3 service handles both modes transparently.

## License

MIT.