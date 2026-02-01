"""
Path utilities for handling file paths with proper expansion.

Provides helper functions for expanding user paths (~) and resolving
symbolic links consistently across the codebase.
"""

from pathlib import Path
from typing import Union


def expand_path(path: Union[str, Path]) -> Path:
    """
    Expand user path (~) and resolve to absolute path.

    This function handles:
    - Tilde (~) expansion to home directory
    - Resolving symbolic links
    - Converting to absolute path

    Args:
        path: Path as string or Path object

    Returns:
        Fully expanded and resolved Path object

    Example:
        >>> expand_path("~/documents/file.txt")
        PosixPath('/home/user/documents/file.txt')
    """
    return Path(path).expanduser().resolve()


def expand_path_str(path: Union[str, Path]) -> str:
    """
    Expand user path (~) and resolve to absolute path string.

    Same as expand_path() but returns a string instead of Path object.
    Useful for external commands (ffmpeg, yt-dlp) that don't handle ~ paths.

    Args:
        path: Path as string or Path object

    Returns:
        Fully expanded and resolved path as string

    Example:
        >>> expand_path_str("~/documents/file.txt")
        '/home/user/documents/file.txt'
    """
    return str(expand_path(path))
