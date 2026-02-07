"""Main entry point for VoiceInk to Notion sync."""

import argparse
import subprocess
import sys
import time
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt, Confirm

from .config import load_config, get_default_config_path, Config
from .notion_client import NotionClient, NotionConfig
from .sync_tracker import load_sync_state, save_sync_state
from .voiceink_reader import find_voiceink_database, read_transcriptions


console = Console()

# launchd service configuration
LAUNCHD_LABEL = "com.voiceink-to-notion.sync"
LAUNCHD_PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LAUNCHD_LABEL}.plist"
LOG_DIR = Path.home() / ".config" / "voiceink-to-notion" / "logs"


def interactive_setup() -> Config | None:
    """Run interactive setup to create config."""
    console.print("\n[bold blue]VoiceInk to Notion Setup[/bold blue]\n")
    
    console.print("[dim]To set this up, you need:[/dim]")
    console.print("  1. A Notion integration token (from notion.so/my-integrations)")
    console.print("  2. A Notion database ID (from the database URL)")
    console.print("  3. The database shared with your integration\n")
    
    api_key = Prompt.ask("Notion API Key (starts with secret_ or ntn_)")
    if not api_key:
        return None
    
    database_id = Prompt.ask("Notion Database ID")
    if not database_id:
        return None
    
    # Clean up database ID (remove dashes if present, extract from URL if needed)
    database_id = database_id.replace("-", "")
    if "notion.so" in database_id:
        # Try to extract ID from URL
        parts = database_id.split("/")
        for part in parts:
            if len(part) >= 32 and part[:32].replace("-", "").isalnum():
                database_id = part[:32].replace("-", "")
                break
    
    config = Config(
        notion_api_key=api_key,
        notion_database_id=database_id,
    )
    
    # Save config
    config_path = get_default_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(f'''{{
    "notion_api_key": "{api_key}",
    "notion_database_id": "{database_id}",
    "sync_interval_seconds": 30
}}
''')
    
    console.print(f"\n[green]Config saved to {config_path}[/green]")
    return config


def validate_and_setup(config: Config) -> NotionClient | None:
    """Validate configuration and setup, returning client if successful."""
    console.print("\n[bold]VoiceInk to Notion[/bold]\n")
    
    # Check VoiceInk database
    db_path = find_voiceink_database()
    if db_path:
        try:
            transcriptions = read_transcriptions(db_path)
            console.print(f"├─ VoiceInk DB: [green]✓[/green] Found ({len(transcriptions)} transcriptions)")
        except Exception as e:
            console.print(f"├─ VoiceInk DB: [red]✗[/red] Error reading: {e}")
            return None
    else:
        console.print("├─ VoiceInk DB: [red]✗[/red] Not found")
        console.print("   [dim]Make sure VoiceInk is installed and has transcription history[/dim]")
        return None
    
    # Create client and test connection
    client = NotionClient(NotionConfig(
        api_key=config.notion_api_key,
        database_id=config.notion_database_id,
    ))
    
    conn_result = client.test_connection()
    if conn_result.success:
        console.print(f"├─ Notion: [green]✓[/green] Connected to \"{conn_result.database_name}\"")
    else:
        console.print(f"├─ Notion: [red]✗[/red] {conn_result.error}")
        return None
    
    # Check schema
    schema_result = client.check_schema()
    if schema_result.valid:
        console.print("├─ Schema: [green]✓[/green] Valid")
    else:
        console.print(f"├─ Schema: [yellow]![/yellow] Missing properties: {', '.join(schema_result.missing_properties)}")
        
        if Confirm.ask("   Create missing properties?", default=True):
            if client.setup_schema():
                console.print("├─ Schema: [green]✓[/green] Properties created")
            else:
                console.print("├─ Schema: [red]✗[/red] Failed to create properties")
                return None
        else:
            console.print("   [dim]Sync may fail without required properties[/dim]")
    
    # Load sync state
    state = load_sync_state()
    console.print(f"└─ Synced: [blue]{len(state.synced_ids)}[/blue] transcriptions")
    
    return client


def sync_command(args):
    """Run the sync process."""
    # Load or create config
    config_path = Path(args.config) if args.config else None
    
    try:
        config = load_config(config_path)
    except Exception:
        console.print("[yellow]No config found. Let's set it up.[/yellow]")
        config = interactive_setup()
        if not config:
            console.print("[red]Setup cancelled[/red]")
            return 1
    
    # Validate and setup
    client = validate_and_setup(config)
    if not client:
        return 1
    
    # Find VoiceInk database
    if config.voiceink_db_path:
        db_path = Path(config.voiceink_db_path)
    else:
        db_path = find_voiceink_database()
    
    # Load sync state
    state = load_sync_state()
    
    # On first run (or if cache not populated), fetch existing IDs from Notion
    if not state.notion_cache_populated:
        console.print("\n[dim]Fetching existing entries from Notion...[/dim]")
        notion_ids = client.get_all_synced_ids()
        if notion_ids:
            state.merge_notion_ids(notion_ids)
            save_sync_state(state)
            console.print(f"[dim]Found {len(notion_ids)} existing entries in Notion[/dim]")
    
    def do_sync() -> int:
        """Perform one sync cycle. Returns number synced."""
        try:
            transcriptions = read_transcriptions(db_path)
        except Exception as e:
            console.print(f"[red]Error reading VoiceInk:[/red] {e}")
            return 0
        
        # Find unsynced transcriptions
        unsynced = [t for t in transcriptions if not state.is_synced(t.id)]
        
        if not unsynced:
            return 0
        
        console.print(f"[yellow]Syncing {len(unsynced)} new transcriptions...[/yellow]")
        
        synced_count = 0
        for t in unsynced:
            result = client.create_transcription_page(
                text=t.text,
                timestamp=t.timestamp,
                duration=t.duration,
                enhanced_text=t.enhanced_text,
                prompt_name=t.prompt_name,
                voiceink_id=t.id,
            )
            
            if result:
                state.mark_synced(t.id)
                save_sync_state(state)
                text_preview = t.text[:40] + "..." if len(t.text) > 40 else t.text
                console.print(f"[green]✓[/green] {text_preview}")
                synced_count += 1
            else:
                console.print(f"[red]✗[/red] Failed: {t.id[:8]}...")
        
        return synced_count
    
    # Determine mode
    if args.once:
        # Single sync
        console.print()
        synced = do_sync()
        if synced:
            console.print(f"\n[green]Synced {synced} transcriptions[/green]")
        else:
            console.print("\n[blue]Everything is synced![/blue]")
    else:
        # Continuous sync (--always is default)
        console.print(f"\n[blue]Watching for new transcriptions (every {config.sync_interval_seconds}s)[/blue]")
        console.print("[dim]Press Ctrl+C to stop[/dim]\n")
        
        try:
            while True:
                synced = do_sync()
                if synced == 0:
                    # No new items, just show a dot to indicate we're alive
                    pass
                time.sleep(config.sync_interval_seconds)
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped[/yellow]")
    
    client.close()
    return 0


def status_command(args):
    """Show current sync status."""
    console.print("\n[bold blue]VoiceInk to Notion Status[/bold blue]\n")
    
    # Check VoiceInk database
    db_path = find_voiceink_database()
    if db_path:
        console.print(f"[green]VoiceInk DB:[/green] {db_path}")
        try:
            transcriptions = read_transcriptions(db_path)
            console.print(f"[green]Total transcriptions:[/green] {len(transcriptions)}")
        except Exception as e:
            console.print(f"[red]Error reading database:[/red] {e}")
    else:
        console.print("[red]VoiceInk DB:[/red] Not found")
    
    # Check sync state
    state = load_sync_state()
    console.print(f"[blue]Synced count:[/blue] {len(state.synced_ids)}")
    console.print(f"[blue]Notion cache:[/blue] {'Populated' if state.notion_cache_populated else 'Not populated'}")
    if state.last_sync_time:
        console.print(f"[blue]Last sync:[/blue] {state.last_sync_time}")
    
    # Check config
    try:
        config = load_config()
        console.print("[green]Config:[/green] Loaded")
        
        # Test Notion connection
        client = NotionClient(NotionConfig(
            api_key=config.notion_api_key,
            database_id=config.notion_database_id,
        ))
        conn_result = client.test_connection()
        if conn_result.success:
            console.print(f"[green]Notion:[/green] Connected to \"{conn_result.database_name}\"")
        else:
            console.print(f"[red]Notion:[/red] {conn_result.error}")
        client.close()
    except Exception as e:
        console.print(f"[red]Config:[/red] {e}")


def list_command(args):
    """List recent transcriptions."""
    db_path = find_voiceink_database()
    if not db_path:
        console.print("[red]VoiceInk database not found[/red]")
        return
    
    try:
        transcriptions = read_transcriptions(db_path)
    except Exception as e:
        console.print(f"[red]Error reading database:[/red] {e}")
        return
    
    if not transcriptions:
        console.print("[yellow]No transcriptions found[/yellow]")
        return
    
    # Sort by timestamp, newest first
    transcriptions.sort(key=lambda t: t.timestamp, reverse=True)
    
    # Show only the most recent N
    limit = args.limit or 10
    transcriptions = transcriptions[:limit]
    
    state = load_sync_state()
    
    table = Table(title=f"Recent Transcriptions (showing {len(transcriptions)})")
    table.add_column("Time", style="cyan")
    table.add_column("Duration", style="green")
    table.add_column("Text", style="white", max_width=60)
    table.add_column("Synced", style="yellow")
    
    for t in transcriptions:
        synced = "✓" if state.is_synced(t.id) else ""
        text_preview = t.text[:57] + "..." if len(t.text) > 60 else t.text
        table.add_row(
            t.timestamp.strftime("%Y-%m-%d %H:%M"),
            f"{t.duration:.1f}s",
            text_preview,
            synced,
        )
    
    console.print(table)


def reset_command(args):
    """Reset sync state."""
    if Confirm.ask("This will reset the sync state. Continue?", default=False):
        state_file = get_default_config_path().parent / "sync_state.json"
        if state_file.exists():
            state_file.unlink()
        console.print("[green]Sync state reset[/green]")
    else:
        console.print("[yellow]Cancelled[/yellow]")


def _get_python_path() -> str:
    """Get the path to the Python executable in the venv."""
    # Find the uv-managed venv python
    venv_python = Path(__file__).parent.parent / ".venv" / "bin" / "python"
    if venv_python.exists():
        return str(venv_python.resolve())
    # Fallback to current python
    return sys.executable


def _get_script_path() -> str:
    """Get the path to this module for running as a script."""
    return str(Path(__file__).parent.resolve())


def _find_uv_path() -> str:
    """Find the uv executable."""
    # Common locations for uv
    candidates = [
        Path.home() / ".cargo" / "bin" / "uv",
        Path.home() / ".local" / "bin" / "uv",
        Path("/opt/homebrew/bin/uv"),
        Path("/usr/local/bin/uv"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    # Fallback - assume it's in PATH
    return "uv"


def _generate_plist() -> str:
    """Generate the launchd plist XML."""
    project_dir = Path(__file__).parent.parent.resolve()
    uv_path = _find_uv_path()
    
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    
    # Use uv run to properly handle the venv and dependencies
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{LAUNCHD_LABEL}</string>
    
    <key>ProgramArguments</key>
    <array>
        <string>{uv_path}</string>
        <string>run</string>
        <string>voiceink-to-notion</string>
        <string>sync</string>
    </array>
    
    <key>WorkingDirectory</key>
    <string>{project_dir}</string>
    
    <key>RunAtLoad</key>
    <true/>
    
    <key>KeepAlive</key>
    <true/>
    
    <key>StandardOutPath</key>
    <string>{LOG_DIR}/stdout.log</string>
    
    <key>StandardErrorPath</key>
    <string>{LOG_DIR}/stderr.log</string>
    
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{Path.home()}/.cargo/bin:{Path.home()}/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>{Path.home()}</string>
    </dict>
    
    <key>ThrottleInterval</key>
    <integer>30</integer>
</dict>
</plist>
"""


def _is_service_running() -> bool:
    """Check if the launchd service is currently running."""
    try:
        result = subprocess.run(
            ["launchctl", "list", LAUNCHD_LABEL],
            capture_output=True,
            text=True
        )
        return result.returncode == 0
    except Exception:
        return False


def install_command(args):
    """Install as a launchd service."""
    console.print("\n[bold blue]Installing VoiceInk to Notion Service[/bold blue]\n")
    
    # First, validate config exists and works
    try:
        config = load_config()
    except Exception:
        console.print("[red]No config found. Run 'voiceink-to-notion sync' first to set up.[/red]")
        return 1
    
    # Test connection
    client = NotionClient(NotionConfig(
        api_key=config.notion_api_key,
        database_id=config.notion_database_id,
    ))
    conn_result = client.test_connection()
    client.close()
    
    if not conn_result.success:
        console.print(f"[red]Notion connection failed: {conn_result.error}[/red]")
        console.print("Fix the config before installing the service.")
        return 1
    
    # Check if already installed
    if LAUNCHD_PLIST_PATH.exists():
        if _is_service_running():
            console.print("[yellow]Service is already installed and running.[/yellow]")
            if Confirm.ask("Reinstall?", default=False):
                # Unload first
                subprocess.run(["launchctl", "unload", str(LAUNCHD_PLIST_PATH)], 
                             capture_output=True)
            else:
                return 0
    
    # Generate and write plist
    plist_content = _generate_plist()
    LAUNCHD_PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LAUNCHD_PLIST_PATH.write_text(plist_content)
    console.print(f"[green]Created:[/green] {LAUNCHD_PLIST_PATH}")
    
    # Load the service
    result = subprocess.run(
        ["launchctl", "load", str(LAUNCHD_PLIST_PATH)],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        console.print("[green]Service installed and started![/green]")
        console.print("\nThe service will:")
        console.print("  • Start automatically when you log in")
        console.print("  • Sync new transcriptions every 30 seconds")
        console.print("  • Restart automatically if it crashes")
        console.print(f"\nLogs: {LOG_DIR}/")
        console.print("\nCommands:")
        console.print("  voiceink-to-notion logs      # View logs")
        console.print("  voiceink-to-notion uninstall # Remove service")
    else:
        console.print(f"[red]Failed to load service:[/red] {result.stderr}")
        return 1
    
    return 0


def uninstall_command(args):
    """Uninstall the launchd service."""
    console.print("\n[bold blue]Uninstalling VoiceInk to Notion Service[/bold blue]\n")
    
    if not LAUNCHD_PLIST_PATH.exists():
        console.print("[yellow]Service is not installed.[/yellow]")
        return 0
    
    # Unload the service
    result = subprocess.run(
        ["launchctl", "unload", str(LAUNCHD_PLIST_PATH)],
        capture_output=True,
        text=True
    )
    
    # Remove the plist
    LAUNCHD_PLIST_PATH.unlink()
    console.print(f"[green]Removed:[/green] {LAUNCHD_PLIST_PATH}")
    
    console.print("[green]Service uninstalled.[/green]")
    console.print("\n[dim]Note: Logs are preserved at {LOG_DIR}/[/dim]")
    
    return 0


def logs_command(args):
    """View service logs."""
    stdout_log = LOG_DIR / "stdout.log"
    stderr_log = LOG_DIR / "stderr.log"
    
    if not stdout_log.exists() and not stderr_log.exists():
        console.print("[yellow]No logs found. Is the service installed?[/yellow]")
        console.print(f"[dim]Expected location: {LOG_DIR}/[/dim]")
        return 1
    
    lines = args.lines or 50
    
    if args.follow:
        # Use tail -f for live following
        console.print(f"[dim]Following logs (Ctrl+C to stop)...[/dim]\n")
        try:
            subprocess.run(["tail", "-f", str(stdout_log), str(stderr_log)])
        except KeyboardInterrupt:
            pass
    else:
        # Show recent logs
        if stdout_log.exists():
            console.print(f"[bold]== stdout.log (last {lines} lines) ==[/bold]")
            content = stdout_log.read_text()
            recent = "\n".join(content.strip().split("\n")[-lines:])
            console.print(recent or "[dim]Empty[/dim]")
        
        if stderr_log.exists():
            console.print(f"\n[bold]== stderr.log (last {lines} lines) ==[/bold]")
            content = stderr_log.read_text()
            recent = "\n".join(content.strip().split("\n")[-lines:])
            if recent:
                console.print(f"[red]{recent}[/red]")
            else:
                console.print("[dim]Empty[/dim]")
    
    return 0


def service_status_command(args):
    """Check if the background service is running."""
    if _is_service_running():
        console.print("[green]Service is running[/green]")
        
        # Show some stats
        stdout_log = LOG_DIR / "stdout.log"
        if stdout_log.exists():
            content = stdout_log.read_text()
            lines = content.strip().split("\n")
            if lines:
                console.print(f"[dim]Last log: {lines[-1][:80]}...[/dim]")
    else:
        if LAUNCHD_PLIST_PATH.exists():
            console.print("[yellow]Service is installed but not running[/yellow]")
            console.print("[dim]Try: launchctl load ~/Library/LaunchAgents/com.voiceink-to-notion.sync.plist[/dim]")
        else:
            console.print("[yellow]Service is not installed[/yellow]")
            console.print("[dim]Run: voiceink-to-notion install[/dim]")
    
    return 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Sync VoiceInk transcriptions to Notion"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Sync command
    sync_parser = subparsers.add_parser("sync", help="Sync transcriptions to Notion")
    sync_parser.add_argument("-c", "--config", help="Path to config file")
    sync_parser.add_argument("--once", action="store_true", help="Sync once and exit")
    sync_parser.add_argument("--always", action="store_true", help="Run continuously (default)")
    sync_parser.set_defaults(func=sync_command)
    
    # Status command
    status_parser = subparsers.add_parser("status", help="Show sync status")
    status_parser.set_defaults(func=status_command)
    
    # List command
    list_parser = subparsers.add_parser("list", help="List recent transcriptions")
    list_parser.add_argument("-n", "--limit", type=int, help="Number to show")
    list_parser.set_defaults(func=list_command)
    
    # Reset command
    reset_parser = subparsers.add_parser("reset", help="Reset sync state")
    reset_parser.set_defaults(func=reset_command)
    
    # Install command (launchd service)
    install_parser = subparsers.add_parser("install", help="Install as background service (launchd)")
    install_parser.set_defaults(func=install_command)
    
    # Uninstall command
    uninstall_parser = subparsers.add_parser("uninstall", help="Remove background service")
    uninstall_parser.set_defaults(func=uninstall_command)
    
    # Logs command
    logs_parser = subparsers.add_parser("logs", help="View service logs")
    logs_parser.add_argument("-n", "--lines", type=int, help="Number of lines to show (default 50)")
    logs_parser.add_argument("-f", "--follow", action="store_true", help="Follow logs in real-time")
    logs_parser.set_defaults(func=logs_command)
    
    # Service status command
    service_parser = subparsers.add_parser("service", help="Check background service status")
    service_parser.set_defaults(func=service_status_command)
    
    args = parser.parse_args()
    
    if not args.command:
        # Default to sync
        args.command = "sync"
        args.config = None
        args.once = False
        args.always = True
        args.func = sync_command
    
    return args.func(args) or 0


if __name__ == "__main__":
    sys.exit(main())
