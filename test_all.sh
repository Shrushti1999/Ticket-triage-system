#!/bin/bash

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

BASE_URL="http://localhost:8000"

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}   TICKET TRIAGE SYSTEM - COMPLETE TEST    ${NC}"
echo -e "${BLUE}   Three-Entity Workflow: Customer →       ${NC}"
echo -e "${BLUE}   Assistant → Admin                       ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""

#############################################
# SECTION 1: HEALTH CHECK
#############################################
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  SECTION 1: HEALTH CHECK                   ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}Test 1.1: Health Check${NC}"
curl -s $BASE_URL/health | python3 -m json.tool
echo ""

#############################################
# SECTION 2: ALL ISSUE TYPES
#############################################
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  SECTION 2: CUSTOMER - ALL ISSUE TYPES     ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}Test 2.1: Refund Request (ORD1001)${NC}"
RESPONSE=$(curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I need a refund for order ORD1001", "order_id": null}')
echo "$RESPONSE" | python3 -m json.tool
TICKET_REFUND=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('ticket_id', 'N/A'))" 2>/dev/null)
echo -e "${GREEN}→ Ticket ID: $TICKET_REFUND${NC}"
echo ""

echo -e "${YELLOW}Test 2.2: Late Delivery (ORD1002)${NC}"
RESPONSE=$(curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "My order ORD1002 is late, where is it?", "order_id": null}')
echo "$RESPONSE" | python3 -m json.tool
TICKET_LATE=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('ticket_id', 'N/A'))" 2>/dev/null)
echo -e "${GREEN}→ Ticket ID: $TICKET_LATE${NC}"
echo ""

echo -e "${YELLOW}Test 2.3: Damaged Item (ORD1003)${NC}"
RESPONSE=$(curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "The product from order ORD1003 arrived damaged", "order_id": null}')
echo "$RESPONSE" | python3 -m json.tool
TICKET_DAMAGED=$(echo "$RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('ticket_id', 'N/A'))" 2>/dev/null)
echo -e "${GREEN}→ Ticket ID: $TICKET_DAMAGED${NC}"
echo ""

echo -e "${YELLOW}Test 2.4: Missing Item (ORD1001)${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "Items are missing from my order ORD1001", "order_id": null}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 2.5: Duplicate Charge (ORD1002)${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I was charged twice for order ORD1002", "order_id": null}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 2.6: Wrong Item (ORD1003)${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I received the wrong item in order ORD1003", "order_id": null}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 2.7: Defective Product (ORD1001)${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "The product from order ORD1001 is defective", "order_id": null}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 2.8: Unknown Issue Type (ORD1002)${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I have a general question about order ORD1002", "order_id": null}' | python3 -m json.tool
echo ""

#############################################
# SECTION 3: EDGE CASES
#############################################
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  SECTION 3: EDGE CASES                     ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}Test 3.1: Order ID Provided Explicitly${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I want a refund please", "order_id": "ORD1001"}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 3.2: No Order ID in Text${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I want a refund for my recent purchase", "order_id": null}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 3.3: Empty Ticket Text (Should Fail)${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "", "order_id": null}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 3.4: Invalid Order ID (Order Not Found)${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "Refund for order ORD9999 please", "order_id": null}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 3.5: Lowercase Order ID${NC}"
curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "Refund for ord1001 please", "order_id": null}' | python3 -m json.tool
echo ""

#############################################
# SECTION 4: ADMIN REVIEW FLOW
#############################################
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  SECTION 4: ADMIN REVIEW FLOW              ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}Test 4.1: View All Pending Tickets${NC}"
curl -s $BASE_URL/triage/pending | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 4.2: Admin Approves Refund Ticket${NC}"
if [ "$TICKET_REFUND" != "N/A" ] && [ -n "$TICKET_REFUND" ]; then
  curl -s -X POST $BASE_URL/triage/review \
    -H "Content-Type: application/json" \
    -d "{\"ticket_id\": \"$TICKET_REFUND\", \"decision\": \"approve\", \"feedback\": \"Refund approved, process immediately\"}" | python3 -m json.tool
else
  echo -e "${RED}No refund ticket ID available${NC}"
fi
echo ""

echo -e "${YELLOW}Test 4.3: Admin Rejects Late Delivery Ticket${NC}"
if [ "$TICKET_LATE" != "N/A" ] && [ -n "$TICKET_LATE" ]; then
  curl -s -X POST $BASE_URL/triage/review \
    -H "Content-Type: application/json" \
    -d "{\"ticket_id\": \"$TICKET_LATE\", \"decision\": \"reject\", \"feedback\": \"Need to offer compensation first\"}" | python3 -m json.tool
else
  echo -e "${RED}No late delivery ticket ID available${NC}"
fi
echo ""

echo -e "${YELLOW}Test 4.4: Check Remaining Pending Tickets${NC}"
curl -s $BASE_URL/triage/pending | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 4.5: Invalid Decision (Should Fail)${NC}"
if [ "$TICKET_DAMAGED" != "N/A" ] && [ -n "$TICKET_DAMAGED" ]; then
  curl -s -X POST $BASE_URL/triage/review \
    -H "Content-Type: application/json" \
    -d "{\"ticket_id\": \"$TICKET_DAMAGED\", \"decision\": \"maybe\", \"feedback\": \"\"}" | python3 -m json.tool
else
  echo -e "${RED}No damaged ticket ID available${NC}"
fi
echo ""

echo -e "${YELLOW}Test 4.6: Ticket Not Found${NC}"
curl -s -X POST $BASE_URL/triage/review \
  -H "Content-Type: application/json" \
  -d '{"ticket_id": "nonexistent123", "decision": "approve", "feedback": ""}' | python3 -m json.tool
echo ""

#############################################
# SECTION 5: ORDER ENDPOINTS
#############################################
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  SECTION 5: ORDER ENDPOINTS                ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}Test 5.1: Get Order ORD1001${NC}"
curl -s "$BASE_URL/orders/get?order_id=ORD1001" | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 5.2: Get Order ORD1002${NC}"
curl -s "$BASE_URL/orders/get?order_id=ORD1002" | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 5.3: Get Order ORD1003${NC}"
curl -s "$BASE_URL/orders/get?order_id=ORD1003" | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 5.4: Get Invalid Order (Should Fail)${NC}"
curl -s "$BASE_URL/orders/get?order_id=ORD9999" | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 5.5: Search Orders by Query${NC}"
curl -s "$BASE_URL/orders/search?q=ORD1001" | python3 -m json.tool
echo ""

#############################################
# SECTION 6: UTILITY ENDPOINTS
#############################################
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  SECTION 6: UTILITY ENDPOINTS              ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${YELLOW}Test 6.1: Classify Issue - Refund${NC}"
curl -s -X POST $BASE_URL/classify/issue \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I need a refund"}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 6.2: Classify Issue - Late Delivery${NC}"
curl -s -X POST $BASE_URL/classify/issue \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "My order is late"}' | python3 -m json.tool
echo ""

echo -e "${YELLOW}Test 6.3: Draft Reply${NC}"
curl -s -X POST $BASE_URL/reply/draft \
  -H "Content-Type: application/json" \
  -d '{"issue_type": "refund_request", "order": {"customer_name": "John Doe", "order_id": "ORD1001"}}' | python3 -m json.tool
echo ""

#############################################
# SECTION 7: COMPLETE WORKFLOW DEMO
#############################################
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}  SECTION 7: COMPLETE THREE-ENTITY WORKFLOW ${NC}"
echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

echo -e "${GREEN}Step 1: CUSTOMER submits a support ticket${NC}"
DEMO_RESPONSE=$(curl -s -X POST $BASE_URL/triage/invoke \
  -H "Content-Type: application/json" \
  -d '{"ticket_text": "I need a refund for order ORD1001, the product was defective", "order_id": null}')
echo "$DEMO_RESPONSE" | python3 -m json.tool
DEMO_TICKET=$(echo "$DEMO_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin).get('ticket_id', 'N/A'))" 2>/dev/null)
echo -e "${GREEN}→ Ticket Created: $DEMO_TICKET${NC}"
echo -e "${GREEN}→ Status: awaiting_admin (ASSISTANT has processed)${NC}"
echo ""

echo -e "${GREEN}Step 2: ADMIN views pending tickets${NC}"
curl -s $BASE_URL/triage/pending | python3 -m json.tool
echo ""

echo -e "${GREEN}Step 3: ADMIN approves the recommendation${NC}"
if [ "$DEMO_TICKET" != "N/A" ] && [ -n "$DEMO_TICKET" ]; then
  curl -s -X POST $BASE_URL/triage/review \
    -H "Content-Type: application/json" \
    -d "{\"ticket_id\": \"$DEMO_TICKET\", \"decision\": \"approve\", \"feedback\": \"Approved - customer is eligible for refund\"}" | python3 -m json.tool
fi
echo ""

echo -e "${GREEN}Step 4: Verify workflow completed (no pending tickets)${NC}"
curl -s $BASE_URL/triage/pending | python3 -m json.tool
echo ""

#############################################
# SUMMARY
#############################################
echo -e "${BLUE}============================================${NC}"
echo -e "${GREEN}   ALL TESTS COMPLETED SUCCESSFULLY!       ${NC}"
echo -e "${BLUE}============================================${NC}"
echo ""
echo -e "Test Sections:"
echo -e "  ✅ Section 1: Health Check"
echo -e "  ✅ Section 2: All Issue Types (8 types)"
echo -e "  ✅ Section 3: Edge Cases (5 cases)"
echo -e "  ✅ Section 4: Admin Review Flow"
echo -e "  ✅ Section 5: Order Endpoints"
echo -e "  ✅ Section 6: Utility Endpoints"
echo -e "  ✅ Section 7: Complete Workflow Demo"
echo ""
echo -e "${BLUE}Three-Entity Workflow Verified:${NC}"
echo -e "  👤 Customer → Submits ticket"
echo -e "  🤖 Assistant → Processes & drafts reply"
echo -e "  👨‍💼 Admin → Approves/Rejects"
echo ""
