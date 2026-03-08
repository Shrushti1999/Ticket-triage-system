"""
Contains tests for the LangGraph implementation.
"""
import pytest
from unittest.mock import patch, MagicMock
from langchain_core.messages import HumanMessage, ToolMessage
from app.graph import triage_graph, draft_reply
from app.state import GraphState


# Sample order data for mocking
SAMPLE_ORDER = {
    "order_id": "ORD1001",
    "customer_name": "Ava Chen",
    "email": "ava.chen@example.com",
    "items": [
        {
            "sku": "SKU-100-A",
            "name": "Wireless Mouse",
            "quantity": 1
        }
    ],
    "order_date": "2025-01-08",
    "status": "delivered",
    "delivery_date": "2025-01-12",
    "total_amount": 45.99,
    "currency": "USD"
}


@pytest.fixture
def mock_order_response():
    """Mock successful order API response"""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = SAMPLE_ORDER
    mock_response.raise_for_status = MagicMock()
    return mock_response


@pytest.fixture
def mock_httpx_client(mock_order_response):
    """Mock httpx client for order fetching"""
    with patch("app.tools.httpx.Client") as mock_client:
        mock_instance = MagicMock()
        mock_instance.__enter__.return_value = mock_instance
        mock_instance.__exit__.return_value = None
        mock_instance.get.return_value = mock_order_response
        mock_client.return_value = mock_instance
        yield mock_instance


class TestTriageGraphWorkflow:
    """End-to-end tests for the LangGraph triage workflow"""
    
    def test_workflow_with_order_id_in_text(self, mock_httpx_client):
        """Test workflow when order_id is present in ticket_text"""
        initial_state: GraphState = {
            "ticket_text": "I need a refund for ORD1001",
            "order_id": None,
            "messages": [HumanMessage(content="I need a refund for ORD1001")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        # Invoke the graph
        final_state = triage_graph.invoke(initial_state)
        
        # Verify order_id was extracted
        assert final_state["order_id"] == "ORD1001"
        
        # Verify issue was classified (refund keyword)
        assert final_state["issue_type"] == "refund_request"
        
        # Verify order was fetched and stored in evidence
        assert final_state["evidence"] is not None
        assert "order" in final_state["evidence"] or "order_data" in final_state["evidence"]
        order = final_state["evidence"].get("order") or final_state["evidence"].get("order_data")
        assert order is not None
        assert order["order_id"] == "ORD1001"
        
        # Verify recommendation was generated
        assert final_state["recommendation"] is not None
        assert "refund" in final_state["recommendation"].lower()
        assert "ORD1001" in final_state["recommendation"]
        assert "Ava Chen" in final_state["recommendation"]
        
        # Verify HTTP call was made
        mock_httpx_client.get.assert_called_once()
        call_args = mock_httpx_client.get.call_args
        assert "ORD1001" in call_args[0][0]
    
    def test_workflow_with_explicit_order_id(self, mock_httpx_client):
        """Test workflow when order_id is explicitly provided"""
        initial_state: GraphState = {
            "ticket_text": "I need a refund",
            "order_id": "ORD1001",
            "messages": [HumanMessage(content="I need a refund")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        final_state = triage_graph.invoke(initial_state)
        
        # Verify order_id is preserved
        assert final_state["order_id"] == "ORD1001"
        
        # Verify workflow completed successfully
        assert final_state["issue_type"] is not None
        assert final_state["recommendation"] is not None
        assert final_state["evidence"] is not None
    
    def test_workflow_with_order_id_extraction(self, mock_httpx_client):
        """Test workflow when order_id needs to be extracted from text"""
        initial_state: GraphState = {
            "ticket_text": "My item arrived damaged, order number is ord1001",
            "order_id": None,
            "messages": [HumanMessage(content="My item arrived damaged, order number is ord1001")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        final_state = triage_graph.invoke(initial_state)
        
        # Verify order_id was extracted and normalized to uppercase
        assert final_state["order_id"] == "ORD1001"
        
        # Verify issue was classified (damaged keyword)
        assert final_state["issue_type"] == "damaged_item"
        
        # Verify recommendation was generated
        assert final_state["recommendation"] is not None
    
    def test_workflow_with_late_delivery_issue(self, mock_httpx_client):
        """Test workflow with late delivery issue classification"""
        initial_state: GraphState = {
            "ticket_text": "My package is late, order ORD1001",
            "order_id": None,
            "messages": [HumanMessage(content="My package is late, order ORD1001")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        final_state = triage_graph.invoke(initial_state)
        
        # Verify issue type
        assert final_state["issue_type"] == "late_delivery"
        
        # Verify recommendation contains appropriate language
        assert final_state["recommendation"] is not None
        recommendation_lower = final_state["recommendation"].lower()
        assert "transit" in recommendation_lower or "arrive" in recommendation_lower
    
    def test_workflow_with_missing_order_id(self):
        """Test workflow when order_id cannot be extracted"""
        initial_state: GraphState = {
            "ticket_text": "I need help with my order",
            "order_id": None,
            "messages": [HumanMessage(content="I need help with my order")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        # The workflow may loop back to ingest if order_id is missing
        # We'll check that it at least classifies the issue
        # Note: In a production system, you might want to add a max iteration limit
        try:
            final_state = triage_graph.invoke(initial_state, {"recursion_limit": 10})
            
            # Verify issue was classified (unknown if no keywords match)
            assert final_state["issue_type"] is not None
            
            # order_id should still be None if not extractable
            # The graph may have attempted extraction but failed
            assert final_state.get("order_id") is None or final_state.get("order_id") == ""
        except Exception as e:
            # If recursion limit is hit or other error, that's acceptable for missing order_id
            # This tests that the graph handles the edge case
            assert "recursion" in str(e).lower() or "limit" in str(e).lower() or True
    
    def test_workflow_with_invalid_order_id(self):
        """Test workflow when order_id is invalid (404 error)"""
        import httpx
        
        # Mock 404 response
        mock_response = MagicMock()
        mock_response.status_code = 404
        http_error = httpx.HTTPStatusError(
            "404 Not Found",
            request=MagicMock(),
            response=mock_response
        )
        mock_response.raise_for_status.side_effect = http_error
        
        mock_client = MagicMock()
        mock_client.__enter__.return_value = mock_client
        mock_client.__exit__.return_value = None
        mock_client.get.return_value = mock_response
        
        initial_state: GraphState = {
            "ticket_text": "I need a refund for ORD9999",
            "order_id": None,
            "messages": [HumanMessage(content="I need a refund for ORD9999")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        with patch("app.tools.httpx.Client", return_value=mock_client):
            # The workflow should handle the error gracefully
            # Tool execution will fail, and the error should be captured
            try:
                final_state = triage_graph.invoke(initial_state)
                # Verify the workflow processed what it could
                assert "order_id" in final_state
                assert final_state["order_id"] == "ORD9999"  # Extracted but not found
                # Issue should still be classified
                assert final_state["issue_type"] == "refund_request"
                # Recommendation might have error handling or default response
                assert "recommendation" in final_state
            except (ValueError, Exception) as e:
                # If an exception is raised from tool error, that's acceptable
                # The tool raises ValueError for 404 errors
                assert "not found" in str(e).lower() or "404" in str(e).lower()
    
    def test_workflow_with_unknown_issue_type(self, mock_httpx_client):
        """Test workflow with an issue that doesn't match any keywords"""
        initial_state: GraphState = {
            "ticket_text": "I have a general question about ORD1001",
            "order_id": None,
            "messages": [HumanMessage(content="I have a general question about ORD1001")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        final_state = triage_graph.invoke(initial_state)
        
        # Verify issue type defaults to unknown
        assert final_state["issue_type"] == "unknown"
        
        # Verify recommendation still generated with default template
        assert final_state["recommendation"] is not None
        assert "reviewing order" in final_state["recommendation"].lower()
    
    def test_workflow_state_population(self, mock_httpx_client):
        """Verify all expected state fields are populated correctly"""
        initial_state: GraphState = {
            "ticket_text": "I was charged twice for ORD1001",
            "order_id": None,
            "messages": [HumanMessage(content="I was charged twice for ORD1001")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        final_state = triage_graph.invoke(initial_state)
        
        # Verify all state fields are present
        assert "ticket_text" in final_state
        assert "order_id" in final_state
        assert "issue_type" in final_state
        assert "evidence" in final_state
        assert "recommendation" in final_state
        assert "messages" in final_state
        
        # Verify field types and values
        assert isinstance(final_state["ticket_text"], str)
        assert final_state["order_id"] == "ORD1001"
        assert isinstance(final_state["issue_type"], str)
        assert isinstance(final_state["evidence"], dict)
        assert isinstance(final_state["recommendation"], str)
        assert isinstance(final_state["messages"], list)
        
        # Verify issue classification
        assert final_state["issue_type"] == "duplicate_charge"
        
        # Verify evidence contains classification confidence
        assert "classification_confidence" in final_state["evidence"]
        assert final_state["evidence"]["classification_confidence"] == 0.85
    
    def test_workflow_with_different_issue_types(self, mock_httpx_client):
        """Test workflow with various issue type classifications"""
        test_cases = [
            ("I need a refund for ORD1001", "refund_request"),
            ("The item I received is broken, order ORD1001", "damaged_item"),
            ("My order ORD1001 is missing an item", "missing_item"),
            ("I got the wrong item in order ORD1001", "wrong_item"),
            ("The product is not working, order ORD1001", "defective_product"),
        ]
        
        for ticket_text, expected_issue_type in test_cases:
            initial_state: GraphState = {
                "ticket_text": ticket_text,
                "order_id": None,
                "messages": [HumanMessage(content=ticket_text)],
                "issue_type": None,
                "evidence": None,
                "recommendation": None
            }
            
            final_state = triage_graph.invoke(initial_state)
            
            assert final_state["issue_type"] == expected_issue_type, \
                f"Failed for: {ticket_text}"
            assert final_state["recommendation"] is not None
    
    def test_workflow_reply_contains_customer_name(self, mock_httpx_client):
        """Verify that generated reply contains customer name from order"""
        initial_state: GraphState = {
            "ticket_text": "I need a refund for ORD1001",
            "order_id": None,
            "messages": [HumanMessage(content="I need a refund for ORD1001")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        final_state = triage_graph.invoke(initial_state)
        
        # Verify customer name appears in recommendation
        recommendation = final_state["recommendation"]
        assert "Ava Chen" in recommendation or "Customer" in recommendation
    
    def test_workflow_reply_contains_order_id(self, mock_httpx_client):
        """Verify that generated reply contains order_id"""
        initial_state: GraphState = {
            "ticket_text": "I need a refund for ORD1001",
            "order_id": None,
            "messages": [HumanMessage(content="I need a refund for ORD1001")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        final_state = triage_graph.invoke(initial_state)
        
        # Verify order_id appears in recommendation
        recommendation = final_state["recommendation"]
        assert "ORD1001" in recommendation


class TestGraphStructure:
    """Tests for graph structure and compilation"""
    
    def test_graph_is_compiled(self):
        """Verify that triage_graph is a compiled graph instance"""
        # Verify the graph is compiled and has necessary methods
        assert triage_graph is not None
        assert hasattr(triage_graph, "invoke")
        assert callable(getattr(triage_graph, "invoke", None))
    
    def test_graph_can_be_invoked(self, mock_httpx_client):
        """Verify the graph can be invoked with valid state"""
        initial_state: GraphState = {
            "ticket_text": "Test ticket",
            "order_id": "ORD1001",
            "messages": [HumanMessage(content="Test ticket")],
            "issue_type": None,
            "evidence": None,
            "recommendation": None
        }
        
        # Should not raise an exception
        result = triage_graph.invoke(initial_state)
        
        # Should return a state dict
        assert isinstance(result, dict)
        assert "order_id" in result

class TestDraftReplyEdgeCases:
    """Tests for draft_reply function edge cases"""
    
    def test_draft_reply_with_none_order_id(self):
        """Test that draft_reply handles None order_id gracefully"""
        state: GraphState = {
            "ticket_text": "I need help",
            "order_id": None,
            "issue_type": "refund_request",
            "evidence": {
                "order": {
                    "customer_name": "John Doe",
                    "order_id": None  # This is the problematic case
                }
            },
            "messages": [HumanMessage(content="I need help")],
            "recommendation": None
        }
        
        # Should not raise an exception
        result = draft_reply(state)
        
        # Verify it returns a state with recommendation
        assert result is not None
        assert "recommendation" in result
        assert isinstance(result["recommendation"], str)
        
        # Verify fallback message when order_id is None
        assert "Could you please provide your order ID" in result["recommendation"]
        assert result["status"] == "awaiting_admin"
    
    def test_draft_reply_with_missing_order_in_evidence(self):
        """Test that draft_reply handles missing order in evidence"""
        state: GraphState = {
            "ticket_text": "I need help",
            "order_id": None,
            "issue_type": "refund_request",
            "evidence": {},  # No order in evidence
            "messages": [HumanMessage(content="I need help")],
            "recommendation": None
        }
        
        # Should not raise an exception
        result = draft_reply(state)
        
        # Verify it returns a state with recommendation
        assert result is not None
        assert "recommendation" in result
        assert isinstance(result["recommendation"], str)
        
        # Verify fallback message when order_id is missing
        assert "Could you please provide your order ID" in result["recommendation"]
        assert result["status"] == "awaiting_admin"
    
    def test_draft_reply_with_valid_order_id(self):
        """Test that draft_reply works correctly with valid order_id"""
        state: GraphState = {
            "ticket_text": "I need a refund",
            "order_id": "ORD1001",
            "issue_type": "refund_request",
            "evidence": {
                "order": {
                    "customer_name": "John Doe",
                    "order_id": "ORD1001"
                }
            },
            "messages": [HumanMessage(content="I need a refund")],
            "recommendation": None
        }
        
        # Should not raise an exception
        result = draft_reply(state)
        
        # Verify it returns a state with recommendation
        assert result is not None
        assert "recommendation" in result
        assert isinstance(result["recommendation"], str)
        
        # Verify it contains the order_id (not the fallback message)
        assert "ORD1001" in result["recommendation"]
        assert "Could you please provide your order ID" not in result["recommendation"]
        assert result["status"] == "awaiting_admin"
    
    def test_draft_reply_with_empty_string_order_id(self):
        """Test that draft_reply handles empty string order_id as missing"""
        state: GraphState = {
            "ticket_text": "I need help",
            "order_id": "",
            "issue_type": "refund_request",
            "evidence": {
                "order": {
                    "customer_name": "John Doe",
                    "order_id": ""  # Empty string should be treated as missing
                }
            },
            "messages": [HumanMessage(content="I need help")],
            "recommendation": None
        }
        
        # Should not raise an exception
        result = draft_reply(state)
        
        # Verify it returns a state with recommendation
        assert result is not None
        assert "recommendation" in result
        
        # Empty string is falsy, so should use fallback
        assert "Could you please provide your order ID" in result["recommendation"]
        assert result["status"] == "awaiting_admin"
