import pytest
from unittest.mock import patch, AsyncMock
from app.orchestrator.orchestrator import run_orchestrator

@pytest.mark.asyncio
async def test_run_orchestrator_safe(db_session):
    with patch("app.orchestrator.orchestrator.client.messages.create", new_callable=AsyncMock) as mock_create:
        mock_create.return_value.content = [AsyncMock(text="Here is your MRR trend.")]
        mock_create.return_value.stop_reason = "end_turn"
        
        response = await run_orchestrator(db_session, "tenant_test", "viewer", "What is my MRR?")
        
        assert "MRR trend" in response
        mock_create.assert_called_once()
        
        # Verify tools passed are filtered by role "viewer"
        kwargs = mock_create.call_args[1]
        assert len(kwargs["tools"]) == 2
        assert kwargs["tools"][0]["name"] == "get_metric_trend"

@pytest.mark.asyncio
async def test_run_orchestrator_tool_use(db_session):
    with patch("app.orchestrator.orchestrator.client.messages.create", new_callable=AsyncMock) as mock_create:
        
        class MockToolUse:
            type = "tool_use"
            name = "get_churn_rate"
            id = "tool_123"
            input = {"period": "last_month"}
            
        class MockContentBlock:
            type = "text"
            text = "Let me check."
            
        mock_resp1 = AsyncMock()
        mock_resp1.stop_reason = "tool_use"
        mock_resp1.content = [MockContentBlock(), MockToolUse()]
        
        mock_resp2 = AsyncMock()
        mock_resp2.stop_reason = "end_turn"
        mock_resp2.content = [AsyncMock(text="The churn rate is 5%.")]
        
        mock_create.side_effect = [mock_resp1, mock_resp2]
        
        response = await run_orchestrator(db_session, "tenant_test", "viewer", "What is my churn rate?")
        
        assert response == "The churn rate is 5%."
        assert mock_create.call_count == 2
