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

## 🚀 Quick Start

### Prerequisites

- **Python 3.9+** (3.9, 3.10, 3.11, or 3.12)

### Installation

```bash
# Clone the repository
git clone <github url>
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

## 🏗️ Architecture

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
│     └─ tests.yml       # GitHub Actions CI
├── .pytest_cache/       # Pytest cache (auto-generated)
├── app/
│   ├─ __init__.py
│   ├── main.py          # FastAPI application with all endpoints
│   ├── graph.py         # LangGraph workflow definition
│   ├── state.py         # GraphState schema
│   └── tools.py         # LangChain tools (fetch_order)
├── interactions/
│  └─ phase1_demo.json   # Example interaction payloads/log
├── mock_data/
│   ├── orders.json      # Sample order data
│   ├── issues.json      # Issue classification rules
│   └── replies.json     # Reply templates
├── tests/
│   └── test_graph.py    # Test suite for graph workflow
├── test_workflow.sh     # End-to-end test script
├── test_all.sh          # Convenience test runner
├── requirements.txt     # Python dependencies
└── README.md            # This file
```

## 🛠️ Built With

- **[LangGraph](https://github.com/langchain-ai/langgraph)** - Workflow orchestration
- **[LangChain](https://github.com/langchain-ai/langchain)** - LLM framework & tools
- **[FastAPI](https://fastapi.tiangolo.com/)** - Web framework
- **[Langfuse](https://langfuse.com/)** - Observability (optional)

## 📝 How I Used Cursor

This project was developed with the assistance of **Cursor AI**, which helped with:
I started by independently reading the assignment and writing a brief plan and README outline without using any AI tools, focusing on the LangGraph state design, node responsibilities, and control flow. Once the architecture was clear, I broke the work into small, explicit implementation steps and used Cursor as a coding copilot to accelerate writing boilerplate and wiring modules together. After each step, I manually reviewed the generated code, ran tests, and validated behavior against the assignment requirements. I used AI tools selectively for iteration and verification, but all design decisions, graph structure, and edge-case handling were driven by my own reasoning. I finalized the project by adding CI with GitHub Actions, refining the README, and manually testing the API end-to-end using curl and Postman.

---
