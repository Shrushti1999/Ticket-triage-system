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

## 🧱 Phase 2 Features

- **Postgres persistence and durable state**: Uses LangGraph's `PostgresSaver` to checkpoint graph state in Postgres and a `pending_tickets` table (via `PostgresPendingTicketsStore`) so tickets survive restarts and can be safely resumed.
- **Human approval gate for refunds**: Refund tickets trigger a `refund_preview`, pause the graph with an interrupt, and enter an `awaiting_approval` state. The `/triage/review` endpoint then *resumes* the same graph thread to run the `commit_refund` path only after an explicit admin decision.
- **Policy-grounded RAG with citations**: Refund flows query a pgvector-backed `policy_chunks` table using `query_policies`, attach `policy_citations` into graph state, and propagate those citations into the `refund_preview` for auditability.
- **Langfuse observability (end-to-end)**: Both customer (`/triage/invoke`) and admin (`/triage/review`) flows can be wrapped with Langfuse callbacks, producing trace-per-ticket observability for the full interrupt-and-resume lifecycle.

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+** (3.9, 3.10, 3.11, or 3.12)

### Installation

```bash
# Clone the repository
git clone https://github.com/Shrushti1999/Ticket-triage-system
cd Ticket-triage-system

# Install dependencies
pip install -r requirements.txt
```

### Running the Server

```bash
# If uvicorn is in PATH
uvicorn app.main:app --reload

# Or using Python module
python -m uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

## ⚙️ Setup (Phase 2)

- **1. Start Postgres with pgvector**
  - Ensure Docker is running, then from the project root:
  ```bash
  docker-compose up -d
  ```
  - This starts `pgvector/pgvector:pg16` on `localhost:5432` and runs `init.sql` to:
    - Enable the `vector` extension.
    - Create the `pending_tickets` table used by the app.

- **2. Configure environment variables**
  - Core database and runtime config:
  ```bash
  # Optional: override if not using the default docker-compose settings
  export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/triage"

  # Use in-memory checkpointer + pending store (for tests/local dev without Postgres)
  export USE_MEMORY_SAVER=1  # omit to use PostgresSaver + PostgresPendingTicketsStore
  ```
  - Embeddings and policy RAG:
  ```bash
  export OPENAI_API_KEY="sk-..."             # required for policy embeddings
  export EMBEDDING_MODEL="text-embedding-3-small"  # optional override
  export EMBEDDING_DIM="1536"               # must match the embedding model
  ```
  - Optional Langfuse observability:
  ```bash
  export LANGFUSE_PUBLIC_KEY="pk-..."
  export LANGFUSE_SECRET_KEY="sk-..."
  export LANGFUSE_HOST="https://cloud.langfuse.com"
  export LANGFUSE_PROJECT_NAME="p1-seafoam-cicada"
  export LANGFUSE_ENVIRONMENT="development"
  ```

- **3. Index policy markdown files into pgvector**
  - After Postgres is up and `OPENAI_API_KEY` is set, run:
  ```bash
  python -m app.kb_index --kb-dir NewPhase/policies --reset
  ```
  - This:
    - Reads all `*.md` files under `NewPhase/policies`.
    - Splits them into small, deterministic sections.
    - Embeds each section and upserts into the `policy_chunks` table.

- **4. Run the FastAPI server**
  - With Postgres + policies indexed, start the app as shown in **Running the Server** above.

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

## 🔄 API Changes (Phase 2)

- **Durable triage threads**
  - `/triage/invoke` now:
    - Derives a deterministic `ticket_id` by hashing `ticket_text` + `order_id`.
    - Uses this `ticket_id` as the LangGraph `thread_id`, so the same ticket can be resumed later via the checkpoint store (Postgres or in-memory).
    - Writes a corresponding row into the `pending_tickets` store (Postgres or in-memory), making tickets visible to `/triage/pending`.

- **Refund-specific interrupt and resume**
  - When the graph classifies a ticket as `refund_request`, it:
    - Produces a `refund_preview` (from `app.payments.refund_preview`).
    - Attaches `policy_citations` from the RAG step.
    - Sets `status="awaiting_approval"` and **emits an interrupt**, pausing the triage graph before any refund is committed.
  - `/triage/pending` lists these tickets with `status: "awaiting_approval"`.
  - `/triage/review`:
    - For refund tickets in `awaiting_approval`, **resumes** the same triage graph thread with the admin's `decision` and `feedback` so the `commit_refund` path runs inside the graph.
    - For non-refund tickets (or already processed ones), falls back to the existing `admin_review` graph.

- **Policy-grounded state**
  - Refund flows now enrich graph state with:
    - `policy_citations`: a mapping keyed by policy file name (for example `refund_policy.md`) whose values are top-k pgvector matches (`section_id`, `content`, `score`).
    - `refund_preview.policy_citations`: the same citation payload, making it easy to surface in UIs or logs.

- **Observability hooks**
  - Both `/triage/invoke` and `/triage/review` optionally attach Langfuse callback handlers:
    - One trace per ticket (e.g., `triage_<ticket_id>`, `admin_review_<ticket_id>`).
    - Useful for visualizing the interrupt-and-resume control flow inside LangGraph.

## 🏗️ Architecture

### Phase 2 Architecture Diagram

```mermaid
flowchart TD
    subgraph Customer
        C["Customer (ticket_text, order_id)"]
    end

    subgraph API["FastAPI Layer"]
        INVOKE["POST /triage/invoke"]
        PENDING["GET /triage/pending"]
        REVIEW["POST /triage/review"]
        HEALTH["GET /health"]
    end

    subgraph LangGraph["LangGraph Workflows"]
        TG["triage_graph (ingest → classify_issue → fetch_order / refund_preview → policy RAG → draft_reply → wait_for_admin_approval)"]
        AG["admin_review_graph (admin_review → finalize)"]
    end

    subgraph DB["Postgres + pgvector"]
        CP["checkpoint tables / PostgresSaver"]
        PT["pending_tickets"]
        POL["policy_chunks / pgvector"]
    end

    subgraph RAG["Policy RAG"]
        KB_INDEX["app.kb_index (CLI indexer)"]
        VSTORE["app.policy_vector_store (query_policies)"]
    end

    subgraph Payments["Refund Flow"]
        PREVIEW["refund_preview"]
        COMMIT["refund_commit"]
    end

    subgraph Obs["Observability"]
        LF["Langfuse (traces, spans)"]
    end

    C --> INVOKE --> TG
    TG -->|non-refund| AG
    TG -->|"refund_request / status=awaiting_approval / INTERRUPT"| PT

    REVIEW -->|"refund_request / resume thread"| TG
    REVIEW -->|other issues| AG

    TG <-.-> CP
    AG <-.-> CP

    TG -->|policy query| VSTORE --> POL
    KB_INDEX --> POL

    TG --> PREVIEW
    TG -->|after approve| COMMIT

    INVOKE -.traced by.-> LF
    REVIEW -.traced by.-> LF
```

### State Schema

```python
class GraphState(TypedDict):
    messages: List[BaseMessage]      # Conversation history
    ticket_text: str                 # Original ticket text
    order_id: Optional[str]          # Extracted order ID
    issue_type: Optional[str]        # Classified issue type
    evidence: Optional[Dict]         # Order data, confidence scores
    recommendation: Optional[str]    # Generated reply
    status: Optional[str]            # Workflow status
    admin_decision: Optional[str]    # approve/reject
    admin_feedback: Optional[str]    # Admin comments
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
| `admin_review` | Admin | Processes admin decision |
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

## 🧪 Demo: Interrupt and Resume (Refund Approval)

- **1. Start infrastructure**
  - Run Postgres + pgvector:
  ```bash
  docker-compose up -d
  ```
  - Set `DATABASE_URL` and `OPENAI_API_KEY` (and Langfuse keys if desired).
  - Index policies:
  ```bash
  python -m app.kb_index --kb-dir NewPhase/policies --reset
  ```

- **2. Start the API server**
  ```bash
  uvicorn app.main:app --reload
  ```

- **3. Customer triggers a refund that pauses for approval**
  ```bash
  curl -X POST http://localhost:8000/triage/invoke ^
    -H "Content-Type: application/json" ^
    -d "{\"ticket_text\": \"I need a refund for order ORD1001\"}"
  ```
  - The response will include:
    - A deterministic `ticket_id`.
    - `issue_type: "refund_request"`.
    - `status: "awaiting_approval"`.
    - A `recommendation` derived from the refund policies.
    - (Internally) `refund_preview` and `policy_citations` stored in graph state.

- **4. Admin inspects pending tickets**
  ```bash
  curl http://localhost:8000/triage/pending
  ```
  - Shows tickets (including the one above) with `status: "awaiting_approval"` and the same `ticket_id`.

- **5. Admin approves (or rejects), resuming the graph**
  ```bash
  # Approve refund
  curl -X POST http://localhost:8000/triage/review ^
    -H "Content-Type: application/json" ^
    -d "{\"ticket_id\": \"<ticket_id-from-step-3>\", \"decision\": \"approve\", \"feedback\": \"Within policy\"}"

  # Or reject refund
  curl -X POST http://localhost:8000/triage/review ^
    -H "Content-Type: application/json" ^
    -d "{\"ticket_id\": \"<ticket_id-from-step-3>\", \"decision\": \"reject\", \"feedback\": \"Outside refund window\"}"
  ```
  - For refunds, this **resumes** the original triage graph thread:
    - `wait_for_admin_approval` node consumes the decision.
    - On approve, `commit_refund` runs and the ticket is finalized.
    - In all cases, `pending_tickets` is updated and `/triage/pending` no longer lists the ticket.

## ⚙️ Configuration

### Langfuse Tracing (Optional)

Enable observability by setting environment variables:

```bash
export LANGFUSE_PUBLIC_KEY="pk-..."
export LANGFUSE_SECRET_KEY="sk-..."
export LANGFUSE_HOST="https://cloud.langfuse.com"
export LANGFUSE_PROJECT_NAME="p1-seafoam-cicada"
export LANGFUSE_ENVIRONMENT="development"
```

The application runs normally without Langfuse - it's optional.

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
├─ .github/
│  └─ workflows/
│     └─ test.yml        # GitHub Actions CI
├── app/
│   ├─ __init__.py
│   ├── main.py                  # FastAPI application with all endpoints
│   ├── graph.py                 # LangGraph workflow definition (Phase 1 + Phase 2 refund flow)
│   ├── state.py                 # GraphState schema
│   ├── tools.py                 # LangChain tools (fetch_order, etc.)
│   ├── payments.py              # Refund preview/commit helpers (no real processor)
│   ├── persistence.py           # Pending ticket stores (in-memory + Postgres)
│   ├── policy_vector_store.py   # pgvector-backed policy_chunks store + query_policies
│   └── kb_index.py              # CLI to index NewPhase/policies into policy_chunks
├── interactions/
│  └─ phase1_demo.json           # Example interaction payloads/log (Phase 1)
├── NewPhase/
│   ├── policies/                # Markdown policy KB used for RAG
│   │   ├── refund_policy.md
│   │   ├── replacement_policy.md
│   │   ├── returns_policy.md
│   │   ├── cancellation_policy.md
│   │   ├── chargeback_policy.md
│   │   ├── delivery_policy.md
│   │   └── fraud_policy.md
│   ├── mock_data/               # Phase 2 mock data (mirrors core mock_data)
│   │   ├── orders.json
│   │   ├── issues.json
│   │   └── replies.json
│   └── interactions/
│       └── phase2_demo.json     # Example Phase 2 interaction payloads/log
├── mock_data/
│   ├── orders.json              # Sample order data
│   ├── issues.json              # Issue classification rules
│   └── replies.json             # Reply templates
├── data/
│   └── pending_ticket_ids.json  # Legacy/local persistence helper (Phase 1)
├── tests/
│   ├── test_graph.py            # Test suite for graph workflow
│   └── test_persistence.py      # Tests for persistent ticket store + checkpointing
├── init.sql                     # Boot-time Postgres init (pgvector + pending_tickets)
├── docker-compose.yml           # Postgres (pgvector) development database
├── pytest.ini                   # Pytest configuration
├── test_workflow.sh             # End-to-end test script
├── test_all.sh                  # Convenience test runner
├── requirements.txt             # Python dependencies
└── README.md                    # This file
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
