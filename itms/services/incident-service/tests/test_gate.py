import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from incident_service.gate import IncidentGate

class MockCalibrator:
    def __init__(self, threshold=0.8):
        self.threshold = threshold
        self.feedbacks = []
        
    def feedback(self, score):
        self.feedbacks.append(score)

@pytest_asyncio.fixture
async def gate():
    calibrator = MockCalibrator(threshold=0.8)
    bus = AsyncMock()
    # Mock psycopg connect
    with patch('psycopg.AsyncConnection.connect', new_callable=AsyncMock) as mock_connect:
        mock_conn = AsyncMock()
        mock_cur = AsyncMock()
        mock_cur.fetchone.return_value = ("link_123", "junc_456")
        
        # Setup context managers
        mock_connect.return_value.__aenter__.return_value = mock_conn
        mock_conn.cursor.return_value.__aenter__.return_value = mock_cur
        
        gate_instance = IncidentGate(calibrator, "mock_db_url", bus)
        yield gate_instance, mock_cur, bus, calibrator

@pytest.mark.asyncio
async def test_check_and_raise_below_threshold(gate):
    gate_instance, mock_cur, bus, _ = gate
    
    candidate_id = await gate_instance.check_and_raise(
        link_id="edge_1",
        graph_score=1.0,
        fused_score=0.5, # Below 0.8 threshold
        features={"speed": 10},
        signal_phase="r"
    )
    
    assert candidate_id is None
    bus.publish.assert_not_called()
    mock_cur.execute.assert_not_called()

@pytest.mark.asyncio
async def test_check_and_raise_above_threshold(gate):
    gate_instance, mock_cur, bus, _ = gate
    
    candidate_id = await gate_instance.check_and_raise(
        link_id="edge_1",
        graph_score=3.0,
        fused_score=0.9, # Above 0.8 threshold
        features={"speed": 2},
        signal_phase="g"
    )
    
    assert candidate_id is not None
    assert bus.publish.call_count == 1
    args, kwargs = bus.publish.call_args
    assert args[0] == "incident.candidate"
    
    assert mock_cur.execute.call_count == 1
    execute_args = mock_cur.execute.call_args[0]
    assert "INSERT INTO incident" in execute_args[0]

@pytest.mark.asyncio
async def test_confirm(gate):
    gate_instance, mock_cur, bus, _ = gate
    
    incident_id = await gate_instance.confirm("mock_candidate_id", "operator", "major")
    
    assert incident_id is not None
    assert bus.publish.call_count == 1
    args, kwargs = bus.publish.call_args
    assert args[0] == "incident.detected"
    
    assert mock_cur.execute.call_count == 1
    execute_args = mock_cur.execute.call_args[0]
    assert "UPDATE incident" in execute_args[0]

@pytest.mark.asyncio
async def test_reject(gate):
    gate_instance, mock_cur, bus, calibrator = gate
    
    # For reject, fetchone returns incident_id (or None), and fused_score
    mock_cur.fetchone.return_value = ("incident_123", 0.9)
    
    await gate_instance.reject("mock_candidate_id", "false alarm")
    
    assert bus.publish.call_count == 1
    args, kwargs = bus.publish.call_args
    assert args[0] == "incident.updated"
    
    assert mock_cur.execute.call_count == 1
    execute_args = mock_cur.execute.call_args[0]
    assert "UPDATE incident" in execute_args[0]
    assert "SET status = 'rejected'" in execute_args[0]
    
    assert len(calibrator.feedbacks) == 1
    assert calibrator.feedbacks[0] == 0.9
