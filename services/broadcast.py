"""
Audio stream broadcasting service.

Handles multi-client streaming with replay buffer for reconnecting clients.
"""
import logging
import threading
import queue
from collections import deque
from typing import List

logger = logging.getLogger(__name__)


class StreamBroadcaster:
    """Broadcasts audio stream to multiple clients with replay buffer."""

    def __init__(self, buffer_size: int = 100):
        self.clients: List[queue.Queue] = []
        self.buffer = deque(maxlen=buffer_size)  # Keep last N chunks for reconnecting clients
        self.lock = threading.Lock()
        self.active = False
        self.reader_thread = None

    def start_broadcasting(self, process):
        """Start reading from process stdout and broadcasting to clients."""
        self.active = True
        self.reader_thread = threading.Thread(
            target=self._read_and_broadcast,
            args=(process,),
            daemon=True
        )
        self.reader_thread.start()

    def _read_and_broadcast(self, process):
        """Read from process stdout and send to all clients (runs in background thread)."""
        chunk_size = 8192
        try:
            while self.active and process.poll() is None:
                chunk = process.stdout.read(chunk_size)
                if not chunk:
                    break

                with self.lock:
                    # Add to buffer for late-joining clients
                    self.buffer.append(chunk)

                    # Send to all connected clients (thread-safe)
                    for client_queue in self.clients[:]:  # Copy list to avoid modification during iteration
                        try:
                            client_queue.put_nowait(chunk)
                        except queue.Full:
                            # Client queue is full, skip this chunk for this client
                            pass
                        except:
                            # Client disconnected, will be removed later
                            pass

        except Exception as e:
            logger.error(f"Error in broadcast reader: {e}")
        finally:
            # Signal EOF to all clients
            with self.lock:
                for client_queue in self.clients[:]:
                    try:
                        client_queue.put_nowait(None)
                    except:
                        pass
            self.active = False

    def subscribe(self) -> queue.Queue:
        """Subscribe a new client to the stream."""
        client_queue = queue.Queue(maxsize=50)

        with self.lock:
            self.clients.append(client_queue)

            # Send buffered chunks to new client so they can catch up
            for chunk in self.buffer:
                try:
                    client_queue.put_nowait(chunk)
                except queue.Full:
                    # Skip old chunks if queue is full
                    pass

        return client_queue

    def unsubscribe(self, client_queue: queue.Queue):
        """Unsubscribe a client from the stream."""
        with self.lock:
            if client_queue in self.clients:
                self.clients.remove(client_queue)

    def stop(self):
        """Stop broadcasting."""
        self.active = False
        with self.lock:
            self.clients.clear()
            self.buffer.clear()

    def is_active(self) -> bool:
        """Check if broadcaster is active."""
        return self.active
