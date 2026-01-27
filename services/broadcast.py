"""
Audio stream broadcasting service.

Handles multi-client streaming with replay buffer for reconnecting clients.
"""

import logging
import threading
import queue
import select
import platform
import time
from collections import deque
from typing import List, Optional

logger = logging.getLogger(__name__)


class StreamBroadcaster:
    """Broadcasts audio stream to multiple clients with replay buffer."""

    def __init__(self, buffer_size: int = 300):
        self.clients: List[queue.Queue[bytes]] = []
        self.buffer: deque[bytes] = deque(
            maxlen=buffer_size
        )  # Keep last N chunks for reconnecting clients (~2.4MB at 8KB chunks)
        self.lock = threading.Lock()
        self.active = False
        self.reader_thread: Optional[threading.Thread] = None
        self.dropped_chunks_count: dict[int, int] = (
            {}
        )  # Track dropped chunks per client for rate-limited logging
        self.last_cleanup: float = 0  # Track last cleanup time
        self.cleanup_interval = 60  # Clean up every 60 seconds

    def start_broadcasting(self, process):
        """Start reading from process stdout and broadcasting to clients."""
        self.active = True
        self.reader_thread = threading.Thread(
            target=self._read_and_broadcast, args=(process,), daemon=True
        )
        self.reader_thread.start()

    def _read_and_broadcast(self, process):
        """Read from process stdout and send to all clients (runs in background thread)."""
        chunk_size = 8192
        import time

        # Check if we can use select (Unix-like systems)
        use_select = platform.system() != "Windows" and hasattr(process.stdout, "fileno")

        try:
            logger.info("Broadcaster: Starting to read from process")
            while self.active:
                chunk = None

                if use_select:
                    # Use select with 1 second timeout
                    try:
                        ready, _, _ = select.select([process.stdout], [], [], 1.0)
                        if ready:
                            chunk = process.stdout.read1(chunk_size)
                        # else: timeout, will check process status below
                    except Exception as e:
                        logger.error(f"Broadcaster: Error in select: {e}")
                        break
                else:
                    # Fallback for Windows or non-file-like streams
                    try:
                        if hasattr(process.stdout, "read1"):
                            chunk = process.stdout.read1(chunk_size)
                        else:
                            chunk = process.stdout.read(chunk_size)
                    except Exception as e:
                        logger.error(f"Broadcaster: Error reading from process: {e}")
                        break

                if not chunk:
                    # Check if process ended
                    poll_result = process.poll()
                    if poll_result is not None:
                        logger.info(f"Broadcaster: Process ended with code {poll_result}")
                        break

                    # Process still running but no data
                    if not use_select:
                        time.sleep(0.01)  # Only sleep if not using select
                    continue

                with self.lock:
                    # Add to buffer for late-joining clients
                    self.buffer.append(chunk)

                    # Send to all connected clients (thread-safe)
                    dropped_clients = []
                    for client_queue in self.clients[:]:
                        try:
                            # Use put with timeout instead of put_nowait
                            # This gives slow clients a chance to catch up (2 seconds for network issues)
                            client_queue.put(chunk, timeout=2.0)

                            # Reset dropped chunks counter on successful delivery
                            if id(client_queue) in self.dropped_chunks_count:
                                del self.dropped_chunks_count[id(client_queue)]

                        except queue.Full:
                            # Client queue is full even after timeout
                            # Track dropped chunks and only log periodically to avoid spam
                            client_id = id(client_queue)
                            self.dropped_chunks_count[client_id] = (
                                self.dropped_chunks_count.get(client_id, 0) + 1
                            )

                            # Log warning only on first drop and every 100 drops after that
                            dropped_count = self.dropped_chunks_count[client_id]
                            if dropped_count == 1 or dropped_count % 100 == 0:
                                logger.warning(
                                    f"Broadcaster: Client queue full, dropped {dropped_count} chunks total "
                                    f"(client may be paused or too slow)"
                                )
                            # Don't drop the client, just skip this chunk
                            pass
                        except Exception as e:
                            logger.error(f"Broadcaster: Error sending to client: {e}")
                            dropped_clients.append(client_queue)

                    # Remove failed clients
                    for client_queue in dropped_clients:
                        if client_queue in self.clients:
                            self.clients.remove(client_queue)
                            # Clean up dropped chunks counter
                            client_id = id(client_queue)
                            if client_id in self.dropped_chunks_count:
                                del self.dropped_chunks_count[client_id]
                            logger.info(f"Broadcaster: Removed failed client")

            logger.info("Broadcaster: Exiting read loop")

        except Exception as e:
            logger.error(f"Broadcaster: Error in broadcast reader: {e}", exc_info=True)
        finally:
            # Signal EOF to all clients
            logger.info("Broadcaster: Sending EOF to all clients")
            with self.lock:
                for client_queue in self.clients[:]:
                    try:
                        client_queue.put_nowait(None)
                    except:
                        pass
            self.active = False
            logger.info("Broadcaster: Stopped")

    def subscribe(self) -> queue.Queue[bytes]:
        """Subscribe a new client to the stream."""
        # Increase queue size to prevent dropping chunks for slow clients
        # 500 chunks * 8KB = ~4MB buffer per client (allows better buffering for network issues)
        client_queue: queue.Queue[bytes] = queue.Queue(maxsize=500)

        with self.lock:
            self.clients.append(client_queue)
            logger.info(f"Broadcaster: New client subscribed (total clients: {len(self.clients)})")

            # Periodic cleanup of dead clients
            now = time.time()
            if now - self.last_cleanup > self.cleanup_interval:
                self._cleanup_dead_clients()
                self.last_cleanup = now

            # Send buffered chunks to new client so they can catch up
            for chunk in self.buffer:
                try:
                    client_queue.put_nowait(chunk)
                except queue.Full:
                    # Skip old chunks if queue is full
                    logger.warning("Broadcaster: New client queue full while adding buffer")
                    pass

        return client_queue

    def _cleanup_dead_clients(self):
        """Remove client queues that are full (likely disconnected)."""
        initial_count = len(self.clients)

        # Remove queues that are full (client not consuming)
        self.clients = [q for q in self.clients if q.qsize() < q.maxsize]

        removed = initial_count - len(self.clients)
        if removed > 0:
            logger.info(f"Cleaned up {removed} dead client queue(s)")

    def unsubscribe(self, client_queue: queue.Queue[bytes]):
        """Unsubscribe a client from the stream."""
        with self.lock:
            if client_queue in self.clients:
                self.clients.remove(client_queue)
                # Clean up dropped chunks counter
                client_id = id(client_queue)
                if client_id in self.dropped_chunks_count:
                    del self.dropped_chunks_count[client_id]

    def stop(self):
        """Stop broadcasting."""
        self.active = False
        with self.lock:
            self.clients.clear()
            self.buffer.clear()
            self.dropped_chunks_count.clear()

    def is_active(self) -> bool:
        """Check if broadcaster is active."""
        return self.active
