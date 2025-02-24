"""Utility functions for file operations."""

import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

def is_binary_file(file_path: Path) -> bool:
    """Check if a file is binary by reading its first few bytes."""
    try:
        chunk_size = 8192  # Read first 8KB
        with open(file_path, 'rb') as f:
            chunk = f.read(chunk_size)
            # Check for NULL bytes or other binary indicators
            return b'\x00' in chunk or b'\xff' in chunk
    except Exception:
        return True  # Assume binary if we can't read it

def safe_count_lines(file_path: str) -> int:
    """Safely count lines in a file, returning 0 for binary files."""
    try:
        # Skip binary files
        if is_binary_file(Path(file_path)):
            logger.debug(f"Skipping line count for binary file: {file_path}")
            return 0
            
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            return sum(1 for _ in f)
    except Exception as e:
        logger.warning(f"Error counting lines in {file_path}: {e}")
        return 0

def get_directory_size(directory: str) -> int:
    """Calculate total size of a directory in bytes."""
    total_size = 0
    for dirpath, _, filenames in os.walk(directory):
        for filename in filenames:
            file_path = os.path.join(dirpath, filename)
            try:
                total_size += os.path.getsize(file_path)
            except (OSError, FileNotFoundError):
                continue
    return total_size

def format_size(size_in_bytes: float) -> str:
    """Convert bytes to human readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_in_bytes < 1024:
            return f"{size_in_bytes:.1f} {unit}"
        size_in_bytes /= 1024
    return f"{size_in_bytes:.1f} TB" 