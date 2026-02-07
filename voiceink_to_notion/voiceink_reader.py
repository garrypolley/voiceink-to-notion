"""Read transcriptions from VoiceInk's SwiftData SQLite database."""

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class Transcription:
    """A VoiceInk transcription record."""
    
    id: str
    text: str
    enhanced_text: str | None
    timestamp: datetime
    duration: float
    prompt_name: str | None
    power_mode_name: str | None


def find_voiceink_database() -> Path | None:
    """Find VoiceInk's SwiftData database on disk.
    
    SwiftData stores data in SQLite format. VoiceInk could be:
    - Sandboxed app: ~/Library/Containers/com.prakashjoshipax.VoiceInk/...
    - Non-sandboxed: ~/Library/Application Support/com.prakashjoshipax.VoiceInk/...
    """
    home = Path.home()
    
    # Possible locations for VoiceInk data (most specific first)
    candidates = [
        # Non-sandboxed locations (most common for VoiceInk)
        home / "Library/Application Support/com.prakashjoshipax.VoiceInk",
        home / "Library/Application Support/VoiceInk",
        # Sandboxed container locations
        home / "Library/Containers/com.prakashjoshipax.VoiceInk/Data/Library/Application Support",
        home / "Library/Containers/VoiceInk/Data/Library/Application Support",
    ]
    
    for base_path in candidates:
        if not base_path.exists():
            continue
        
        # Look for default.store first (SwiftData's default name)
        default_store = base_path / "default.store"
        if default_store.is_file():
            return default_store
        
        # SwiftData creates a default.store file or similar
        for db_file in base_path.glob("*.store"):
            # Skip dictionary.store - that's for vocabulary, not transcriptions
            if db_file.name == "dictionary.store":
                continue
            if db_file.is_file():
                return db_file
        
        # Also check for .sqlite files
        for db_file in base_path.glob("*.sqlite"):
            if db_file.is_file():
                return db_file
    
    return None


def _parse_swiftdata_timestamp(value: float | None) -> datetime:
    """Parse SwiftData/Core Data timestamp (seconds since 2001-01-01)."""
    if value is None:
        return datetime.now()
    
    # Core Data reference date is 2001-01-01 00:00:00 UTC
    core_data_epoch = datetime(2001, 1, 1)
    return datetime.fromtimestamp(core_data_epoch.timestamp() + value)


def read_transcriptions(db_path: Path) -> list[Transcription]:
    """Read all transcriptions from VoiceInk's database.
    
    VoiceInk uses SwiftData which stores data in SQLite with Core Data conventions:
    - Table: ZTRANSCRIPTION
    - Columns prefixed with Z
    - Timestamps in Core Data epoch (seconds since 2001-01-01)
    - UUIDs stored as blobs
    """
    transcriptions = []
    
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Query the ZTRANSCRIPTION table directly
        query = """
            SELECT 
                Z_PK,
                hex(ZID) as ZID_HEX,
                ZTEXT,
                ZENHANCEDTEXT,
                ZTIMESTAMP,
                ZDURATION,
                ZPROMPTNAME,
                ZPOWERMODENAME,
                ZTRANSCRIPTIONSTATUS
            FROM ZTRANSCRIPTION
            WHERE ZTEXT IS NOT NULL AND ZTEXT != ''
            ORDER BY ZTIMESTAMP DESC
        """
        
        cursor.execute(query)
        
        for row in cursor.fetchall():
            # Use hex UUID as the ID, or fall back to primary key
            record_id = row["ZID_HEX"] or str(row["Z_PK"])
            
            # Format UUID properly if it's a hex string (32 chars)
            if record_id and len(record_id) == 32:
                record_id = f"{record_id[:8]}-{record_id[8:12]}-{record_id[12:16]}-{record_id[16:20]}-{record_id[20:]}"
            
            transcriptions.append(Transcription(
                id=record_id,
                text=row["ZTEXT"],
                enhanced_text=row["ZENHANCEDTEXT"],
                timestamp=_parse_swiftdata_timestamp(row["ZTIMESTAMP"]),
                duration=row["ZDURATION"] or 0.0,
                prompt_name=row["ZPROMPTNAME"],
                power_mode_name=row["ZPOWERMODENAME"],
            ))
        
        conn.close()
        
    except sqlite3.Error as e:
        raise RuntimeError(f"Failed to read VoiceInk database: {e}") from e
    
    return transcriptions
