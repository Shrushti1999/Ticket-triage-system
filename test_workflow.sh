#!/bin/bash

echo "=== Step 1: Customer submits ticket ==="
RESPONSE=$(curl -s -X POST http://localhost:8000/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I need a refund for order ORD1001", "order_id": null}')
echo "$RESPONSE" | python3 -m json.tool

TICKET_ID=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['ticket_id'])")
echo ""
echo "Ticket ID: $TICKET_ID"

echo ""
echo "=== Step 2: Check pending tickets ==="
curl -s http://localhost:8000/triage/pending | python3 -m json.tool

echo ""
echo "=== Step 3: Admin approves ticket ==="
curl -s -X POST http://localhost:8000/triage/review \
  -H "Content-Type: application/json" \
  -d "{\"ticket_id\": \"$TICKET_ID\", \"decision\": \"approve\", \"feedback\": \"Approved for refund\"}" | python3 -m json.tool

echo ""
echo "=== Step 4: Verify no pending tickets ==="
curl -s http://localhost:8000/triage/pending | python3 -m json.tool

echo ""
echo "=== Workflow Complete! ==="

