"""Transcript summarization using ChatGPT or Gemini."""

import logging
from google import genai

from config import get_config
from services.api_clients import get_openai_client

logger = logging.getLogger(__name__)


SUMMARY_PROMPT_TEMPLATE = """You are summarizing a YouTube video transcript. Please provide:

1. A clear and informative title for the video (max 60 characters)
2. A concise 2-3 sentence overview of the main topic
3. If the audiobook covers 40 points, summarize the 40 points. If it covers 10 points, summarize the 10 points. If it is unclear use that heuristic: take the Key points discussed and focus on 5 to 10 bullet points depending of the number of topics/laws/concepts/ideas/points covered.
4. Any important conclusions or takeaways. A paragraph of about 3 to 5 sentences.

Keep the summary clear, well-structured, and informative.

Transcript:
{transcript}

Please provide the summary:"""


def summarize_transcript(transcript: str, video_id: str) -> str:
    """
    Summarize a transcript using the configured AI provider.

    Args:
        transcript: The transcript text to summarize
        video_id: The video ID (for logging purposes)

    Returns:
        The summary text

    Raises:
        Exception: If summarization fails
    """
    config = get_config()

    if config.summary_provider == "openai":
        return _summarize_with_openai(transcript, video_id)
    elif config.summary_provider == "gemini":
        return _summarize_with_gemini(transcript, video_id)
    else:
        raise ValueError(f"Unknown summary provider: {config.summary_provider}")


def _summarize_with_openai(transcript: str, video_id: str) -> str:
    """Summarize using OpenAI ChatGPT."""
    config = get_config()

    if not config.openai_api_key:
        raise ValueError("OpenAI API key not configured")

    logger.info(f"Summarizing transcript for video {video_id} using OpenAI")

    client = get_openai_client()

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",  # Using cost-effective model
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that creates clear, concise summaries of video transcripts.",
                },
                {"role": "user", "content": SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript)},
            ],
            temperature=0.7,
            max_tokens=1000,
        )

        summary = response.choices[0].message.content
        logger.info(
            f"Successfully generated summary using OpenAI ({0 if not summary else len(summary)} characters)"
        )
        return summary if summary else ""

    except Exception as e:
        logger.error(f"Failed to summarize with OpenAI: {e}")
        raise


def _summarize_with_gemini(transcript: str, video_id: str) -> str:
    """Summarize using Google Gemini."""
    config = get_config()

    if not config.gemini_api_key:
        raise ValueError("Gemini API key not configured")

    logger.info(f"Summarizing transcript for video {video_id} using Gemini")

    try:
        # Create client with API key
        client = genai.Client(api_key=config.gemini_api_key)

        prompt = SUMMARY_PROMPT_TEMPLATE.format(transcript=transcript)

        # Generate content using the new API
        response = client.models.generate_content(
            model="gemini-1.5-flash", contents=prompt  # Using cost-effective model
        )

        summary = response.text
        logger.info(
            f"Successfully generated summary using Gemini ({0 if not summary else len(summary)} characters)"
        )
        return summary if summary else ""

    except Exception as e:
        logger.error(f"Failed to summarize with Gemini: {e}")
        raise
