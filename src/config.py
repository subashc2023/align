"""Configuration management for the Align application."""

import os
import json
import logging
from typing import List, Dict, Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class UIConfig:
    """UI-related configuration."""
    WINDOW_WIDTH: int = 800
    WINDOW_HEIGHT: int = 600
    BUTTON_WIDTH: int = 120
    PREVIEW_WIDTH: int = 600
    PREVIEW_HEIGHT: int = 600
    REFRESH_COOLDOWN: float = 1.0  # seconds
    FILE_DIALOG_WIDTH: int = 700
    FILE_DIALOG_HEIGHT: int = 500

class ConfigError(Exception):
    """Configuration related errors."""
    pass

class Config:
    """Configuration management class."""
    
    def __init__(self):
        self.config_path = os.path.join(os.path.expanduser("~"), ".align_config.json")
        self.ui = UIConfig()
        self._load_env_vars()
    
    def _load_env_vars(self) -> None:
        """Load configuration from environment variables."""
        env_prefix = "ALIGN_"
        for key, value in os.environ.items():
            if key.startswith(env_prefix):
                config_key = key[len(env_prefix):].lower()
                if hasattr(self.ui, config_key.upper()):
                    try:
                        # Convert value to appropriate type
                        attr_type = type(getattr(self.ui, config_key.upper()))
                        setattr(self.ui, config_key.upper(), attr_type(value))
                    except ValueError as e:
                        logger.warning(f"Invalid environment variable {key}: {e}")
    
    def load_repos(self) -> List[str]:
        """Load tracked repositories from config file."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading config: {e}")
                raise ConfigError(f"Failed to load config: {e}")
        return []
    
    def save_repos(self, repos: List[str]) -> None:
        """Save tracked repositories to config file."""
        try:
            with open(self.config_path, 'w') as f:
                json.dump(repos, f)
        except Exception as e:
            logger.error(f"Error saving config: {e}")
            raise ConfigError(f"Failed to save config: {e}")
    
    def get_ui_constants(self) -> Dict[str, Any]:
        """Get UI constants as a dictionary."""
        return {
            key: getattr(self.ui, key)
            for key in dir(self.ui)
            if not key.startswith('_') and key.isupper()
        }

# Create global config instance
config = Config() 