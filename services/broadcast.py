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
        self.dropped_chunks_count = {}  # Track dropped chunks per client for rate-limited logging

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
        import time
        try:
            logger.info("Broadcaster: Starting to read from process")
            while self.active:
                # Read available data (use read1 to avoid blocking for full chunk_size)
                try:
                    # read1() reads at least 1 byte up to chunk_size without blocking for full size
                    if hasattr(process.stdout, 'read1'):
                        chunk = process.stdout.read1(chunk_size)
                    else:
                        # Fallback to regular read
                        chunk = process.stdout.read(chunk_size)
                except Exception as e:
                    logger.error(f"Broadcaster: Error reading from process: {e}")
                    break

                if not chunk:
                    # read1() can return empty bytes when no data is available yet
                    # Only break if the process has actually finished
                    poll_result = process.poll()
                    if poll_result is not None:
                        logger.info(f"Broadcaster: Process ended with code {poll_result}, no more data")
                        break
                    # Process still running, just no data available right now
                    # Sleep briefly and continue
                    time.sleep(0.01)
                    continue

                with self.lock:
                    # Add to buffer for late-joining clients
                    self.buffer.append(chunk)

                    # Send to all connected clients (thread-safe)
                    dropped_clients = []
                    for client_queue in self.clients[:]:
                        try:
                            # Use put with timeout instead of put_nowait
                            # This gives slow clients a chance to catch up
                            client_queue.put(chunk, timeout=0.5)

                            # Reset dropped chunks counter on successful delivery
                            if id(client_queue) in self.dropped_chunks_count:
                                del self.dropped_chunks_count[id(client_queue)]

                        except queue.Full:
                            # Client queue is full even after timeout
                            # Track dropped chunks and only log periodically to avoid spam
                            client_id = id(client_queue)
                            self.dropped_chunks_count[client_id] = self.dropped_chunks_count.get(client_id, 0) + 1

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

    def subscribe(self) -> queue.Queue:
        """Subscribe a new client to the stream."""
        # Increase queue size to prevent dropping chunks for slow clients
        # 200 chunks * 8KB = ~1.6MB buffer per client
        client_queue = queue.Queue(maxsize=200)

        with self.lock:
            self.clients.append(client_queue)
            logger.info(f"Broadcaster: New client subscribed (total clients: {len(self.clients)})")

            # Send buffered chunks to new client so they can catch up
            for chunk in self.buffer:
                try:
                    client_queue.put_nowait(chunk)
                except queue.Full:
                    # Skip old chunks if queue is full
                    logger.warning("Broadcaster: New client queue full while adding buffer")
                    pass

        return client_queue

    def unsubscribe(self, client_queue: queue.Queue):
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
