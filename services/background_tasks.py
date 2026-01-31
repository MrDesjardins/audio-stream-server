"""Background task processing for audio transcription."""

import logging
import os
import threading
import time
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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
    completed_at: Optional[datetime] = (
        None  # Timestamp when job completed/failed/skipped
    )


class TranscriptionQueue:
    """Thread-safe queue for transcription jobs."""

    def __init__(self) -> None:
        self.queue: Queue[TranscriptionJob] = Queue()
        self.jobs: Dict[str, TranscriptionJob] = {}
        self.lock = threading.Lock()
        self.max_job_age_hours = 24  # Keep jobs for 24 hours

    def add_job(self, job: TranscriptionJob) -> bool:
        """
        Add a job to the queue with deduplication.

        Only blocks jobs that are currently active (PENDING, TRANSCRIBING, etc.).
        Completed/skipped jobs can be re-queued - they will be caught by the
        Trilium deduplication check during processing.

        Returns:
            True if job was added, False if it was a duplicate
        """
        # Validate job before adding
        if not job.video_id or not job.video_id.strip():
            logger.error("Rejected invalid job: video_id is empty or None")
            return False

        if (
            not job.audio_path
            or not job.audio_path.strip()
            or job.audio_path.endswith("/.mp3")
        ):
            logger.error(
                f"Rejected invalid job: audio_path is invalid: {job.audio_path}"
            )
            return False

        with self.lock:
            # Don't add if already in queue with active status
            if job.video_id in self.jobs:
                existing = self.jobs[job.video_id]
                if existing.status not in [
                    JobStatus.FAILED,
                    JobStatus.COMPLETED,
                    JobStatus.SKIPPED,
                ]:
                    logger.info(
                        f"Job deduplication: {job.video_id} already queued with status {existing.status}"
                    )
                    return False

            self.jobs[job.video_id] = job
            self.queue.put(job)
            logger.info(f"Added transcription job for video {job.video_id}")
            return True

    def should_skip_transcription(self, video_id: str) -> tuple[bool, str]:
        """
        Check if transcription should be skipped for this video.

        Only checks if already in queue with active status.
        Completed/skipped jobs are allowed to be re-queued - they will be
        caught by the Trilium deduplication check during processing.

        Returns:
            (should_skip, reason) tuple
        """
        with self.lock:
            # Check if already in queue with active status
            if video_id in self.jobs:
                existing = self.jobs[video_id]
                if existing.status not in [
                    JobStatus.FAILED,
                    JobStatus.COMPLETED,
                    JobStatus.SKIPPED,
                ]:
                    return (True, f"Already queued with status {existing.status}")

            return (False, "")

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
        transcript: Optional[str] = None,
    ) -> None:
        """Update a job's status."""
        with self.lock:
            if video_id in self.jobs:
                job = self.jobs[video_id]
                job.status = status

                # Set timestamp on completion
                if status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.SKIPPED]:
                    job.completed_at = datetime.now(timezone.utc)

                # Update other fields
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

        # Periodically clean up old jobs (10% chance)
        if random.random() < 0.1:
            self._cleanup_old_jobs()

    def _cleanup_old_jobs(self):
        """Remove jobs older than max_age."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=self.max_job_age_hours)

        with self.lock:
            to_remove = []
            for video_id, job in self.jobs.items():
                if job.completed_at and job.completed_at < cutoff:
                    to_remove.append(video_id)

            for video_id in to_remove:
                del self.jobs[video_id]

            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} old transcription job(s)")

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
                self._process_job(
                    job,
                    check_video_exists,
                    transcribe_audio,
                    summarize_transcript,
                    create_trilium_note,
                )
            except Exception as e:
                logger.exception(f"Unexpected error processing job {job.video_id}")
                self.queue.update_job_status(
                    job.video_id, JobStatus.FAILED, error=f"Unexpected error: {str(e)}"
                )
            finally:
                # Clean up old audio files asynchronously (non-blocking)
                self._cleanup_audio_async()

        logger.info("Worker loop ended")

    def _process_job(
        self,
        job: TranscriptionJob,
        check_video_exists,
        transcribe_audio,
        summarize_transcript,
        create_trilium_note,
    ) -> None:
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
                    error="Audio file download timeout or failed",
                )
                return

            # Step 1: Check if already exists in Trilium
            self.queue.update_job_status(job.video_id, JobStatus.CHECKING_DEDUP)
            existing_note = check_video_exists(job.video_id)
            if existing_note:
                logger.info(
                    f"Video {job.video_id} already exists in Trilium: {existing_note['noteId']}"
                )

                # Fetch the summary from Trilium for display
                from services.trilium import get_note_content
                import re

                summary = None
                try:
                    content = get_note_content(existing_note["noteId"])
                    if content:
                        # Extract summary from HTML content (same logic as /transcription/summary endpoint)
                        # Remove the YouTube link section at the bottom
                        content = re.sub(
                            r'<p style="margin-top.*?</p>', "", content, flags=re.DOTALL
                        )

                        # Convert HTML to text with line breaks
                        text_summary = re.sub(r"</p>", "\n\n", content)
                        text_summary = re.sub(r"</h[1-3]>", "\n\n", text_summary)
                        text_summary = re.sub(r"</li>", "\n", text_summary)
                        text_summary = re.sub(r"<ul>", "\n", text_summary)
                        text_summary = re.sub(r"</ul>", "\n", text_summary)
                        text_summary = re.sub(r"<[^>]+>", "", text_summary)
                        text_summary = re.sub(r"\n\s*\n\s*\n", "\n\n", text_summary)
                        summary = text_summary.strip()
                        logger.info(
                            f"Fetched summary from existing Trilium note for {job.video_id}"
                        )
                except Exception as e:
                    logger.warning(f"Failed to fetch summary from Trilium note: {e}")

                self.queue.update_job_status(
                    job.video_id,
                    JobStatus.SKIPPED,
                    trilium_note_id=existing_note["noteId"],
                    trilium_note_url=existing_note["url"],
                    summary=summary,
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

            self.queue.update_job_status(
                job.video_id, JobStatus.TRANSCRIBING, transcript=transcript
            )

            # Step 3: Summarize transcript (use cache if available)
            if cached_data and cached_data.get("summary"):
                logger.info(f"Using cached summary for video {job.video_id}")
                summary = cached_data["summary"]
            else:
                self.queue.update_job_status(job.video_id, JobStatus.SUMMARIZING)
                summary = summarize_transcript(transcript, job.video_id)
                cache.save_summary(job.video_id, summary)

            self.queue.update_job_status(
                job.video_id, JobStatus.SUMMARIZING, summary=summary
            )

            # Step 4: Post to Trilium
            self.queue.update_job_status(job.video_id, JobStatus.POSTING)
            note_info = create_trilium_note(job.video_id, transcript, summary)

            # Step 5: Mark as completed
            self.queue.update_job_status(
                job.video_id,
                JobStatus.COMPLETED,
                trilium_note_id=note_info["noteId"],
                trilium_note_url=note_info["url"],
            )
            logger.info(f"Successfully completed job for video {job.video_id}")

        except Exception as e:
            logger.exception(f"Error processing job {job.video_id}")
            self.queue.update_job_status(job.video_id, JobStatus.FAILED, error=str(e))

    def _cleanup_audio_async(self) -> None:
        """
        Asynchronously clean up old audio files without blocking the worker thread.

        Runs cleanup in a separate daemon thread to avoid blocking job processing.
        """

        def _do_cleanup():
            try:
                audio_cache = get_audio_cache()
                audio_cache.cleanup_old_files()
            except Exception as e:
                logger.error(f"Error in async audio cleanup: {e}")

        cleanup_thread = threading.Thread(
            target=_do_cleanup, daemon=True, name="AudioCleanup"
        )
        cleanup_thread.start()

    def _wait_for_file(
        self, audio_path: str, video_id: str, timeout: int = 300
    ) -> bool:
        """
        Wait for the audio file to be fully downloaded.

        Uses the .downloading marker file as the authoritative signal:
        the marker exists while yt-dlp is running, and is removed by
        finish_youtube_download() once the file is complete.

        Args:
            audio_path: Path to the audio file
            video_id: Video ID for logging
            timeout: Maximum seconds to wait (default: 5 minutes)

        Returns:
            True if file is ready, False if timeout or error
        """
        from services.streaming import is_download_in_progress

        # Validate inputs to fail fast on invalid jobs
        if not video_id or not video_id.strip():
            logger.error("Invalid job: video_id is empty or None")
            return False

        if not audio_path or not audio_path.strip() or audio_path.endswith("/.mp3"):
            logger.error(f"Invalid job: audio_path is invalid: {audio_path}")
            return False

        logger.info(f"Waiting for audio file to be ready: {audio_path}")
        start_time = time.time()

        while time.time() - start_time < timeout:
            file_exists = os.path.exists(audio_path)
            still_downloading = is_download_in_progress(video_id)

            if file_exists and not still_downloading:
                file_size = os.path.getsize(audio_path)
                if file_size > 0:
                    logger.info(
                        f"Audio file is ready: {audio_path} ({file_size / 1024 / 1024:.2f} MB)"
                    )
                    return True

            # Log periodic progress
            elapsed = time.time() - start_time
            if int(elapsed) % 10 == 0:
                status = (
                    "downloading"
                    if still_downloading
                    else "waiting for download to start"
                )
                logger.debug(
                    f"Audio file {video_id}: {status} ({elapsed:.0f}s elapsed)"
                )

            time.sleep(2)

        # Timeout — check if file exists at all for a better error message
        if os.path.exists(audio_path):
            logger.error(f"Timeout waiting for download to finish: {audio_path}")
        else:
            logger.error(f"Timeout — audio file never appeared: {audio_path}")
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
