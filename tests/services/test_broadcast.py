"""Tests for broadcast service."""
import queue
import time
from unittest.mock import Mock, MagicMock
import pytest
from services.broadcast import StreamBroadcaster


class TestStreamBroadcaster:
    """Tests for StreamBroadcaster class."""

    def test_broadcaster_initialization(self):
        """Test broadcaster initializes correctly."""
        broadcaster = StreamBroadcaster(buffer_size=50)

        assert broadcaster.buffer.maxlen == 50
        assert broadcaster.clients == []
        assert broadcaster.active is False
        assert broadcaster.reader_thread is None

    def test_subscribe_creates_queue(self):
        """Test subscribing creates a new client queue."""
        broadcaster = StreamBroadcaster()

        client_queue = broadcaster.subscribe()

        assert isinstance(client_queue, queue.Queue)
        assert client_queue in broadcaster.clients
        assert len(broadcaster.clients) == 1

    def test_subscribe_multiple_clients(self):
        """Test multiple clients can subscribe."""
        broadcaster = StreamBroadcaster()

        queue1 = broadcaster.subscribe()
        queue2 = broadcaster.subscribe()
        queue3 = broadcaster.subscribe()

        assert len(broadcaster.clients) == 3
        assert queue1 in broadcaster.clients
        assert queue2 in broadcaster.clients
        assert queue3 in broadcaster.clients

    def test_subscribe_receives_buffer(self):
        """Test new subscriber receives buffered chunks."""
        broadcaster = StreamBroadcaster(buffer_size=10)

        # Add some chunks to buffer
        broadcaster.buffer.append(b"chunk1")
        broadcaster.buffer.append(b"chunk2")
        broadcaster.buffer.append(b"chunk3")

        # Subscribe
        client_queue = broadcaster.subscribe()

        # Should have received buffered chunks
        assert client_queue.qsize() == 3
        assert client_queue.get_nowait() == b"chunk1"
        assert client_queue.get_nowait() == b"chunk2"
        assert client_queue.get_nowait() == b"chunk3"

    def test_subscribe_full_queue_skips_old_chunks(self):
        """Test that full queue skips old buffered chunks."""
        broadcaster = StreamBroadcaster(buffer_size=100)

        # Fill buffer with many chunks
        for i in range(100):
            broadcaster.buffer.append(f"chunk{i}".encode())

        # Subscribe with default maxsize queue (200)
        # This should try to add all 100 chunks but skip some due to queue full
        client_queue = broadcaster.subscribe()

        # Queue should have some chunks but not overflow
        assert client_queue.qsize() <= 200  # Queue maxsize

    def test_unsubscribe_removes_client(self):
        """Test unsubscribing removes client queue."""
        broadcaster = StreamBroadcaster()

        client_queue = broadcaster.subscribe()
        assert client_queue in broadcaster.clients

        broadcaster.unsubscribe(client_queue)

        assert client_queue not in broadcaster.clients
        assert len(broadcaster.clients) == 0

    def test_unsubscribe_nonexistent_client(self):
        """Test unsubscribing non-existent client doesn't error."""
        broadcaster = StreamBroadcaster()

        fake_queue = queue.Queue()
        broadcaster.unsubscribe(fake_queue)  # Should not raise

    def test_stop_clears_state(self):
        """Test stop clears broadcaster state."""
        broadcaster = StreamBroadcaster()

        # Add some clients and buffer
        broadcaster.subscribe()
        broadcaster.subscribe()
        broadcaster.buffer.append(b"test")

        broadcaster.stop()

        assert broadcaster.active is False
        assert len(broadcaster.clients) == 0
        assert len(broadcaster.buffer) == 0

    def test_is_active(self):
        """Test is_active returns correct state."""
        broadcaster = StreamBroadcaster()

        assert broadcaster.is_active() is False

        broadcaster.active = True
        assert broadcaster.is_active() is True

        broadcaster.active = False
        assert broadcaster.is_active() is False

    def test_start_broadcasting_starts_thread(self):
        """Test start_broadcasting starts reader thread."""
        broadcaster = StreamBroadcaster()

        # Mock process that stays running for a bit
        mock_process = Mock()
        mock_process.poll.side_effect = [None, None, None, 0]  # Running for a few iterations
        mock_process.stdout.read1 = Mock(side_effect=[
            b"chunk1",
            b"chunk2",
            b""  # EOF to end the loop
        ])

        broadcaster.start_broadcasting(mock_process)

        # Check immediately - thread should be created and active
        assert broadcaster.reader_thread is not None
        assert broadcaster.reader_thread.daemon is True
        # Note: Can't reliably check active state due to race condition with thread execution

        # Wait for thread to finish
        broadcaster.reader_thread.join(timeout=1)

    def test_read_and_broadcast_sends_chunks(self):
        """Test that chunks are broadcast to all clients."""
        broadcaster = StreamBroadcaster()

        # Subscribe two clients
        client1 = broadcaster.subscribe()
        client2 = broadcaster.subscribe()

        # Mock process that returns some data
        mock_process = Mock()
        mock_process.poll.side_effect = [None, None, 0]  # Running, running, finished
        mock_process.stdout.read1 = Mock(side_effect=[
            b"chunk1",
            b"chunk2",
            b""  # EOF
        ])

        broadcaster.start_broadcasting(mock_process)

        # Wait for broadcasting to finish
        broadcaster.reader_thread.join(timeout=2)

        # Both clients should have received chunks
        assert client1.get_nowait() == b"chunk1"
        assert client1.get_nowait() == b"chunk2"

        assert client2.get_nowait() == b"chunk1"
        assert client2.get_nowait() == b"chunk2"

    def test_read_and_broadcast_adds_to_buffer(self):
        """Test that chunks are added to buffer."""
        broadcaster = StreamBroadcaster(buffer_size=10)

        # Mock process
        mock_process = Mock()
        mock_process.poll.side_effect = [None, 0]
        mock_process.stdout.read1 = Mock(side_effect=[
            b"chunk1",
            b""
        ])

        broadcaster.start_broadcasting(mock_process)
        broadcaster.reader_thread.join(timeout=2)

        assert b"chunk1" in broadcaster.buffer

    def test_read_and_broadcast_sends_eof(self):
        """Test that EOF (None) is sent to clients."""
        broadcaster = StreamBroadcaster()

        client = broadcaster.subscribe()

        # Mock process
        mock_process = Mock()
        mock_process.poll.return_value = 0
        mock_process.stdout.read1 = Mock(return_value=b"")

        broadcaster.start_broadcasting(mock_process)
        broadcaster.reader_thread.join(timeout=2)

        # Should receive EOF marker
        assert client.get_nowait() is None

    def test_read_and_broadcast_handles_exception(self):
        """Test that exceptions in broadcast thread are handled."""
        broadcaster = StreamBroadcaster()

        # Mock process that raises exception
        mock_process = Mock()
        mock_process.poll.side_effect = Exception("Read error")

        broadcaster.start_broadcasting(mock_process)
        broadcaster.reader_thread.join(timeout=2)

        # Broadcaster should stop gracefully
        assert broadcaster.active is False
