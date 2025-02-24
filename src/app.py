import os
import json
import dearpygui.dearpygui as dpg
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
from ignore_patterns import should_ignore
from markdown_generator import generate_markdown
from file_utils import is_binary_file, safe_count_lines, get_directory_size, format_size
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from datetime import datetime
import hashlib
from pathlib import Path
import logging
from enum import Enum
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class AlignError(Exception):
    """Base exception for Align application."""
    pass

class ConfigError(AlignError):
    """Configuration related errors."""
    pass

class RepoStatus(Enum):
    """Repository status indicators."""
    UPDATING = ("Currently updating", "\uf021", (255, 165, 0))  # Orange refresh
    UP_TO_DATE = ("Content is up to date", "\uf00c", (0, 255, 0))  # Green check
    NEEDS_UPDATE = ("Content needs updating", "\uf071", (255, 0, 0))  # Red warning
    
    def __init__(self, description: str, icon: str, color: tuple):
        self.description = description
        self.icon = icon
        self.color = color

class Config:
    """Configuration management class."""
    CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".align_config.json")
    
    @classmethod
    def load_repos(cls) -> List[str]:
        """Load tracked repositories from config file."""
        if os.path.exists(cls.CONFIG_PATH):
            try:
                with open(cls.CONFIG_PATH, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                raise ConfigError(f"Failed to load config: {e}")
        return []
    
    @classmethod
    def save_repos(cls, repos: List[str]) -> None:
        """Save tracked repositories to config file."""
        try:
            with open(cls.CONFIG_PATH, 'w') as f:
                json.dump(repos, f)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            raise ConfigError(f"Failed to save config: {e}")

# UI Constants
UI_CONSTANTS = {
    'WINDOW_WIDTH': 800,
    'WINDOW_HEIGHT': 600,
    'BUTTON_WIDTH': 120,
    'PREVIEW_WIDTH': 600,
    'PREVIEW_HEIGHT': 600,
    'REFRESH_COOLDOWN': 1.0,  # seconds
}

def load_gitignore(directory):
    """Load and parse .gitignore file."""
    gitignore_path = os.path.join(directory, '.gitignore')
    patterns = []
    
    try:
        if os.path.exists(gitignore_path):
            with open(gitignore_path, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        # Handle patterns with trailing slashes
                        if line.endswith('/'):
                            line = line[:-1]  # Remove trailing slash
                        # Add both with and without '**/' prefix for nested matching
                        patterns.append(line)
                        if not line.startswith('**/'):
                            patterns.append(f"**/{line}")
    except Exception as e:
        logger.warning(f"Error reading .gitignore: {e}")
    
    return PathSpec.from_lines(GitWildMatchPattern, patterns)

def load_align_content(path):
    """Load the content of Align.md from a repository."""
    align_file_path = os.path.join(path, "Align.md")
    try:
        with open(align_file_path, "r", encoding='utf-8', errors='replace') as f:
            return f.read()
    except Exception as e:
        logger.warning(f"Error reading Align.md: {e}")
        return "No Align.md file found"

def view_repo(sender, app_data, user_data):
    """Show the Align.md content in a new window."""
    try:
        content = load_align_content(user_data)
        
        # Create a unique tag for this window
        window_tag = f"preview_window_{hash(user_data)}"
        
        # Close existing window if it exists
        if dpg.does_item_exist(window_tag):
            dpg.delete_item(window_tag)
        
        # Create new window
        with dpg.window(
            label=f"Preview: {os.path.basename(user_data)}",
            width=600,
            height=600,
            pos=[100, 100],
            tag=window_tag
        ):
            dpg.add_input_text(
                default_value=content,
                width=-1,
                height=-1,
                multiline=True,
                readonly=True,
                wrap=0,
                tag=f"preview_text_{window_tag}"
            )
    except Exception as e:
        print(f"Error showing preview for {user_data}: {e}")

def format_time_ago(timestamp):
    """Format timestamp as relative time."""
    minutes_ago = int((time.time() - timestamp) / 60)
    
    if minutes_ago == 0:
        return "just now"
    elif minutes_ago == 1:
        return "1 minute ago"
    elif minutes_ago < 60:
        return f"{minutes_ago} minutes ago"
    
    hours_ago = minutes_ago // 60
    if hours_ago == 1:
        return "1 hour ago"
    elif hours_ago < 24:
        return f"{hours_ago} hours ago"
    
    days_ago = hours_ago // 24
    if days_ago == 1:
        return "1 day ago"
    return f"{days_ago} days ago"

def calculate_repo_hash(directory):
    """Calculate a hash of the repository content."""
    sha256_hash = hashlib.sha256()
    
    # Load gitignore patterns
    gitignore_spec = load_gitignore(directory)
    
    # Get all files sorted by path for consistent hashing
    files = []
    skipped_files = []
    binary_files = []
    
    for path in Path(directory).rglob('*'):
        if path.is_file():
            try:
                rel_path = str(path.relative_to(directory))
                # Skip Align.md and ignored files
                if rel_path == 'Align.md' or should_ignore(path.name, rel_path, gitignore_spec):
                    continue
                
                # Track binary files separately
                if is_binary_file(path):
                    binary_files.append(path)
                
                files.append((rel_path, path))
            except Exception as e:
                logger.warning(f"Error processing path {path}: {e}")
                skipped_files.append(path)
    
    # Sort files by relative path
    files.sort(key=lambda x: x[0])
    
    # Update hash with file contents
    processed_files = 0
    for rel_path, path in files:
        try:
            # Add path and content to hash
            sha256_hash.update(rel_path.encode())
            # Read file in binary mode
            sha256_hash.update(path.read_bytes())
            processed_files += 1
        except Exception as e:
            # Log error but continue processing other files
            logger.warning(f"Error reading file {path}: {e}")
            skipped_files.append(path)
    
    if skipped_files:
        logger.info(f"Processed {processed_files} files, skipped {len(skipped_files)} files")
        logger.debug(f"Skipped files: {', '.join(str(f) for f in skipped_files)}")
    
    if binary_files:
        logger.debug(f"Found {len(binary_files)} binary files: {', '.join(str(f) for f in binary_files)}")
    
    return sha256_hash.hexdigest()

class RepoChangeHandler(FileSystemEventHandler):
    """Handler for file system changes in repositories."""
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.last_refresh = 0
        self.refresh_cooldown = UI_CONSTANTS['REFRESH_COOLDOWN']
        self.is_refreshing = False
        try:
            self.current_hash = calculate_repo_hash(repo_path)
            self.saved_hash = self.load_saved_hash()
            logger.info(f"Initialized handler for {repo_path} with hash {self.current_hash[:8]}")
        except Exception as e:
            logger.error(f"Error initializing handler for {repo_path}: {e}")
            raise AlignError(f"Failed to initialize repository handler: {e}")

    def load_saved_hash(self) -> Optional[str]:
        """Load the saved hash from Align.md if it exists."""
        align_path = os.path.join(self.repo_path, "Align.md")
        try:
            with open(align_path, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if first_line.startswith("<!-- Hash: "):
                    hash_value = first_line[10:-3]
                    logger.debug(f"Loaded saved hash {hash_value[:8]} from {align_path}")
                    return hash_value
        except Exception as e:
            logger.warning(f"Could not load saved hash from {align_path}: {e}")
        return None

    def update_saved_hash(self) -> None:
        """Update the saved hash in Align.md."""
        old_hash = self.saved_hash and self.saved_hash[:8]
        self.saved_hash = self.current_hash
        logger.debug(f"Updated saved hash from {old_hash} to {self.current_hash[:8]}")

    def on_any_event(self, event) -> None:
        """Handle any file system event."""
        # Skip temporary files and Align.md itself
        if event.src_path.endswith('Align.md') or event.src_path.endswith('.tmp'):
            logger.debug(f"Ignoring event for {event.src_path}")
            return

        # Implement cooldown to prevent rapid successive refreshes
        current_time = time.time()
        time_since_last = current_time - self.last_refresh
        if time_since_last < self.refresh_cooldown:
            logger.debug(f"Skipping refresh, only {time_since_last:.1f}s since last refresh")
            return

        try:
            logger.info(f"Processing {event.event_type} event for {event.src_path}")
            self.last_refresh = current_time
            self.is_refreshing = True
            update_repo_list()  # Update UI to show refreshing status
            
            refresh_repo(None, None, self.repo_path, show_preview=False)
            
            self.is_refreshing = False
            update_repo_list()  # Update UI to show new status
            logger.info(f"Completed processing {event.event_type} event")
        except Exception as e:
            logger.error(f"Error handling file system event in {self.repo_path}: {e}", exc_info=True)
            self.is_refreshing = False
            update_repo_list()

class RepoWatcher:
    """Manages file system observers for all repositories."""
    def __init__(self):
        self.observers = {}

    def watch_repo(self, repo_path):
        if repo_path in self.observers:
            return

        event_handler = RepoChangeHandler(repo_path)
        observer = Observer()
        observer.schedule(event_handler, repo_path, recursive=True)
        observer.start()
        # Store both observer and handler for status tracking
        self.observers[repo_path] = type('Observer', (), {
            'observer': observer,
            'event_handler': event_handler
        })

    def unwatch_repo(self, repo_path):
        if repo_path in self.observers:
            self.observers[repo_path].observer.stop()
            self.observers[repo_path].observer.join()
            del self.observers[repo_path]

    def stop_all(self):
        for obs in self.observers.values():
            obs.observer.stop()
        for obs in self.observers.values():
            obs.observer.join()
        self.observers.clear()

# Create global watcher instance
repo_watcher = RepoWatcher()

def add_repository(sender, app_data, user_data):
    """Callback for when a new repository is selected."""
    folder_path = app_data.get("file_path_name", None)
    if not folder_path:
        return

    try:
        repos = Config.load_repos()
        if folder_path not in repos:
            repos.append(folder_path)
            Config.save_repos(repos)
            
            # Generate initial Align.md without preview
            refresh_repo(None, None, folder_path, show_preview=False)
            # Start watching the new repository
            repo_watcher.watch_repo(folder_path)
            # Recreate the repository list
            create_repo_list()
    except ConfigError as e:
        logger.error(f"Failed to add repository: {e}")
        dpg.configure_item("status_text", default_value=f"Error: {str(e)}")

def remove_repository(sender, app_data, user_data):
    """Remove a repository from tracking."""
    repo_path = user_data
    try:
        repos = Config.load_repos()
        if repo_path in repos:
            repos.remove(repo_path)
            Config.save_repos(repos)
            # Stop watching the repository
            repo_watcher.unwatch_repo(repo_path)
            # Recreate the repository list
            create_repo_list()
    except ConfigError as e:
        logger.error(f"Failed to remove repository: {e}")
        dpg.configure_item("status_text", default_value=f"Error: {str(e)}")

def refresh_repo(sender=None, app_data=None, user_data=None, show_preview=False):
    """Refresh the Align.md file for a specific repository."""
    path = user_data  # Get the path from user_data
    if not path or not os.path.exists(path):
        logger.warning(f"Invalid repository path: {path}")
        return False

    logger.info(f"Starting refresh for repository: {path}")
    try:
        gitignore_spec = load_gitignore(path)
        
        # Calculate new hash
        logger.debug(f"Calculating hash for {path}")
        new_hash = calculate_repo_hash(path)
        
        # Check if content actually changed
        handler = repo_watcher.observers.get(path) and repo_watcher.observers[path].event_handler
        if handler and handler.current_hash == new_hash and handler.current_hash == handler.saved_hash:
            logger.info(f"No changes detected for {path}, skipping refresh")
            return True
        
        # Generate markdown with hash
        logger.debug(f"Generating markdown for {path}")
        markdown_content = f"<!-- Hash: {new_hash} -->\n" + generate_markdown(path, gitignore_spec)
        
        align_file_path = os.path.join(path, "Align.md")
        with open(align_file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Updated Align.md at {align_file_path}")
        
        # Update handler's hashes
        if handler:
            logger.debug(f"Updating handler hashes for {path}")
            handler.current_hash = new_hash
            handler.update_saved_hash()
        
        # Only show preview if explicitly requested
        if show_preview:
            try:
                view_repo(None, None, path)
            except Exception as e:
                logger.error(f"Error showing preview for {path}: {e}")
        
        return True
    except Exception as e:
        logger.error(f"Error refreshing repository {path}: {e}", exc_info=True)
        dpg.configure_item("status_text", default_value=f"Error refreshing {os.path.basename(path)}")
        return False

def refresh_all_repos(sender=None, app_data=None, user_data=None):
    """Refresh all tracked repositories."""
    try:
        repos = Config.load_repos()
        logger.info(f"Starting refresh of {len(repos)} repositories")
        
        # Track which repos have been processed to avoid duplicates
        processed_repos = set()
        
        # Mark all repos as refreshing
        for repo in repos:
            if repo in processed_repos:
                logger.warning(f"Skipping duplicate repository: {repo}")
                continue
                
            if repo in repo_watcher.observers:
                repo_watcher.observers[repo].event_handler.is_refreshing = True
            processed_repos.add(repo)
            
        update_repo_list()  # Initial UI update to show all repos refreshing
        
        # Refresh all repos
        total_repos = len(repos)
        successful_refreshes = 0
        
        for i, repo in enumerate(repos, 1):
            if repo in processed_repos:
                logger.info(f"Processing repository {i}/{total_repos}: {repo}")
                
                if refresh_repo(None, None, repo, show_preview=False):
                    successful_refreshes += 1
                
                # Update is_refreshing status after each repo
                if repo in repo_watcher.observers:
                    handler = repo_watcher.observers[repo].event_handler
                    handler.is_refreshing = False
                    # Update current hash and refresh time
                    handler.current_hash = calculate_repo_hash(repo)
                    handler.last_refresh = time.time()
                
                # Only update UI every few repos or on the last one
                if i == total_repos or i % 3 == 0:
                    update_repo_list()  # Update UI less frequently
        
        # Final UI update and status message
        update_repo_list()
        status_msg = f"Refreshed {successful_refreshes}/{total_repos} repositories"
        logger.info(status_msg)
        dpg.configure_item("status_text", default_value=status_msg)
        
    except Exception as e:
        error_msg = f"Error during refresh all: {str(e)}"
        logger.error(error_msg, exc_info=True)
        dpg.configure_item("status_text", default_value=error_msg)

def setup_icons():
    """Setup font awesome icons"""
    with dpg.font_registry():
        try:
            # Load from fonts directory
            font_path = os.path.join(os.path.dirname(__file__), "fonts", "fa-solid-900.ttf")
            if os.path.exists(font_path):
                with dpg.font(font_path, 13) as font:
                    dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                    dpg.add_font_range(0xf000, 0xf999)  # Font Awesome range
                logger.info("Successfully loaded Font Awesome icons")
                return font
            else:
                logger.warning(f"Font file not found at {font_path}")
                return None
        except Exception as e:
            logger.error(f"Could not load icons: {e}", exc_info=True)
            return None

def create_repo_list():
    """Create the initial repository list."""
    repos = Config.load_repos()
    
    # Clear existing items
    dpg.delete_item("repo_list", children_only=True)
    
    for repo in repos:
        # Create a group for this repo with a unique tag
        group_tag = f"repo_group_{hash(repo)}"
        with dpg.group(parent="repo_list", horizontal=True, tag=group_tag):
            # Status indicator with tooltip
            status_tag = f"status_{hash(repo)}"
            dpg.add_text("\uf111", color=(128, 128, 128), tag=status_tag)  # fa-circle
            dpg.bind_item_font(dpg.last_item(), icon_font)
            
            # Add tooltip with tag
            tooltip_tag = f"tooltip_{hash(repo)}"
            with dpg.tooltip(status_tag, tag=tooltip_tag):
                dpg.add_text("Loading status...", tag=f"tooltip_text_{hash(repo)}")
            
            # Add buttons with icons
            dpg.add_button(
                label="\uf2ed",  # trash icon
                callback=remove_repository,
                user_data=repo,
                width=30
            )
            dpg.bind_item_font(dpg.last_item(), icon_font)
            
            dpg.add_button(
                label="\uf06e",  # eye icon
                callback=view_repo,
                user_data=repo,
                width=30
            )
            dpg.bind_item_font(dpg.last_item(), icon_font)
            
            dpg.add_spacer(width=10)
            dpg.add_text(repo, wrap=0)
            
            # Add timestamp text with tag
            time_tag = f"time_{hash(repo)}"
            dpg.add_text("", tag=time_tag, color=(128, 128, 128))

def update_repo_list():
    """Update only the status indicators and timestamps."""
    try:
        repos = Config.load_repos()
        
        for repo in repos:
            status_tag = f"status_{hash(repo)}"
            tooltip_tag = f"tooltip_{hash(repo)}"
            time_tag = f"time_{hash(repo)}"
            
            if not dpg.does_item_exist(status_tag):
                continue
                
            # Get handler for this repo
            handler = repo_watcher.observers.get(repo) and repo_watcher.observers[repo].event_handler
            
            # Update current hash
            if handler:
                handler.current_hash = calculate_repo_hash(repo)
            
            # Update status indicator
            status = None
            if handler and handler.is_refreshing:
                status = RepoStatus.UPDATING
            elif handler and handler.current_hash == handler.saved_hash:
                status = RepoStatus.UP_TO_DATE
            else:
                status = RepoStatus.NEEDS_UPDATE
            
            dpg.configure_item(status_tag, default_value=status.icon, color=status.color)
            
            # Update tooltip text
            tooltip_text = ("Status Indicator\n\n"
                        "✓ Check: Content is up to date\n"
                        "↻ Refresh: Currently updating\n"
                        "⚠ Warning: Content needs updating\n\n"
                        f"Current Status: {status.description}")
            
            tooltip_text_tag = f"tooltip_text_{hash(repo)}"
            if dpg.does_item_exist(tooltip_text_tag):
                dpg.configure_item(tooltip_text_tag, default_value=tooltip_text)
            
            # Update timestamp
            if handler and handler.last_refresh:
                time_ago = format_time_ago(handler.last_refresh)
                dpg.configure_item(time_tag, default_value=f"(Updated: {time_ago})")
    except ConfigError as e:
        logger.error(f"Failed to update repository list: {e}")
        dpg.configure_item("status_text", default_value=f"Error: {str(e)}")

def main():
    """Initialize and run the Dear PyGUI application."""
    dpg.create_context()
    
    # Setup icons first and make icon_font global
    global icon_font
    icon_font = setup_icons()
    
    # Create file dialog for directory selection
    with dpg.file_dialog(
        directory_selector=True, 
        show=False, 
        callback=add_repository, 
        id="file_dialog",
        width=700,
        height=500,
        modal=True,
        default_path=os.path.expanduser("~"),
        label="Select Repository Directory",
        tag="file_dialog_tag"
    ):
        # Add informative text and help
        with dpg.group(horizontal=True):
            dpg.add_text("📁")  # Folder emoji
            dpg.add_text("Select a repository directory to track")
        
        # Add quick access buttons for common locations
        with dpg.group(horizontal=True):
            dpg.add_button(label="Home", callback=lambda: dpg.set_value("file_dialog_tag", os.path.expanduser("~")))
            dpg.add_button(label="Desktop", callback=lambda: dpg.set_value("file_dialog_tag", os.path.join(os.path.expanduser("~"), "Desktop")))
            dpg.add_button(label="Documents", callback=lambda: dpg.set_value("file_dialog_tag", os.path.join(os.path.expanduser("~"), "Documents")))
        
        dpg.add_separator()
        
        # Add file type filters
        with dpg.group():
            dpg.add_checkbox(label="Show Hidden Files", callback=lambda sender, app_data: dpg.configure_item("file_dialog_tag", show_hidden=app_data))
            dpg.add_checkbox(label="Show Only Directories", default_value=True, enabled=False)
        
        dpg.add_separator()
        
        # Add help text at the bottom
        with dpg.group():
            dpg.add_text("Tips:", color=(255, 255, 0))
            dpg.add_text("• Double-click a folder to open it")
            dpg.add_text("• Press Enter to select current directory")
            dpg.add_text("• Use backspace to go up one level")

    # Create main application window
    with dpg.window(
        label="Align - Repository Tracker",
        width=UI_CONSTANTS['WINDOW_WIDTH'],
        height=UI_CONSTANTS['WINDOW_HEIGHT'],
        tag="primary_window"
    ):
        # Create main content
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Add Repository",
                callback=lambda: dpg.show_item("file_dialog"),
                width=UI_CONSTANTS['BUTTON_WIDTH']
            )
            dpg.add_button(
                label="Refresh All",
                callback=refresh_all_repos,
                width=UI_CONSTANTS['BUTTON_WIDTH']
            )
        
        dpg.add_separator()
        dpg.add_text("Tracked Repositories:")
        
        # Create a child window for scrolling repository list
        with dpg.child_window(height=-1, width=-1, tag="repo_list"):
            pass  # Content will be populated by update_repo_list()
        
        # Add status bar at bottom
        dpg.add_separator()
        dpg.add_text("Ready", tag="status_text")

    # Setup viewport and start the application
    dpg.create_viewport(
        title="Align",
        width=UI_CONSTANTS['WINDOW_WIDTH'],
        height=UI_CONSTANTS['WINDOW_HEIGHT']
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("primary_window", True)
    
    try:
        # Load and display tracked repositories
        repos = Config.load_repos()
        for repo in repos:
            repo_watcher.watch_repo(repo)
        create_repo_list()  # Create initial list
        
        dpg.start_dearpygui()
    except Exception as e:
        logger.error(f"Application error: {e}")
        raise
    finally:
        repo_watcher.stop_all()
        dpg.destroy_context()

if __name__ == "__main__":
    main()
