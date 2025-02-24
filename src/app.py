"""Align application - Repository structure documentation tool."""

import os
import json
import time
import logging
import hashlib
from datetime import datetime
from enum import Enum
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

import dearpygui.dearpygui as dpg
from pathspec import PathSpec
from pathspec.patterns import GitWildMatchPattern
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# ---------- File Utilities ----------
def is_binary_file(file_path: Path) -> bool:
    """Check if a file is binary by reading its first few bytes."""
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(8192)  # 8KB
            return b"\x00" in chunk or b"\xff" in chunk
    except Exception:
        return True  # Assume binary on error


def safe_count_lines(file_path: str) -> int:
    """Safely count lines in a text file (0 for binary files)."""
    if is_binary_file(Path(file_path)):
        logger.debug(f"Skipping line count for binary file: {file_path}")
        return 0
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            return sum(1 for _ in f)
    except Exception as e:
        logger.warning(f"Error counting lines in {file_path}: {e}")
        return 0


def get_directory_size(directory: str) -> int:
    """Calculate total size (in bytes) of a directory."""
    total = 0
    for dirpath, _, filenames in os.walk(directory):
        for filename in filenames:
            try:
                total += os.path.getsize(os.path.join(dirpath, filename))
            except (OSError, FileNotFoundError):
                continue
    return total


def format_size(size_in_bytes: float) -> str:
    """Convert bytes to a human-readable string."""
    for unit in ["B", "KB", "MB", "GB"]:
        if size_in_bytes < 1024:
            return f"{size_in_bytes:.1f} {unit}"
        size_in_bytes /= 1024
    return f"{size_in_bytes:.1f} TB"


# ---------- Ignore Patterns ----------
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


def should_ignore(entry_name: str, rel_path: str, gitignore_spec: PathSpec) -> bool:
    """Determine if an entry should be ignored based on defaults and .gitignore."""
    if any(entry_name.endswith(p[1:]) for p in DEFAULT_IGNORES if p.startswith("*")):
        return True
    if entry_name in DEFAULT_IGNORES:
        return True
    return bool(gitignore_spec.match_file(rel_path) or gitignore_spec.match_file(rel_path + "/"))


# ---------- Configuration ----------
@dataclass
class UIConfig:
    WINDOW_WIDTH: int = 800
    WINDOW_HEIGHT: int = 600
    BUTTON_WIDTH: int = 120
    PREVIEW_WIDTH: int = 600
    PREVIEW_HEIGHT: int = 600
    REFRESH_COOLDOWN: float = 1.0  # seconds
    FILE_DIALOG_WIDTH: int = 700
    FILE_DIALOG_HEIGHT: int = 500


class ConfigError(Exception):
    pass


class Config:
    def __init__(self):
        self.config_path = os.path.join(os.path.expanduser("~"), ".align_config.json")
        self.ui = UIConfig()
        self._load_env_vars()

    def _load_env_vars(self) -> None:
        env_prefix = "ALIGN_"
        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                config_key = key[len(env_prefix):].lower()
                if hasattr(self.ui, config_key.upper()):
                    try:
                        attr_type = type(getattr(self.ui, config_key.upper()))
                        setattr(self.ui, config_key.upper(), attr_type(value))
                    except ValueError as e:
                        logger.warning(f"Invalid environment variable {key}: {e}")

    def load_repos(self) -> List[str]:
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                raise ConfigError(f"Failed to load config: {e}")
        return []

    def save_repos(self, repos: List[str]) -> None:
        try:
            with open(self.config_path, "w") as f:
                json.dump(repos, f)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            raise ConfigError(f"Failed to save config: {e}")

    def get_ui_constants(self) -> Dict[str, Any]:
        return asdict(self.ui)


config = Config()


# ---------- Markdown Generator ----------
def generate_markdown(directory: str, gitignore_spec: PathSpec) -> str:
    """Generate a markdown overview of the directory structure including stats."""
    markdown_lines = []
    total_lines = 0
    all_entries = []
    max_indent_level = 0

    def collect_entries(current_path: str, level: int = 0):
        nonlocal max_indent_level
        max_indent_level = max(max_indent_level, level)
        try:
            entries = os.listdir(current_path)
            dirs, files = [], []
            for entry in entries:
                full_path = os.path.join(current_path, entry)
                rel_path = os.path.relpath(full_path, directory)
                if should_ignore(entry, rel_path, gitignore_spec):
                    continue
                if os.path.isdir(full_path):
                    dirs.append((entry, full_path, level))
                else:
                    files.append((entry, full_path, level))
            for entry, full_path, lvl in sorted(dirs):
                indent = "    " * lvl
                all_entries.append((entry, full_path, indent, lvl, True))
                collect_entries(full_path, lvl + 1)
            for entry, full_path, lvl in sorted(files):
                indent = "    " * lvl
                all_entries.append((entry, full_path, indent, lvl, False))
        except Exception as e:
            logger.warning(f"Error listing {current_path}: {e}")

    collect_entries(directory)
    max_width = 50 + (max_indent_level * 4)

    for entry, full_path, indent, level, is_dir in all_entries:
        if is_dir:
            markdown_lines.append(f"{indent}- **{entry}/**")
        else:
            loc = safe_count_lines(full_path)
            total_lines += loc
            line_suffix = "line" if loc == 1 else "lines"
            try:
                size_str = format_size(os.path.getsize(full_path))
            except Exception:
                size_str = "0 B"
            stats = f"`[{loc} {line_suffix}, {size_str}]`"
            padding = " " * (max_width - (len(indent) + 2 + len(entry)))
            markdown_lines.append(f"{indent}- {entry}{padding}{stats}")

    project_name = os.path.basename(os.path.abspath(directory))
    project_path = os.path.abspath(directory)
    project_size = format_size(get_directory_size(directory))
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


# ---------- Repository Utilities ----------
class AlignError(Exception):
    pass


class RepoStatus(Enum):
    UPDATING = ("Currently updating", "\uf021", (255, 165, 0))
    UP_TO_DATE = ("Content is up to date", "\uf00c", (0, 255, 0))
    NEEDS_UPDATE = ("Content needs updating", "\uf071", (255, 0, 0))

    def __init__(self, description: str, icon: str, color: tuple):
        self.description = description
        self.icon = icon
        self.color = color


def load_gitignore(directory: str) -> PathSpec:
    gitignore_path = Path(directory) / ".gitignore"
    patterns = []
    try:
        if gitignore_path.exists():
            for line in gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    line = line.rstrip("/")
                    patterns.append(line)
                    if not line.startswith("**/"):
                        patterns.append(f"**/{line}")
    except Exception as e:
        logger.warning(f"Error reading .gitignore: {e}")
    return PathSpec.from_lines(GitWildMatchPattern, patterns)


def load_align_content(path: str) -> str:
    align_file_path = os.path.join(path, "Align.md")
    try:
        with open(align_file_path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:
        logger.warning(f"Error reading Align.md: {e}")
        return "No Align.md file found"


def view_repo(sender, app_data, user_data):
    """Display the Align.md content in a new window."""
    try:
        content = load_align_content(user_data) or "No content available"
        window_tag = f"preview_window_{hash(user_data)}"
        if dpg.does_item_exist(window_tag):
            dpg.delete_item(window_tag)
        with dpg.window(
            label=f"Preview: {os.path.basename(user_data)}",
            width=config.ui.PREVIEW_WIDTH,
            height=config.ui.PREVIEW_HEIGHT,
            pos=[100, 100],
            tag=window_tag
        ):
            dpg.add_text(default_value=content, wrap=0, tag=f"preview_text_{window_tag}")
    except Exception as e:
        error_msg = f"Error showing preview for {user_data}: {e}"
        logger.error(error_msg, exc_info=True)
        dpg.configure_item("status_text", default_value=error_msg)


def format_time_ago(timestamp: float) -> str:
    """Return a human-friendly relative time."""
    minutes = int((time.time() - timestamp) / 60)
    if minutes <= 0:
        return "just now"
    if minutes == 1:
        return "1 minute ago"
    if minutes < 60:
        return f"{minutes} minutes ago"
    hours = minutes // 60
    if hours == 1:
        return "1 hour ago"
    if hours < 24:
        return f"{hours} hours ago"
    days = hours // 24
    return f"{days} days ago"


def calculate_repo_hash(directory: str) -> str:
    """Compute a SHA256 hash of the repository contents."""
    sha256 = hashlib.sha256()
    gitignore_spec = load_gitignore(directory)
    files, skipped, binary_files = [], [], []
    for path in Path(directory).rglob("*"):
        if path.is_file():
            try:
                rel_path = str(path.relative_to(directory))
                if rel_path == "Align.md" or should_ignore(path.name, rel_path, gitignore_spec):
                    continue
                if is_binary_file(path):
                    binary_files.append(path)
                files.append((rel_path, path))
            except Exception as e:
                logger.warning(f"Error processing {path}: {e}")
                skipped.append(path)
    files.sort(key=lambda x: x[0])
    processed = 0
    for rel_path, path in files:
        try:
            sha256.update(rel_path.encode())
            sha256.update(path.read_bytes())
            processed += 1
        except Exception as e:
            logger.warning(f"Error reading {path}: {e}")
            skipped.append(path)
    if skipped:
        logger.info(f"Processed {processed} files, skipped {len(skipped)}")
    if binary_files:
        logger.debug(f"Found {len(binary_files)} binary files")
    return sha256.hexdigest()


def store_hash_in_metadata(file_path: str, hash_value: str) -> bool:
    try:
        with open(f"{file_path}:align_hash", "w", encoding="utf-8") as f:
            f.write(hash_value)
        logger.debug(f"Stored hash {hash_value[:8]} for {file_path}")
        return True
    except Exception as e:
        logger.warning(f"Could not store hash for {file_path}: {e}")
        return False


def read_hash_from_metadata(file_path: str) -> Optional[str]:
    try:
        with open(f"{file_path}:align_hash", "r", encoding="utf-8") as f:
            hash_value = f.read().strip()
            logger.debug(f"Read hash {hash_value[:8]} from {file_path}")
            return hash_value
    except Exception as e:
        logger.debug(f"Could not read hash from {file_path}: {e}")
        return None


# ---------- File System Watcher ----------
class RepoChangeHandler(FileSystemEventHandler):
    def __init__(self, repo_path: str):
        self.repo_path = repo_path
        self.last_refresh = 0
        self.refresh_cooldown = config.ui.REFRESH_COOLDOWN
        self.is_refreshing = False
        try:
            self.current_hash = calculate_repo_hash(repo_path)
            self.saved_hash = self.load_saved_hash()
            logger.info(f"Initialized handler for {repo_path} with hash {self.current_hash[:8]}")
        except Exception as e:
            logger.error(f"Error initializing handler for {repo_path}: {e}")
            raise AlignError(f"Failed to initialize handler: {e}")

    def load_saved_hash(self) -> Optional[str]:
        return read_hash_from_metadata(os.path.join(self.repo_path, "Align.md"))

    def update_saved_hash(self) -> None:
        old = self.saved_hash[:8] if self.saved_hash else None
        self.saved_hash = self.current_hash
        if store_hash_in_metadata(os.path.join(self.repo_path, "Align.md"), self.current_hash):
            logger.debug(f"Updated hash from {old} to {self.current_hash[:8]}")
        else:
            logger.warning("Failed to update hash in metadata")

    def on_any_event(self, event) -> None:
        if event.src_path.endswith("Align.md") or event.src_path.endswith(".tmp"):
            logger.debug(f"Ignoring event for {event.src_path}")
            return
        now = time.time()
        if now - self.last_refresh < self.refresh_cooldown:
            logger.debug(f"Skipping refresh; only {now - self.last_refresh:.1f}s since last")
            return
        try:
            logger.info(f"Processing {event.event_type} for {event.src_path}")
            self.last_refresh = now
            self.is_refreshing = True
            repo_ui.update_repo_list()
            refresh_repo(None, None, self.repo_path, show_preview=False)
            self.is_refreshing = False
            repo_ui.update_repo_list()
            logger.info(f"Completed {event.event_type} event")
        except Exception as e:
            logger.error(f"Error handling event in {self.repo_path}: {e}", exc_info=True)
            self.is_refreshing = False
            repo_ui.update_repo_list()


class RepoWatcher:
    def __init__(self):
        self.observers: Dict[str, Dict[str, Any]] = {}

    def watch_repo(self, repo_path: str) -> None:
        if repo_path in self.observers:
            return
        handler = RepoChangeHandler(repo_path)
        observer = Observer()
        observer.schedule(handler, repo_path, recursive=True)
        observer.start()
        self.observers[repo_path] = {"observer": observer, "event_handler": handler}

    def unwatch_repo(self, repo_path: str) -> None:
        if repo_path in self.observers:
            self.observers[repo_path]["observer"].stop()
            self.observers[repo_path]["observer"].join()
            del self.observers[repo_path]

    def stop_all(self) -> None:
        for obs in self.observers.values():
            obs["observer"].stop()
        for obs in self.observers.values():
            obs["observer"].join()
        self.observers.clear()


repo_watcher = RepoWatcher()


# ---------- Repository Actions ----------
def add_repository(sender, app_data, user_data) -> None:
    folder_path = app_data.get("file_path_name")
    if not folder_path:
        return
    try:
        repos = config.load_repos()
        if folder_path not in repos:
            repos.append(folder_path)
            config.save_repos(repos)
            refresh_repo(None, None, folder_path, show_preview=False)
            repo_watcher.watch_repo(folder_path)
            repo_ui.create_repo_entry(folder_path)
    except ConfigError as e:
        logger.error(f"Failed to add repository: {e}")
        dpg.configure_item("status_text", default_value=f"Error: {e}")


def remove_repository(sender, app_data, user_data) -> None:
    repo_path = user_data
    try:
        repos = config.load_repos()
        if repo_path in repos:
            repos.remove(repo_path)
            config.save_repos(repos)
            repo_watcher.unwatch_repo(repo_path)
            group_tag = f"repo_group_{hash(repo_path)}"
            if dpg.does_item_exist(group_tag):
                dpg.delete_item(group_tag)
    except ConfigError as e:
        logger.error(f"Failed to remove repository: {e}")
        dpg.configure_item("status_text", default_value=f"Error: {e}")


def ensure_align_in_gitignore(directory: str) -> None:
    gitignore_path = os.path.join(directory, ".gitignore")
    align_entry = "Align.md"
    try:
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r", encoding="utf-8") as f:
                content = f.read()
            if align_entry not in content.splitlines():
                with open(gitignore_path, "a", encoding="utf-8") as f:
                    if not content.endswith("\n"):
                        f.write("\n")
                    f.write(f"# Added by Align\n{align_entry}\n")
                logger.info(f"Added {align_entry} to .gitignore in {directory}")
        else:
            with open(gitignore_path, "w", encoding="utf-8") as f:
                f.write(f"# Created by Align\n{align_entry}\n")
            logger.info(f"Created .gitignore with {align_entry} in {directory}")
    except Exception as e:
        logger.warning(f"Could not modify .gitignore in {directory}: {e}")


def refresh_repo(sender=None, app_data=None, user_data: Optional[str] = None, show_preview: bool = False) -> bool:
    path = user_data
    if not path or not os.path.exists(path):
        logger.warning(f"Invalid repository path: {path}")
        return False

    logger.info(f"Starting refresh for {path}")
    try:
        ensure_align_in_gitignore(path)
        gitignore_spec = load_gitignore(path)
        new_hash = calculate_repo_hash(path)
        handler = repo_watcher.observers.get(path, {}).get("event_handler")
        if handler and handler.current_hash == new_hash == handler.saved_hash:
            logger.info(f"No changes detected for {path}, skipping refresh")
            return True

        markdown_content = generate_markdown(path, gitignore_spec)
        align_file_path = os.path.join(path, "Align.md")
        with open(align_file_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
        logger.info(f"Updated Align.md at {align_file_path}")
        store_hash_in_metadata(align_file_path, new_hash)
        if handler:
            handler.current_hash = new_hash
            handler.update_saved_hash()
        if show_preview:
            view_repo(None, None, path)
        return True
    except Exception as e:
        logger.error(f"Error refreshing repository {path}: {e}", exc_info=True)
        dpg.configure_item("status_text", default_value=f"Error refreshing {os.path.basename(path)}")
        return False


def _refresh_repositories(repos_to_refresh: List[str], description: str = "repositories") -> None:
    try:
        if not repos_to_refresh:
            msg = f"No {description} to update"
            logger.info(msg)
            dpg.configure_item("status_text", default_value=msg)
            return

        logger.info(f"Processing {len(repos_to_refresh)} {description}")
        for repo in repos_to_refresh:
            if repo in repo_watcher.observers:
                repo_watcher.observers[repo]["event_handler"].is_refreshing = True
        repo_ui.update_repo_list()
        successful = 0
        for i, repo in enumerate(repos_to_refresh, 1):
            logger.info(f"Processing repository {i}/{len(repos_to_refresh)}: {repo}")
            if refresh_repo(None, None, repo, show_preview=False):
                successful += 1
            if repo in repo_watcher.observers:
                handler = repo_watcher.observers[repo]["event_handler"]
                handler.is_refreshing = False
                handler.current_hash = calculate_repo_hash(repo)
                handler.last_refresh = time.time()
            if i % 3 == 0 or i == len(repos_to_refresh):
                repo_ui.update_repo_list()
        repo_ui.update_repo_list()
        status_msg = f"Realigned {successful}/{len(repos_to_refresh)} {description}"
        logger.info(status_msg)
        dpg.configure_item("status_text", default_value=status_msg)
    except Exception as e:
        error_msg = f"Error during realign of {description}: {e}"
        logger.error(error_msg, exc_info=True)
        dpg.configure_item("status_text", default_value=error_msg)


def refresh_all_repos(sender=None, app_data=None, user_data=None) -> None:
    try:
        repos = config.load_repos()
        repos_to_update = []
        current_time = time.time()
        for repo in repos:
            if repo not in repo_watcher.observers:
                logger.info(f"Repository {repo} not watched; will update")
                repos_to_update.append(repo)
                repo_watcher.watch_repo(repo)
            else:
                handler = repo_watcher.observers[repo]["event_handler"]
                current_hash = calculate_repo_hash(repo)
                handler.current_hash = current_hash
                if current_hash != handler.saved_hash:
                    logger.info(f"Repository {repo} out of sync; will update")
                    repos_to_update.append(repo)
                else:
                    logger.info(f"Repository {repo} is up to date")
                    handler.last_refresh = current_time
        repo_ui.update_repo_list()
        if repos_to_update:
            _refresh_repositories(repos_to_update, "out-of-date repositories")
        else:
            msg = "All repositories are up to date"
            logger.info(msg)
            dpg.configure_item("status_text", default_value=msg)
            repo_ui.update_repo_list()
    except Exception as e:
        error_msg = f"Error preparing repositories for refresh: {e}"
        logger.error(error_msg, exc_info=True)
        dpg.configure_item("status_text", default_value=error_msg)


def refresh_selected_repos(sender=None, app_data=None, user_data=None) -> None:
    try:
        repos = config.load_repos()
        selected = [
            repo for repo in repos
            if dpg.does_item_exist(f"select_{hash(repo)}") and dpg.get_value(f"select_{hash(repo)}")
        ]
        _refresh_repositories(selected, "selected repositories")
    except Exception as e:
        error_msg = f"Error preparing selected repositories for refresh: {e}"
        logger.error(error_msg, exc_info=True)
        dpg.configure_item("status_text", default_value=error_msg)


# ---------- Repository List UI ----------
class RepositoryListUI:
    def __init__(self):
        self.icon_font = None

    def setup_icons(self):
        with dpg.font_registry():
            try:
                font_path = os.path.join(os.path.dirname(__file__), "fonts", "fa-solid-900.ttf")
                if os.path.exists(font_path):
                    with dpg.font(font_path, 13) as font:
                        dpg.add_font_range_hint(dpg.mvFontRangeHint_Default)
                        dpg.add_font_range(0xf000, 0xf999)
                    logger.info("Successfully loaded Font Awesome icons")
                    self.icon_font = font
                    return font
                else:
                    logger.warning(f"Font file not found at {font_path}")
                    return None
            except Exception as e:
                logger.error(f"Could not load icons: {e}", exc_info=True)
                return None

    def create_repo_entry(self, repo: str, parent: str = "repo_list") -> None:
        group_tag = f"repo_group_{hash(repo)}"
        with dpg.group(parent=parent, horizontal=True, tag=group_tag):
            dpg.add_checkbox(tag=f"select_{hash(repo)}")
            dpg.add_button(label="\uf2ed", callback=remove_repository, user_data=repo, width=30)
            dpg.bind_item_font(dpg.last_item(), self.icon_font)
            dpg.add_button(label="\uf06e", callback=view_repo, user_data=repo, width=30)
            dpg.bind_item_font(dpg.last_item(), self.icon_font)
            status_tag = f"status_{hash(repo)}"
            dpg.add_text("\uf111", color=(128, 128, 128), tag=status_tag)
            dpg.bind_item_font(dpg.last_item(), self.icon_font)
            with dpg.tooltip(status_tag, tag=f"tooltip_{hash(repo)}"):
                dpg.add_text("Loading status...", tag=f"tooltip_text_{hash(repo)}")
            dpg.add_spacer(width=10)
            dpg.add_text(repo, wrap=0)
            dpg.add_text("", tag=f"time_{hash(repo)}", color=(128, 128, 128))

    def create_repo_list(self) -> None:
        repos = config.load_repos()
        dpg.delete_item("repo_list", children_only=True)
        for repo in repos:
            self.create_repo_entry(repo)

    def update_repo_status(self, repo: str, handler: Optional[RepoChangeHandler]) -> None:
        status_tag = f"status_{hash(repo)}"
        tooltip_tag = f"tooltip_{hash(repo)}"
        time_tag = f"time_{hash(repo)}"
        if not dpg.does_item_exist(status_tag):
            return
        if handler:
            handler.current_hash = calculate_repo_hash(repo)
        if handler and handler.is_refreshing:
            status = RepoStatus.UPDATING
        elif handler and handler.current_hash == handler.saved_hash:
            status = RepoStatus.UP_TO_DATE
        else:
            status = RepoStatus.NEEDS_UPDATE
        dpg.configure_item(status_tag, default_value=status.icon, color=status.color)
        tooltip_text = (
            "Status Indicator\n\n"
            "✓ Check: Content is up to date\n"
            "↻ Refresh: Currently updating\n"
            "⚠ Warning: Content needs updating\n\n"
            f"Current Status: {status.description}"
        )
        tooltip_text_tag = f"tooltip_text_{hash(repo)}"
        if dpg.does_item_exist(tooltip_text_tag):
            dpg.configure_item(tooltip_text_tag, default_value=tooltip_text)
        if handler and handler.last_refresh:
            dpg.configure_item(time_tag, default_value=f"(Updated: {format_time_ago(handler.last_refresh)})")

    def update_repo_list(self) -> None:
        try:
            repos = config.load_repos()
            for repo in repos:
                handler = repo_watcher.observers.get(repo, {}).get("event_handler")
                self.update_repo_status(repo, handler)
        except ConfigError as e:
            logger.error(f"Failed to update repository list: {e}")
            dpg.configure_item("status_text", default_value=f"Error: {e}")


repo_ui = RepositoryListUI()


# ---------- Main Application ----------
def main():
    dpg.create_context()
    repo_ui.setup_icons()
    with dpg.file_dialog(
        directory_selector=True,
        show=False,
        callback=add_repository,
        id="file_dialog",
        width=config.ui.FILE_DIALOG_WIDTH,
        height=config.ui.FILE_DIALOG_HEIGHT,
        modal=True,
        default_path=os.path.expanduser("~"),
        label="Select Repository Directory"
    ):
        dpg.add_text("Select a repository directory to track")
        dpg.add_separator()
        with dpg.group():
            dpg.add_text("Tips:", color=(255, 255, 0))
            dpg.add_text("• Double-click a folder to open it")
            dpg.add_text("• Click OK to select current directory")
            dpg.add_text("• Use .. to go up one level")

    with dpg.window(
        label="Align - Repository Tracker",
        width=config.ui.WINDOW_WIDTH,
        height=config.ui.WINDOW_HEIGHT,
        tag="primary_window"
    ):
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Add Repository",
                callback=lambda: dpg.show_item("file_dialog"),
                width=config.ui.BUTTON_WIDTH
            )
            with dpg.group(horizontal=True):
                dpg.add_text("Realign:")
                dpg.add_button(label="ALL", callback=refresh_all_repos, width=50)
                dpg.add_button(label="Selected", callback=refresh_selected_repos, width=80)
        dpg.add_separator()
        dpg.add_text("Tracked Repositories:")
        with dpg.child_window(height=-1, width=-1, tag="repo_list"):
            pass
        dpg.add_separator()
        dpg.add_text("Ready", tag="status_text")

    dpg.create_viewport(
        title="Align",
        width=config.ui.WINDOW_WIDTH,
        height=config.ui.WINDOW_HEIGHT
    )
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window("primary_window", True)

    try:
        for repo in config.load_repos():
            repo_watcher.watch_repo(repo)
        repo_ui.create_repo_list()
        dpg.start_dearpygui()
    except Exception as e:
        logger.error(f"Application error: {e}")
        raise
    finally:
        repo_watcher.stop_all()
        dpg.destroy_context()


if __name__ == "__main__":
    main()
