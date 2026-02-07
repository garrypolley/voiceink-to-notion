# VoiceInk to Notion

[![VoiceInk](https://img.shields.io/badge/Works%20with-VoiceInk-blue?style=for-the-badge)](https://tryvoiceink.com?atp=garrypolley)
[![Notion](https://img.shields.io/badge/Syncs%20to-Notion-black?style=for-the-badge)](https://notion.so)

Automatically sync your [VoiceInk](https://tryvoiceink.com?atp=garrypolley) transcriptions to a Notion database.

## Install

```bash
git clone https://github.com/garrypolley/voiceink-to-notion.git
cd voiceink-to-notion
uv sync
uv run voiceink-to-notion install
```

That's it! The installer will prompt you for your Notion API key and database ID, then start syncing in the background.

---

<details>
<summary><strong>Setup Details</strong></summary>

### 1. Create a Notion Integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
2. Click **"New integration"**
3. Give it a name (e.g., "VoiceInk Sync")
4. Copy the **Internal Integration Secret** (starts with `secret_` or `ntn_`)

### 2. Create a Notion Database

Create a database in Notion. The app will automatically add the required properties (Text, Timestamp, Duration, VoiceInk ID) if they're missing.

### 3. Share Database with Integration

1. Open your Notion database
2. Click **...** (three dots) → **"Add connections"**
3. Select your integration

### 4. Get Database ID

Copy from the URL: `https://notion.so/workspace/DATABASE_ID_HERE?v=...`

### 5. Run the Installer

```bash
uv run voiceink-to-notion install
```

You'll be prompted for your API key and database ID. The service will then run in the background automatically.

</details>

<details>
<summary><strong>Technical Details</strong></summary>

### How It Works

1. **Reads VoiceInk's database** - Parses the SwiftData (SQLite) store at `~/Library/Application Support/com.prakashjoshipax.VoiceInk/`

2. **Caches synced IDs locally** - On first run, fetches all existing entries from Notion to know what's already synced. Stores this in `~/.config/voiceink-to-notion/sync_state.json`

3. **Syncs only new items** - Compares VoiceInk transcriptions against the local cache, only uploads new ones

4. **Runs as a launchd service** - Starts automatically on login, restarts if it crashes, syncs every 30 seconds

### Commands

```bash
uv run voiceink-to-notion install    # Install background service
uv run voiceink-to-notion uninstall  # Remove background service
uv run voiceink-to-notion service    # Check if service is running
uv run voiceink-to-notion logs       # View service logs
uv run voiceink-to-notion logs -f    # Follow logs in real-time
uv run voiceink-to-notion sync       # Run manually (foreground)
uv run voiceink-to-notion sync --once # Sync once and exit
uv run voiceink-to-notion status     # Show sync statistics
uv run voiceink-to-notion list       # List recent transcriptions
uv run voiceink-to-notion reset      # Clear sync state
```

### Configuration

Config is stored at `~/.config/voiceink-to-notion/config.json`:

```json
{
    "notion_api_key": "ntn_your_token",
    "notion_database_id": "your_database_id",
    "sync_interval_seconds": 30
}
```

Or use environment variables:

```bash
export NOTION_API_KEY="ntn_your_token"
export NOTION_DATABASE_ID="your_database_id"
```

### Logs

Service logs are at `~/.config/voiceink-to-notion/logs/`

</details>

## License

MIT
