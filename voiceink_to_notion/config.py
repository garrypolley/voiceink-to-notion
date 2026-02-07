"""Configuration management."""

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Config:
    """Application configuration."""
    
    notion_api_key: str
    notion_database_id: str
    sync_interval_seconds: int = 30
    voiceink_db_path: str | None = None
    
    @classmethod
    def from_file(cls, path: Path) -> "Config":
        """Load config from a JSON file."""
        data = json.loads(path.read_text())
        return cls(
            notion_api_key=data["notion_api_key"],
            notion_database_id=data["notion_database_id"],
            sync_interval_seconds=data.get("sync_interval_seconds", 30),
            voiceink_db_path=data.get("voiceink_db_path"),
        )
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load config from environment variables."""
        api_key = os.environ.get("NOTION_API_KEY")
        database_id = os.environ.get("NOTION_DATABASE_ID")
        
        if not api_key or not database_id:
            raise ValueError(
                "Missing required environment variables: "
                "NOTION_API_KEY and NOTION_DATABASE_ID"
            )
        
        return cls(
            notion_api_key=api_key,
            notion_database_id=database_id,
            sync_interval_seconds=int(os.environ.get("SYNC_INTERVAL", "30")),
            voiceink_db_path=os.environ.get("VOICEINK_DB_PATH"),
        )


def get_default_config_path() -> Path:
    """Get the default config file path."""
    return Path.home() / ".config" / "voiceink-to-notion" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from file or environment.
    
    Priority:
    1. Provided config_path
    2. Default config file location
    3. Environment variables
    """
    if config_path and config_path.exists():
        return Config.from_file(config_path)
    
    default_path = get_default_config_path()
    if default_path.exists():
        return Config.from_file(default_path)
    
    # Fall back to environment variables
    return Config.from_env()
