import pytest
from fastapi.testclient import TestClient
from tests.conftest import DummyChannel

def test_channel_put_and_get_endpoints(dummy_channel: DummyChannel):
    """Test that we can PUT data and GET it back via the REST API."""
    
    # Using TestClient automatically runs the _lifespan startup/shutdown
    with TestClient(dummy_channel.app) as client:
        
        # 1. Test PUT (with a dummy payload)
        put_resp = client.put(
            dummy_channel.url, 
            json={"id": "item_1", "data": "hello world"},
            headers={"X-Sssn-Requester-Id": "agent_alpha"}
        )
        assert put_resp.status_code == 200
        assert put_resp.json()["status"] == "accepted"
        
        # Wait a tiny bit for the background loop to process the item from the buffer
        import time
        time.sleep(0.2) 
        
        # 2. Test GET
        get_resp = client.get(
            dummy_channel.url,
            headers={"X-Sssn-Requester-Id": "agent_alpha"}
        )
        assert get_resp.status_code == 200
        messages = get_resp.json()["messages"]
        assert len(messages) == 1
        assert messages[0]["content"] == "hello world"

def test_channel_access_control(dummy_channel: DummyChannel):
    """Test that the whitelist properly blocks unauthorized agents."""
    dummy_channel.readable_by = ["agent_alpha"] # Restrict access

    with TestClient(dummy_channel.app) as client:
        # Request with unauthorized ID should fail
        resp = client.get(
            dummy_channel.url,
            headers={"X-Sssn-Requester-Id": "rogue_agent"}
        )
        assert resp.status_code == 403