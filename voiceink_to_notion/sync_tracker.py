"""Track which transcriptions have been synced to Notion."""

import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path


@dataclass
class SyncState:
    """Tracks sync state to avoid duplicates."""
    
    synced_ids: set[str] = field(default_factory=set)
    last_sync_time: datetime | None = None
    notion_cache_populated: bool = False  # Whether we've fetched from Notion
    
    def mark_synced(self, voiceink_id: str):
        """Mark a transcription as synced."""
        self.synced_ids.add(voiceink_id)
        self.last_sync_time = datetime.now()
    
    def is_synced(self, voiceink_id: str) -> bool:
        """Check if a transcription has already been synced."""
        return voiceink_id in self.synced_ids
    
    def merge_notion_ids(self, notion_ids: set[str]):
        """Merge IDs fetched from Notion into local state."""
        self.synced_ids.update(notion_ids)
        self.notion_cache_populated = True


def get_state_file_path() -> Path:
    """Get the path to the sync state file."""
    # Store in user's config directory
    config_dir = Path.home() / ".config" / "voiceink-to-notion"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "sync_state.json"


def load_sync_state() -> SyncState:
    """Load sync state from disk."""
    state_file = get_state_file_path()
    
    if not state_file.exists():
        return SyncState()
    
    try:
        data = json.loads(state_file.read_text())
        state = SyncState(
            synced_ids=set(data.get("synced_ids", [])),
            notion_cache_populated=data.get("notion_cache_populated", False),
        )
        if data.get("last_sync_time"):
            state.last_sync_time = datetime.fromisoformat(data["last_sync_time"])
        return state
    except (json.JSONDecodeError, KeyError):
        return SyncState()


def save_sync_state(state: SyncState):
    """Save sync state to disk."""
    state_file = get_state_file_path()
    
    data = {
        "synced_ids": list(state.synced_ids),
        "last_sync_time": state.last_sync_time.isoformat() if state.last_sync_time else None,
        "notion_cache_populated": state.notion_cache_populated,
    }
    
    state_file.write_text(json.dumps(data, indent=2))
