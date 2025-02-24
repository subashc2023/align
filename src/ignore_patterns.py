"""Common ignore patterns and ignore checking logic."""

# Default patterns to always ignore, regardless of .gitignore
DEFAULT_IGNORES = {
    # Python
    "__pycache__",
    "__init__.py",
    ".pytest_cache",
    ".coverage",
    ".venv",
    "venv",
    "env",
    ".env",
    "*.pyc",
    "*.pyo",
    "*.pyd",
    
    # Node/JavaScript
    "node_modules",
    "package-lock.json",
    "yarn.lock",
    ".npm",
    
    # IDE/Editor
    ".idea",
    ".vscode",
    ".vs",
    "*.swp",
    ".DS_Store",
    "Thumbs.db",
    
    # Build/Dist
    "build",
    "dist",
    "*.egg-info",
    
    # Git
    ".git",
}

def should_ignore(entry_name, rel_path, gitignore_spec):
    """
    Check if a file or directory should be ignored.
    
    Args:
        entry_name: The name of the file or directory
        rel_path: The relative path from the root directory
        gitignore_spec: The PathSpec object for gitignore patterns
    
    Returns:
        bool: True if the entry should be ignored
    """
    # Check default ignores
    for pattern in DEFAULT_IGNORES:
        if pattern.startswith("*"):
            # Handle file extension patterns
            if entry_name.endswith(pattern[1:]):
                return True
        elif entry_name == pattern:
            return True
    
    # Check gitignore patterns
    if gitignore_spec.match_file(rel_path) or gitignore_spec.match_file(rel_path + '/'):
        return True
        
    return False 