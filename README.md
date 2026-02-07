# VoiceInk to Notion

Automatically sync your VoiceInk transcriptions to a Notion database.

## Quick Start

```bash
# Install
uv sync

# Run (interactive setup on first run)
uv run voiceink-to-notion sync
```

That's it! On first run, it will:
1. Prompt for your Notion API key and database ID
2. Test the connection
3. Create any missing database properties
4. Fetch existing entries from Notion (so it doesn't re-sync)
5. Sync all new transcriptions

## Commands

```bash
# Install as background service (runs forever, starts on login)
uv run voiceink-to-notion install

# Check if background service is running
uv run voiceink-to-notion service

# View service logs
uv run voiceink-to-notion logs
uv run voiceink-to-notion logs -f        # Follow in real-time

# Remove background service
uv run voiceink-to-notion uninstall

# --- Manual sync (if not using background service) ---

# Sync continuously - watches for new transcriptions
uv run voiceink-to-notion sync

# Sync once and exit
uv run voiceink-to-notion sync --once

# Check status
uv run voiceink-to-notion status

# List recent transcriptions
uv run voiceink-to-notion list
uv run voiceink-to-notion list -n 20

# Reset sync state (start fresh)
uv run voiceink-to-notion reset
```

## Setup

### 1. Create a Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **"New integration"**
3. Give it a name (e.g., "VoiceInk Sync")
4. Copy the **Internal Integration Secret** (starts with `secret_` or `ntn_`)

### 2. Create a Notion Database

Create a database in Notion. The app will automatically add these properties if missing:
- **Text** - Full transcription text
- **Timestamp** - When the transcription was created
- **Duration** - Recording duration in seconds
- **VoiceInk ID** - Unique identifier for deduplication

### 3. Share Database with Integration

1. Open your Notion database
2. Click **...** (three dots) → **"Add connections"**
3. Select your integration

### 4. Get Database ID

Copy from the URL: `https://notion.so/workspace/DATABASE_ID_HERE?v=...`

### 5. Run

```bash
uv run voiceink-to-notion sync
```

You'll be prompted for credentials on first run, or create `~/.config/voiceink-to-notion/config.json`:

```json
{
    "notion_api_key": "ntn_your_token",
    "notion_database_id": "your_database_id",
    "sync_interval_seconds": 30
}
```

## Background Service

The recommended way to run this is as a background service using macOS launchd:

```bash
uv run voiceink-to-notion install
```

This will:
- **Start automatically** when you log in
- **Run forever** in the background
- **Restart automatically** if it crashes
- **Sync every 30 seconds** for new transcriptions

Logs are written to `~/.config/voiceink-to-notion/logs/`

To stop and remove the service:
```bash
uv run voiceink-to-notion uninstall
```

## How It Works

1. **Reads VoiceInk's database** - Parses the SwiftData (SQLite) store at `~/Library/Application Support/com.prakashjoshipax.VoiceInk/`

2. **Caches synced IDs locally** - On first run, fetches all existing entries from Notion to know what's already synced. Stores this in `~/.config/voiceink-to-notion/sync_state.json`

3. **Syncs only new items** - Compares VoiceInk transcriptions against the local cache, only uploads new ones

4. **Runs continuously** - Polls every 30 seconds for new transcriptions

## Environment Variables

Alternative to config file:

```bash
export NOTION_API_KEY="ntn_your_token"
export NOTION_DATABASE_ID="your_database_id"
export SYNC_INTERVAL=30
```

## Troubleshooting

### "VoiceInk database not found"
Make sure VoiceInk is installed and you've made at least one transcription.

### "Database not found" 
1. Check the database ID is correct
2. Make sure you've shared the database with your integration

### Schema issues
The app auto-creates missing properties. If you see errors, run `uv run voiceink-to-notion status` to diagnose.

### Re-sync everything
```bash
uv run voiceink-to-notion reset
uv run voiceink-to-notion sync --once
```

## License

MIT
