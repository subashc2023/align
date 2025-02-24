"""Module for generating markdown content for repository structure."""

import os
import logging
from ignore_patterns import should_ignore
from file_utils import safe_count_lines, get_directory_size, format_size

logger = logging.getLogger(__name__)

def generate_markdown(directory, gitignore_spec):
    """Generate a markdown representation of the directory structure with line counts."""
    markdown_lines = []
    total_lines = 0
    
    # First pass to collect all entries and find max width needed
    all_entries = []
    max_indent_level = 0
    
    def collect_entries(current_path, indent_level=0):
        nonlocal max_indent_level
        max_indent_level = max(max_indent_level, indent_level)
        try:
            entries = os.listdir(current_path)
            dirs = []
            files = []
            
            for entry in entries:
                full_path = os.path.join(current_path, entry)
                rel_path = os.path.relpath(full_path, directory)
                
                if should_ignore(entry, rel_path, gitignore_spec):
                    continue
                
                if os.path.isdir(full_path):
                    dirs.append((entry, full_path, indent_level))
                else:
                    files.append((entry, full_path, indent_level))
            
            # Add directories first
            for entry, full_path, level in sorted(dirs):
                indent = "    " * level
                all_entries.append((entry, full_path, indent, level, True))
                collect_entries(full_path, level + 1)
            
            # Then add files
            for entry, full_path, level in sorted(files):
                indent = "    " * level
                all_entries.append((entry, full_path, indent, level, False))
                
        except Exception as e:
            logger.warning(f"Error listing {current_path}: {e}")
    
    # Collect all entries
    collect_entries(directory)
    
    # Calculate the maximum width needed for alignment
    # Base width + maximum possible indentation
    max_width = 50 + (max_indent_level * 4)
    
    # Generate the markdown with aligned stats
    for entry, full_path, indent, level, is_dir in all_entries:
        if is_dir:
            markdown_lines.append(f"{indent}- **{entry}/**")
        else:
            # Get line count and size
            loc = safe_count_lines(full_path)
            total_lines += loc
            line_suffix = "line" if loc == 1 else "lines"
            
            try:
                size = os.path.getsize(full_path)
                size_str = format_size(size)
            except:
                size_str = "0 B"
            
            # Right align the stats with consistent spacing
            stats = f"`[{loc} {line_suffix}, {size_str}]`"
            # Calculate padding based on entry length and current indent level
            current_width = len(indent) + 2 + len(entry)  # 2 for "- "
            padding = " " * (max_width - current_width)
            
            markdown_lines.append(
                f"{indent}- {entry}{padding}{stats}"
            )
    
    # Get project details
    project_name = os.path.basename(os.path.abspath(directory))
    project_path = os.path.abspath(directory)
    project_size = format_size(get_directory_size(directory))
    
    # Create header with project details
    header = [
        "# Project Details",
        "",
        f"Name : {project_name}",
        f"path : {project_path}",
        f"size : {project_size}",
        f"lines : {total_lines}",
        "",
        "## Directory Structure",
        ""
    ]
    
    return "\n".join(header + markdown_lines) 