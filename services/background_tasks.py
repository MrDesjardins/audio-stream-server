"""Background task processing for audio transcription."""
import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import Enum
from queue import Queue, Empty
from typing import Optional, Dict

from services.cache import get_transcript_cache, get_audio_cache

logger = logging.getLogger(__name__)


class JobStatus(Enum):
    """Status of a transcription job."""
    PENDING = "pending"
    CHECKING_DEDUP = "checking_dedup"
    TRANSCRIBING = "transcribing"
    SUMMARIZING = "summarizing"
    POSTING = "posting"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"  # Skipped due to deduplication


@dataclass
class TranscriptionJob:
    """A transcription job to be processed."""
    video_id: str
    audio_path: str
    status: JobStatus = JobStatus.PENDING
    error: Optional[str] = None
    trilium_note_id: Optional[str] = None
    trilium_note_url: Optional[str] = None
    summary: Optional[str] = None
    transcript: Optional[str] = None


class TranscriptionQueue:
    """Thread-safe queue for transcription jobs."""

    def __init__(self):
        self.queue: Queue[TranscriptionJob] = Queue()
        self.jobs: Dict[str, TranscriptionJob] = {}
        self.lock = threading.Lock()

    def add_job(self, job: TranscriptionJob) -> None:
        """Add a job to the queue."""
        with self.lock:
            # Don't add if already in queue or completed
            if job.video_id in self.jobs:
                existing = self.jobs[job.video_id]
                if existing.status not in [JobStatus.FAILED, JobStatus.COMPLETED, JobStatus.SKIPPED]:
                    logger.info(f"Job for {job.video_id} already exists with status {existing.status}")
                    return

            self.jobs[job.video_id] = job
            self.queue.put(job)
            logger.info(f"Added transcription job for video {job.video_id}")

    def get_job(self, timeout: float = 1.0) -> Optional[TranscriptionJob]:
        """Get the next job from the queue (blocking with timeout)."""
        try:
            return self.queue.get(timeout=timeout)
        except Empty:
            return None

    def update_job_status(
        self,
        video_id: str,
        status: JobStatus,
        error: Optional[str] = None,
        trilium_note_id: Optional[str] = None,
        trilium_note_url: Optional[str] = None,
        summary: Optional[str] = None,
        transcript: Optional[str] = None
    ) -> None:
        """Update a job's status."""
        with self.lock:
            if video_id in self.jobs:
                job = self.jobs[video_id]
                job.status = status
                if error:
                    job.error = error
                if trilium_note_id:
                    job.trilium_note_id = trilium_note_id
                if trilium_note_url:
                    job.trilium_note_url = trilium_note_url
                if summary:
                    job.summary = summary
                if transcript:
                    job.transcript = transcript
                logger.info(f"Updated job {video_id} status to {status}")

    def get_job_status(self, video_id: str) -> Optional[TranscriptionJob]:
        """Get the status of a specific job."""
        with self.lock:
            return self.jobs.get(video_id)


class TranscriptionWorker:
    """Background worker that processes transcription jobs."""

    def __init__(self, queue: TranscriptionQueue):
        self.queue = queue
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self) -> None:
        """Start the worker thread."""
        if self.running:
            logger.warning("Worker already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.thread.start()
        logger.info("Transcription worker started")

    def stop(self) -> None:
        """Stop the worker thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5.0)
            logger.info("Transcription worker stopped")

    def _worker_loop(self) -> None:
        """Main worker loop."""
        from services.transcription import transcribe_audio
        from services.summarization import summarize_transcript
        from services.trilium import check_video_exists, create_trilium_note

        logger.info("Worker loop started")

        while self.running:
            job = self.queue.get_job(timeout=1.0)
            if job is None:
                continue

            try:
                self._process_job(job, check_video_exists, transcribe_audio, summarize_transcript, create_trilium_note)
            except Exception as e:
                logger.exception(f"Unexpected error processing job {job.video_id}")
                self.queue.update_job_status(
                    job.video_id,
                    JobStatus.FAILED,
                    error=f"Unexpected error: {str(e)}"
                )
            finally:
                # Clean up old audio files (keep max 10)
                audio_cache = get_audio_cache()
                audio_cache.cleanup_old_files()

        logger.info("Worker loop ended")

    def _process_job(self, job: TranscriptionJob, check_video_exists, transcribe_audio, summarize_transcript, create_trilium_note) -> None:
        """Process a single transcription job."""
        logger.info(f"Processing job for video {job.video_id}")
        cache = get_transcript_cache()
        cached_data = cache.get_cached(job.video_id)

        try:
            # Step 0: Wait for the audio file to be ready
            if not self._wait_for_file(job.audio_path, job.video_id):
                self.queue.update_job_status(
                    job.video_id,
                    JobStatus.FAILED,
                    error="Audio file download timeout or failed"
                )
                return

            # Step 1: Check if already exists in Trilium
            self.queue.update_job_status(job.video_id, JobStatus.CHECKING_DEDUP)
            existing_note = check_video_exists(job.video_id)
            if existing_note:
                logger.info(f"Video {job.video_id} already exists in Trilium: {existing_note['noteId']}")
                self.queue.update_job_status(
                    job.video_id,
                    JobStatus.SKIPPED,
                    trilium_note_id=existing_note["noteId"],
                    trilium_note_url=existing_note["url"]
                )
                return

            # Step 2: Transcribe audio (use cache if available)
            if cached_data and cached_data.get("transcript"):
                logger.info(f"Using cached transcript for video {job.video_id}")
                transcript = cached_data["transcript"]
            else:
                self.queue.update_job_status(job.video_id, JobStatus.TRANSCRIBING)
                transcript = transcribe_audio(job.audio_path, retries=3)
                cache.save_transcript(job.video_id, transcript)

            self.queue.update_job_status(job.video_id, JobStatus.TRANSCRIBING, transcript=transcript)

            # Step 3: Summarize transcript (use cache if available)
            if cached_data and cached_data.get("summary"):
                logger.info(f"Using cached summary for video {job.video_id}")
                summary = cached_data["summary"]
            else:
                self.queue.update_job_status(job.video_id, JobStatus.SUMMARIZING)
                summary = summarize_transcript(transcript, job.video_id)
                cache.save_summary(job.video_id, summary)

            self.queue.update_job_status(job.video_id, JobStatus.SUMMARIZING, summary=summary)

            # Step 4: Post to Trilium
            self.queue.update_job_status(job.video_id, JobStatus.POSTING)
            note_info = create_trilium_note(job.video_id, transcript, summary)

            # Step 5: Mark as completed
            self.queue.update_job_status(
                job.video_id,
                JobStatus.COMPLETED,
                trilium_note_id=note_info["noteId"],
                trilium_note_url=note_info["url"]
            )
            logger.info(f"Successfully completed job for video {job.video_id}")

        except Exception as e:
            logger.exception(f"Error processing job {job.video_id}")
            self.queue.update_job_status(
                job.video_id,
                JobStatus.FAILED,
                error=str(e)
            )

    def _wait_for_file(self, audio_path: str, video_id: str, timeout: int = 1800) -> bool:
        """
        Wait for the audio file to be fully downloaded and stable.

        Args:
            audio_path: Path to the audio file
            video_id: Video ID for logging
            timeout: Maximum seconds to wait (default: 30 minutes)

        Returns:
            True if file is ready, False if timeout or error
        """
        logger.info(f"Waiting for audio file to be ready: {audio_path}")
        start_time = time.time()
        last_size = 0
        stable_count = 0

        while time.time() - start_time < timeout:
            if not os.path.exists(audio_path):
                # File doesn't exist yet, wait a bit
                time.sleep(2)
                continue

            current_size = os.path.getsize(audio_path)

            if current_size == 0:
                # File exists but is empty, wait
                logger.debug(f"Audio file is empty, waiting... ({video_id})")
                time.sleep(2)
                continue

            if current_size == last_size:
                # Size hasn't changed, might be complete
                stable_count += 1
                if stable_count >= 3:  # Stable for 3 checks (6 seconds)
                    logger.info(f"Audio file is ready: {audio_path} ({current_size / 1024 / 1024:.2f} MB)")
                    return True
            else:
                # Still growing
                stable_count = 0
                logger.debug(f"Audio file growing: {current_size / 1024 / 1024:.2f} MB ({video_id})")

            last_size = current_size
            time.sleep(2)

        # Timeout
        logger.error(f"Timeout waiting for audio file: {audio_path}")
        return False



# Global queue and worker instances
transcription_queue: Optional[TranscriptionQueue] = None
transcription_worker: Optional[TranscriptionWorker] = None


def init_background_tasks() -> None:
    """Initialize the global background task system."""
    global transcription_queue, transcription_worker

    if transcription_queue is None:
        transcription_queue = TranscriptionQueue()
        transcription_worker = TranscriptionWorker(transcription_queue)
        transcription_worker.start()
        logger.info("Background task system initialized")


def get_transcription_queue() -> TranscriptionQueue:
    """Get the global transcription queue."""
    if transcription_queue is None:
        raise RuntimeError("Background task system not initialized")
    return transcription_queue
