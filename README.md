# Ticket Triage System - Agent in Action

A multi-agent ticket triage system built with LangGraph that implements a **three-entity workflow** (Customer → Assistant → Admin) for processing customer support tickets.

## 🎯 Project Overview

This project implements an intelligent customer support ticket triage system using LangGraph for workflow orchestration. The system features a multi-agent architecture with three distinct entities:

| Entity | Role | Endpoint |
|--------|------|----------|
| **Customer** | Submits support tickets | `POST /triage/invoke` |
| **Assistant** | Processes ticket, classifies issue, fetches order, drafts reply | Automated |
| **Admin** | Reviews and approves/rejects assistant's recommendation | `POST /triage/review` |

## ✨ Features

- **Three-Entity Workflow**: Customer → Assistant → Admin approval flow
- **LangGraph State Machine**: Multi-node graph-based ticket triage
- **ToolNode Integration**: Uses LangGraph's `ToolNode` for order fetching
- **Issue Classification**: Automatic classification based on keywords
- **Order Management**: Order lookup and data retrieval via tools
- **Reply Generation**: Automated reply drafting with templates
- **Admin Review**: Human-in-the-loop approval/rejection
- **Langfuse Tracing**: Optional observability and tracing integration

### Phase 2 Features

- **PostgreSQL persistence**: LangGraph state is checkpointed with `PostgresSaver`; workflow can be interrupted and resumed across restarts. Pending tickets are stored in a `pending_tickets` table in the same database.
- **Durable state**: Each run uses a `thread_id` (derived from ticket submission). State is read from and written to Postgres at each step, enabling interrupt and resume.
- **Human approval gate for refunds**: After the assistant drafts a reply, the graph runs a **refund preview** node and then calls LangGraph’s `interrupt()`. Execution pauses until an admin approves or rejects via `POST /triage/review`. On resume, the graph continues to policy evaluation and, if approved, commits the refund.
- **Policy-grounded RAG with citations**: A `policy_evaluator` node builds a query from the ticket and proposed action, calls a knowledge-base orchestrator that embeds the query (OpenAI) and runs a pgvector similarity search over `kb.policies`. Retrieved snippets are attached to state as `policy_citations` and returned in API responses for transparency.
- **Langfuse observability**: When configured, Langfuse records run trees, and node metadata (e.g. `retrieved_document_ids`, `citation_spans`) for policy retrieval and reply drafting, so you can inspect retrieval and citations in the Langfuse UI.

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+** (3.9, 3.10, 3.11, 3.12, or 3.13)
- **PostgreSQL 16** with **pgvector** (e.g. `pgvector/pgvector:pg16` Docker image)
- **OpenAI API key** (for policy RAG embeddings and optional LLM use)
- **Langfuse** (optional): for observability; requires `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY`

### Setup

1. **Clone the repository**

   ```bash
   git clone https://github.com/Shrushti1999/Ticket-triage-system
   cd Ticket-triage-system
   ```

2. **Install dependencies**

   ```bash
   pip install -r requirements.txt
   ```

   For Phase 2 policy RAG and Postgres persistence you also need:

   ```bash
   pip install psycopg[binary] pgvector openai
   ```

   (These may already be satisfied by `langgraph-checkpoint-postgres` and project usage.)

3. **Start PostgreSQL with pgvector**

   Using Docker Compose (recommended):

   ```bash
   docker-compose up -d
   ```

   This starts Postgres (user `app`, password `app`, database `practice`) on port 5432 with pgvector enabled.

4. **Configure environment**

   Copy the example env and set at least `POSTGRES_DSN` and `OPENAI_API_KEY`:

   ```bash
   cp .env.example .env
   ```

   Edit `.env`:

   - `POSTGRES_DSN=postgresql://app:app@localhost:5432/practice` (match Docker Compose)
   - `OPENAI_API_KEY=your-openai-api-key`
   - Optionally set Langfuse variables for observability (see [Configuration](#-configuration)).

5. **Index policy documents (Phase 2 RAG)**

   From the project root, run the KB index script so that policy-grounded retrieval works:

   ```bash
   python Phase2/scripts/kb_index.py --policies-dir Phase2/mock_data/policies
   ```

   Use `--recreate` to drop and recreate the `kb.policies` table. Use `--dsn` if your Postgres DSN differs.

6. **Run the server**

   ```bash
   uvicorn app.main:app --reload
   # or: python -m uvicorn app.main:app --reload
   ```

   The API will be available at `http://localhost:8000`. The app will fail to start if `POSTGRES_DSN` is not set, because the checkpointer and pending-ticket store require Postgres.

## 📖 Three-Entity Workflow

### Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                           THREE-ENTITY WORKFLOW                              │
├──────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  CUSTOMER                    ASSISTANT                      ADMIN            │
│  ────────                    ─────────                      ─────            │
│                                                                              │
│  POST /triage/invoke                                                         │
│       │                                                                      │
│       ▼                                                                      │
│  ┌─────────┐    ┌────────────────┐    ┌─────────────┐    ┌─────────────┐     │
│  │ ingest  │──▶│ classify_issue  │──▶│ fetch_order │──▶│ draft_reply │     │
│  └─────────┘    └────────────────┘    │  (ToolNode) │    └─────────────┘     │
│                                       └─────────────┘           │            │
│                                                                 ▼            │
│                                                    status: "awaiting_admin"  │
│                                                                 │            │
│                                                                 ▼            │
│                                                    POST /triage/review       │
│                                                                 │            │
│                                                    ┌────────────┴───────┐    │
│                                                    ▼                    ▼    │
│                                               "approve"            "reject"  │
│                                                    │                    │    │
│                                                    ▼                    ▼    │
│                                               COMPLETED            COMPLETED │
│                                                                              │
└──────────────────────────────────────────────────────────────────────────────┘
```

### Step-by-Step

1. **Customer** submits a ticket via `POST /triage/invoke`
2. **Assistant** automatically:
   - Ingests and extracts order ID from text
   - Classifies the issue type
   - Fetches order details using ToolNode
   - Drafts a reply recommendation
3. **Admin** reviews via `POST /triage/review`:
   - Views pending tickets at `GET /triage/pending`
   - Approves or rejects with feedback

## 🧪 Example Usage

### Step 1: Customer Submits Ticket

```bash
curl -X POST http://localhost:8000/triage/invoke \ `
  -H "Content-Type: application/json" \ `
  -d '{"ticket_text": "I need a refund for order ORD1001", "order_id": null}'
```
OR
```bash
Invoke-RestMethod `
  -Method POST `
  -Uri "http://localhost:8000/triage/invoke" `
  -Headers @{ "Content-Type" = "application/json" } `
  -Body (@{ ticket_text = "I need a refund for order ORD1001" } | ConvertTo-Json)
```

**Response:**
```json
{
  "ticket_id": "abc12345",
  "order_id": "ORD1001",
  "issue_type": "refund_request",
  "recommendation": "Hi Ava Chen, we are sorry for the inconvenience...",
  "status": "awaiting_admin",
  "order": {
    "order_id": "ORD1001",
    "customer_name": "Ava Chen",
    "email": "ava.chen@example.com"
  },
  "message": "Ticket processed by assistant. Awaiting admin review at POST /triage/review"
}
```

### Step 2: Admin Reviews Pending Tickets

```bash
curl.exe http://localhost:8000/triage/pending
```

**Response:**
```json
{
  "pending_tickets": [
    {
      "ticket_id": "abc12345",
      "order_id": "ORD1001",
      "issue_type": "refund_request",
      "recommendation": "Hi Ava Chen, we are sorry...",
      "status": "awaiting_admin"
    }
  ],
  "count": 1
}
```

### Step 3: Admin Approves/Rejects

**Approve:**
```bash
curl -X POST http://localhost:8000/triage/review \ `
  -H "Content-Type: application/json" \ `
  -d '{"ticket_id": "abc12345", "decision": "approve", "feedback": "Looks good"}'
```
OR
```bash
Invoke-RestMethod `
  -Method POST `
  -Uri "http://localhost:8000/triage/review" `
  -Headers @{ "Content-Type" = "application/json" } `
  -Body (@{
    ticket_id = "abc12345"
    decision  = "approve"
    feedback  = "Looks good"
  } | ConvertTo-Json)
```
**Response (Approve):**
```json
{
  "ticket_id": "abc12345",
  "order_id": "ORD1001",
  "issue_type": "refund_request",
  "recommendation": "Hi Ava Chen, we are sorry for the inconvenience...",
  "status": "completed",
  "order": {
    "order_id": "ORD1001",
    "customer_name": "Ava Chen",
    "email": "ava.chen@example.com"
  },
  "message": "Ticket approved by admin. Feedback: Looks good"
}
```
**Reject:**
```bash
curl -X POST http://localhost:8000/triage/review \ `
  -H "Content-Type: application/json" \ `
  -d '{"ticket_id": "abc12345", "decision": "reject", "feedback": "Offer discount"}'
```
OR
```bash
Invoke-RestMethod `
  -Method POST `
  -Uri "http://localhost:8000/triage/review" `
  -Headers @{ "Content-Type" = "application/json" } `
  -Body (@{
    ticket_id = "abc12345"
    decision  = "reject"
    feedback  = "Offer discount"
  } | ConvertTo-Json)
```
**Response (Reject):**
```json
{
  "ticket_id": "abc12345",
  "order_id": "ORD1001",
  "issue_type": "refund_request",
  "recommendation": "Hi Ava Chen, we are sorry for the inconvenience...",
  "status": "completed",
  "order": {
    "order_id": "ORD1001",
    "customer_name": "Ava Chen",
    "email": "ava.chen@example.com"
  },
  "message": "Ticket rejected by admin. Feedback: Offer discount"
}
```

### Step 4: Customer submits ticket without order_id

```bash
curl -X POST http://localhost:8000/triage/invoke \ `
  -H "Content-Type: application/json" \ `
  -d "{\"ticket_text\": \"My package arrived damaged\"}"
```
OR
```bash
Invoke-RestMethod `
  -Method POST `
  -Uri "http://localhost:8000/triage/invoke" `
  -Headers @{ "Content-Type" = "application/json" } `
  -Body (@{ ticket_text = "My package arrived damaged" } | ConvertTo-Json)
```

**Response:**
```json
{
  "ticket_id": "abc12345",
  "order_id": ,
  "issue_type": "damaged_item",
  "recommendation": "Could you please provide your order ID so I can assist you further?",
  "status": "awaiting_admin",
  "order": ,
  "message": "Ticket processed by assistant. Awaiting admin review at POST /triage/review"
}
```

### Demo: Interrupt and Resume (Phase 2)

Phase 2 adds a **human approval gate**: after the assistant drafts a reply, the graph runs a refund preview and then **interrupts**. The API returns with `status: "awaiting_approval"`. The admin approves or rejects via `POST /triage/review`; the server **resumes** the same graph with that decision, then runs policy RAG and (if approved) commits the refund.

1. **Customer submits a refund-style ticket**

   ```bash
   curl -X POST http://localhost:8000/triage/invoke \
     -H "Content-Type: application/json" \
     -d '{"ticket_text": "I need a refund for order ORD1001", "order_id": null}'
   ```

2. **Response (workflow interrupted at approval gate)**

   ```json
   {
     "ticket_id": "a1b2c3d4",
     "order_id": "ORD1001",
     "issue_type": "refund_request",
     "recommendation": "Hi Ava Chen, we are sorry for the inconvenience...",
     "status": "awaiting_approval",
     "order": { "order_id": "ORD1001", "customer_name": "Ava Chen", ... },
     "message": "Ticket processed by assistant. Awaiting admin review at POST /triage/review",
     "policy_citations": null
   }
   ```

   The graph has paused after computing a refund preview; state is stored in Postgres under `thread_id` = `ticket_id`.

3. **Admin lists pending tickets**

   ```bash
   curl http://localhost:8000/triage/pending
   ```

   The ticket appears with `status: "awaiting_approval"`.

4. **Admin approves (resume)**

   ```bash
   curl -X POST http://localhost:8000/triage/review \
     -H "Content-Type: application/json" \
     -d '{"ticket_id": "a1b2c3d4", "decision": "approve", "feedback": "Looks good"}'
   ```

   The server loads the checkpoint for `a1b2c3d4`, injects `admin_decision` and `admin_feedback`, and resumes the graph with `Command(resume="approve")`. The graph continues: **policy_evaluator** (RAG over `kb.policies`, fills `policy_citations`), then **commit_refund** (calls `refund_commit`), then ends.

5. **Response (after resume)**

   ```json
   {
     "ticket_id": "a1b2c3d4",
     "order_id": "ORD1001",
     "issue_type": "refund_request",
     "recommendation": "Hi Ava Chen, we are sorry for the inconvenience...",
     "status": "completed",
     "order": { ... },
     "message": "Ticket approved by admin. Feedback: Looks good",
     "policy_citations": [
       { "file": "refund_policy.md", "doc_id": "refund_policy.md#chunk-1", "snippet": "..." }
     ]
   }
   ```

   If the admin had sent `"decision": "reject"`, the graph would still resume and run policy_evaluator and commit_refund, but `refund_commit` would not be called (only on approve).

## 📡 API Endpoints

### Customer Endpoint

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/triage/invoke` | Submit a support ticket for triage |

### Admin Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/triage/pending` | List all tickets awaiting admin review |
| `POST` | `/triage/review` | Approve or reject a recommendation |

### Utility Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check |
| `GET` | `/orders/get?order_id=ORD1234` | Get order by ID |
| `GET` | `/orders/search?customer_email=...` | Search orders |
| `POST` | `/classify/issue` | Classify issue type |
| `POST` | `/reply/draft` | Draft a reply |

### API Changes (Phase 2)

- **`POST /triage/invoke`**
  - Response may include **`policy_citations`**: list of `{ "file", "doc_id", "snippet" }` from the policy RAG. Returned when the run has passed through the policy evaluator (e.g. after resume).
  - **`status`** may be **`awaiting_approval`** instead of `awaiting_admin`: the workflow has paused at the human approval gate (refund preview). Admin must call `POST /triage/review` with the same `ticket_id` to resume; the graph then continues to policy evaluation and refund commit (if approved).

- **`POST /triage/review`**
  - For tickets in **`awaiting_approval`**, the server **resumes** the interrupted triage graph with `Command(resume=decision)` instead of invoking the separate admin-review graph. The same request body (`ticket_id`, `decision`, `feedback`) is used; `decision` is `"approve"` or `"reject"`.
  - Response may include **`policy_citations`** after resume (from the policy_evaluator node run during resume).

- **State persistence**
  - Ticket state is stored in Postgres (LangGraph checkpointer) keyed by `thread_id` (= `ticket_id`). Pending tickets are also stored in the `pending_tickets` table. Listing and reviewing use this durable state so interrupt/resume and server restarts are supported.

## 🏗️ Architecture

### Phase 2 Flow (Mermaid)

The following diagram shows the Phase 2 workflow including the human approval gate, policy RAG, and durable state. Execution pauses at **propose_remedy** until the admin reviews; on resume the graph continues to **policy_evaluator** and **commit_refund**.

```mermaid
flowchart TB
    subgraph customer["Customer"]
        A[POST /triage/invoke]
    end

    subgraph assistant["Assistant"]
        B[ingest]
        C[classify_issue]
        D{order_id?}
        E[prepare_tool_call]
        F[fetch_order]
        G[process_tool_result]
        H[draft_reply]
        I[propose_remedy]
        K[policy_evaluator]
        L[commit_refund]
    end

    subgraph persistence["Persistence"]
        P[(Postgres: checkpoints + pending_tickets)]
    end

    subgraph admin["Admin"]
        J[POST /triage/review approve/reject]
    end

    A --> B
    B --> C
    C --> D
    D -->|yes| E
    D -->|no| H
    E --> F
    F --> G
    G --> H
    H --> I
    I -->|interrupt| J
    J -->|resume| K
    K --> L
    L --> M([END])
    I -.->|checkpoint| P
    J -.->|load state| P
```

- **Solid edges**: automatic flow.
- **interrupt**: at `propose_remedy` the graph calls `interrupt()` and returns; state is checkpointed in Postgres.
- **resume**: admin calls `POST /triage/review` with `ticket_id` and `decision`; server loads state and runs `graph.invoke(Command(resume=decision))`, so execution continues from the node after the interrupt.
- **policy_evaluator**: builds a query, runs RAG over `kb.policies` (pgvector), and attaches `policy_citations` to state; citations are returned in the API response.

### State Schema

```python
class GraphState(TypedDict):
    messages: List[BaseMessage]      # Conversation history
    ticket_text: str                 # Original ticket text
    order_id: Optional[str]          # Extracted order ID
    issue_type: Optional[str]        # Classified issue type
    evidence: Optional[Dict]         # Order data, confidence, policy_citations, policy_justification
    recommendation: Optional[str]    # Generated reply
    status: Optional[str]            # pending | awaiting_admin | awaiting_approval | completed
    admin_decision: Optional[str]    # approve/reject
    admin_feedback: Optional[str]    # Admin comments
    refund_preview: Optional[Dict]    # Refund preview from propose_remedy (Phase 2)
```

### Workflow Nodes

| Node | Entity | Description |
|------|--------|-------------|
| `ingest` | Customer Entry | Extracts ticket text and order ID |
| `classify_issue` | Assistant | Classifies issue based on keywords |
| `prepare_tool_call` | Assistant | Creates AIMessage with tool call |
| `fetch_order` | Assistant (ToolNode) | Executes order fetch tool |
| `process_tool_result` | Assistant | Extracts order data from tool result |
| `draft_reply` | Assistant | Generates reply recommendation |
| `propose_remedy` | Assistant | Computes refund preview, then **interrupts** for admin approval |
| `policy_evaluator` | Assistant | RAG over `kb.policies`; attaches `policy_citations` to evidence |
| `commit_refund` | Assistant/Admin | On resume, if approved, commits refund; sets status to completed |
| `admin_review` | Admin | Processes admin decision (used in separate admin-review graph for non-refund flow) |
| `finalize` | System | Marks workflow complete |

### Supported Issue Types

- `refund_request`
- `late_delivery`
- `damaged_item`
- `missing_item`
- `duplicate_charge`
- `wrong_item`
- `defective_product`
- `unknown`

## ⚙️ Configuration

### Required (Phase 2)

- **POSTGRES_DSN**: Postgres connection string for checkpointer and pending_tickets (e.g. `postgresql://app:app@localhost:5432/practice`). Must be set or the app will not start.
- **OPENAI_API_KEY**: Used by the policy RAG (kb_orchestrator) for embedding queries. Set in `.env` or environment.

Optional: **KB_PG_DSN** — if set, the KB index and RAG use this DSN instead of `POSTGRES_DSN` (e.g. a separate DB for policies).

### Langfuse Tracing (Optional)

Enable observability by setting environment variables (see `.env.example`):

```bash
export LANGFUSE_PUBLIC_KEY="pk-..."
export LANGFUSE_SECRET_KEY="sk-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"
export LANGFUSE_PROJECT_NAME="p1-seafoam-cicada"
export LANGFUSE_ENVIRONMENT="development"
```

The application runs normally without Langfuse; run trees and node metadata (e.g. citation spans) appear in the Langfuse UI when configured.

## 🧪 Testing

### Run All Tests

```bash
pytest tests/ -v
```

### Run Workflow Test Script

```bash
chmod +x test_workflow.sh
./test_workflow.sh
```

### Test Coverage

- ✅ Complete three-entity workflow
- ✅ Issue classification for all types
- ✅ Order fetching via ToolNode
- ✅ Reply generation with templates
- ✅ Admin approve/reject flows
- ✅ Error handling scenarios

## 📁 Project Structure

```
Ticket-triage-system/
├── .github/
│   └── workflows/
│       └── tests.yml           # GitHub Actions CI
├── .env.example                # Example env (POSTGRES_DSN, OPENAI_API_KEY, Langfuse)
├── .pytest_cache/              # Pytest cache (auto-generated)
├── app/
│   ├── __init__.py
│   ├── main.py                 # FastAPI app; triage/review endpoints; Langfuse; lifespan with Postgres
│   ├── graph.py                # LangGraph triage + admin-review graphs; interrupt at propose_remedy
│   ├── state.py                # GraphState schema (includes refund_preview, evidence.policy_citations)
│   ├── tools.py                # LangChain tools (fetch_order)
│   ├── persistence.py          # PostgresPendingTicketStore, InMemoryPendingTicketStore, PendingTicket
│   ├── policy_evaluator.py     # Policy RAG node; kb_orchestrator; citations into evidence
│   ├── kb_orchestrator.py      # Query embedding + pgvector search over kb.policies
│   └── payment.py              # refund_preview, refund_commit (mock)
├── Phase2/
│   ├── scripts/
│   │   └── kb_index.py         # CLI to index policy .md files into kb.policies (pgvector)
│   ├── mock_data/
│   │   ├── orders.json
│   │   ├── issues.json
│   │   ├── replies.json
│   │   └── policies/           # Policy markdown files for RAG
│   │       ├── refund_policy.md
│   │       ├── cancellation_policy.md
│   │       ├── delivery_policy.md
│   │       ├── warranty_policy.md
│   │       ├── chargeback_policy.md
│   │       ├── fraud_policy.md
│   │       ├── pricing_discounts_policy.md
│   │       └── support_sla_policy.md
│   └── interactions/
│       └── phase2_demo.json    # Phase 2 demo scenarios (interrupt/resume, citations)
├── interactions/
│   └── phase1_demo.json        # Phase 1 example payloads
├── mock_data/
│   ├── orders.json             # Sample order data
│   ├── issues.json             # Issue classification rules
│   └── replies.json            # Reply templates
├── tests/
│   ├── test_graph.py           # Graph workflow tests
│   └── test_persistence.py     # Persistence store tests
├── docker-compose.yml          # Postgres + pgvector (pg16)
├── test_workflow.sh             # End-to-end test script
├── test_all.sh                 # Convenience test runner
├── requirements.txt            # Python dependencies (langgraph-checkpoint-postgres, etc.)
└── README.md                   # This file
```
## 📷 Loom Video
https://www.loom.com/share/8fb6eb26d4b34036bf74987c9ab6a274

## 🛠️ Built With

- **[LangGraph](https://github.com/langchain-ai/langgraph)** - Workflow orchestration
- **[LangChain](https://github.com/langchain-ai/langchain)** - LLM framework & tools
- **[FastAPI](https://fastapi.tiangolo.com/)** - Web framework
- **[Langfuse](https://langfuse.com/)** - Observability (optional)

## 📝 How I Used Cursor

This project was developed with the assistance of **Cursor AI**, which helped with:
I started by independently reading the assignment and writing a brief plan and README outline without using any AI tools, focusing on the LangGraph state design, node responsibilities, and control flow. Once the architecture was clear, I broke the work into small, explicit implementation steps and used Cursor as a coding copilot to accelerate writing boilerplate and wiring modules together. After each step, I manually reviewed the generated code, ran tests, and validated behavior against the assignment requirements. I used AI tools selectively for iteration and verification, but all design decisions, graph structure, and edge-case handling were driven by my own reasoning. I finalized the project by adding CI with GitHub Actions, refining the README, and manually testing the API end-to-end using curl and Postman.

---
