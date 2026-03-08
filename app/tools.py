"""
Contains LangChain tools utilized in the application.
"""
import httpx
from langchain_core.tools import tool


@tool
def fetch_order(order_id: str) -> dict:
    """
    Fetches order details by order_id from the orders API.
    
    Args:
        order_id: The order ID to fetch details for.
        
    Returns:
        dict: Order data containing order details.
        
    Raises:
        ValueError: If the order is not found or the API request fails.
    """
    try:
        url = f"http://localhost:8000/orders/get?order_id={order_id}"
        with httpx.Client() as client:
            response = client.get(url, timeout=10.0)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            raise ValueError(f"Order with ID '{order_id}' not found")
        raise ValueError(f"Failed to fetch order: HTTP {e.response.status_code}")
    except httpx.RequestError as e:
        raise ValueError(f"Failed to connect to orders API: {str(e)}")
    except Exception as e:
        raise ValueError(f"Unexpected error fetching order: {str(e)}")


# Export list of tools for use in LangGraph
tools = [fetch_order]
