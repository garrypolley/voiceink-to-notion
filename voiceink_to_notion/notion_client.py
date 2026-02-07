"""Notion API client for creating pages in a database."""

import httpx
from dataclasses import dataclass
from datetime import datetime


NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"

# Required properties for the database schema
REQUIRED_PROPERTIES = {
    "Text": {"rich_text": {}},
    "Timestamp": {"date": {}},
    "Duration": {"number": {"format": "number"}},
    "VoiceInk ID": {"rich_text": {}},
}


@dataclass
class NotionConfig:
    """Configuration for Notion API access."""
    
    api_key: str
    database_id: str


@dataclass
class ConnectionResult:
    """Result of testing Notion connection."""
    
    success: bool
    error: str | None = None
    database_name: str | None = None


@dataclass  
class SchemaResult:
    """Result of checking database schema."""
    
    valid: bool
    missing_properties: list[str] | None = None
    title_property: str | None = None


class NotionClient:
    """Simple Notion API client for creating database pages."""
    
    def __init__(self, config: NotionConfig):
        self.config = config
        self._client = httpx.Client(
            base_url=NOTION_BASE_URL,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Notion-Version": NOTION_API_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        self._title_property = "Name"  # Default, will be detected
    
    def test_connection(self) -> ConnectionResult:
        """Test that we can connect to the Notion database."""
        try:
            response = self._client.get(f"/databases/{self.config.database_id}")
            if response.status_code == 200:
                data = response.json()
                title_parts = data.get("title", [])
                db_name = title_parts[0]["plain_text"] if title_parts else "Untitled"
                return ConnectionResult(success=True, database_name=db_name)
            elif response.status_code == 404:
                return ConnectionResult(
                    success=False, 
                    error="Database not found. Check the ID and make sure it's shared with your integration."
                )
            elif response.status_code == 401:
                return ConnectionResult(
                    success=False,
                    error="Invalid API key. Check your Notion integration token."
                )
            else:
                return ConnectionResult(
                    success=False,
                    error=f"Notion API error: {response.status_code}"
                )
        except httpx.HTTPError as e:
            return ConnectionResult(success=False, error=f"Connection failed: {e}")
    
    def check_schema(self) -> SchemaResult:
        """Check if database has required properties."""
        try:
            response = self._client.get(f"/databases/{self.config.database_id}")
            if response.status_code != 200:
                return SchemaResult(valid=False, missing_properties=list(REQUIRED_PROPERTIES.keys()))
            
            data = response.json()
            properties = data.get("properties", {})
            
            # Find the title property name
            for prop_name, prop_info in properties.items():
                if prop_info.get("type") == "title":
                    self._title_property = prop_name
                    break
            
            # Check for required properties
            existing = set(properties.keys())
            required = set(REQUIRED_PROPERTIES.keys())
            missing = required - existing
            
            if missing:
                return SchemaResult(
                    valid=False, 
                    missing_properties=list(missing),
                    title_property=self._title_property
                )
            
            return SchemaResult(valid=True, title_property=self._title_property)
            
        except httpx.HTTPError:
            return SchemaResult(valid=False, missing_properties=list(REQUIRED_PROPERTIES.keys()))
    
    def setup_schema(self) -> bool:
        """Add missing properties to the database."""
        schema_result = self.check_schema()
        if schema_result.valid:
            return True
        
        if not schema_result.missing_properties:
            return True
        
        # Build properties to add
        properties_to_add = {
            prop: REQUIRED_PROPERTIES[prop] 
            for prop in schema_result.missing_properties
        }
        
        try:
            response = self._client.patch(
                f"/databases/{self.config.database_id}",
                json={"properties": properties_to_add}
            )
            return response.status_code == 200
        except httpx.HTTPError:
            return False
    
    def get_database_info(self) -> dict | None:
        """Get information about the target database."""
        try:
            response = self._client.get(f"/databases/{self.config.database_id}")
            if response.status_code == 200:
                return response.json()
        except httpx.HTTPError:
            pass
        return None
    
    def get_all_synced_ids(self) -> set[str]:
        """Query all pages in the database and extract VoiceInk IDs.
        
        This is used on first run to populate the local cache with
        what's already been synced to Notion.
        """
        synced_ids = set()
        start_cursor = None
        
        while True:
            payload = {"page_size": 100}
            if start_cursor:
                payload["start_cursor"] = start_cursor
            
            try:
                response = self._client.post(
                    f"/databases/{self.config.database_id}/query",
                    json=payload
                )
                
                if response.status_code != 200:
                    break
                
                data = response.json()
                
                for page in data.get("results", []):
                    properties = page.get("properties", {})
                    voiceink_id_prop = properties.get("VoiceInk ID", {})
                    rich_text = voiceink_id_prop.get("rich_text", [])
                    if rich_text:
                        voiceink_id = rich_text[0].get("plain_text", "")
                        if voiceink_id:
                            synced_ids.add(voiceink_id)
                
                # Check for more pages
                if data.get("has_more") and data.get("next_cursor"):
                    start_cursor = data["next_cursor"]
                else:
                    break
                    
            except httpx.HTTPError:
                break
        
        return synced_ids
    
    def create_transcription_page(
        self,
        text: str,
        timestamp: datetime,
        duration: float,
        enhanced_text: str | None = None,
        prompt_name: str | None = None,
        voiceink_id: str | None = None,
    ) -> dict | None:
        """Create a new page in the Notion database for a transcription.
        
        The database should have these properties:
        - Title (title): The transcription text or a summary
        - Text (rich_text): The full transcription text  
        - Timestamp (date): When the transcription was created
        - Duration (number): Recording duration in seconds
        - Enhanced Text (rich_text): AI-enhanced version if available
        - Prompt (rich_text): The prompt/mode used
        - VoiceInk ID (rich_text): Unique ID from VoiceInk for deduplication
        """
        # Truncate title to 100 chars for readability
        title = text[:100] + "..." if len(text) > 100 else text
        
        # Build properties matching the database schema
        # Use detected title property name (default is "Name")
        properties = {
            self._title_property: {
                "title": [{"text": {"content": title}}]
            },
            "Text": {
                "rich_text": [{"text": {"content": text[:2000]}}]  # Notion limit
            },
            "Timestamp": {
                "date": {"start": timestamp.isoformat()}
            },
            "Duration": {
                "number": round(duration, 2)
            },
        }
        
        if voiceink_id:
            properties["VoiceInk ID"] = {
                "rich_text": [{"text": {"content": voiceink_id}}]
            }
        
        # Build page content with full text as blocks
        children = []
        
        # Split long text into multiple paragraph blocks (Notion has block limits)
        remaining_text = text
        while remaining_text:
            chunk = remaining_text[:2000]
            remaining_text = remaining_text[2000:]
            children.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": chunk}}]
                }
            })
        
        if enhanced_text:
            children.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": "Enhanced Version"}}]
                }
            })
            remaining_enhanced = enhanced_text
            while remaining_enhanced:
                chunk = remaining_enhanced[:2000]
                remaining_enhanced = remaining_enhanced[2000:]
                children.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [{"type": "text", "text": {"content": chunk}}]
                    }
                })
        
        payload = {
            "parent": {"database_id": self.config.database_id},
            "properties": properties,
            "children": children[:100],  # Notion limit
        }
        
        try:
            response = self._client.post("/pages", json=payload)
            
            if response.status_code == 200:
                return response.json()
            else:
                # Try with minimal properties if full set fails
                minimal_payload = {
                    "parent": {"database_id": self.config.database_id},
                    "properties": {
                        self._title_property: {"title": [{"text": {"content": title}}]}
                    },
                    "children": children[:100],
                }
                response = self._client.post("/pages", json=minimal_payload)
                if response.status_code == 200:
                    return response.json()
                    
        except httpx.HTTPError as e:
            print(f"HTTP error creating page: {e}")
        
        return None
    
    def close(self):
        """Close the HTTP client."""
        self._client.close()
