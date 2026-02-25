"""
Textual TUI for Preservica Upload Tool
"""

import os
import sys
import shutil
import tempfile
import asyncio
import threading
import subprocess
import argparse
from pathlib import Path
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import (
    DirectoryTree,
    Header,
    Footer,
    Static,
    Tree,
    Button,
    Label,
    ProgressBar,
    LoadingIndicator,
)
from textual.binding import Binding
from textual.reactive import reactive
from textual.message import Message
from textual import work
from dotenv import load_dotenv
from pyPreservica import (
    EntityAPI,
    UploadAPI,
)

# Load .env file if present (system environment variables take precedence)
load_dotenv()

# Get credentials from environment
USERNAME = os.getenv("PRESERVICA_USERNAME")
PASSWORD = os.getenv("PRESERVICA_PASSWORD")
SERVER = os.getenv("PRESERVICA_SERVER")
BUCKET = os.getenv("PRESERVICA_BUCKET")
# S3 upload threshold in MB (default: 100MB)
S3_THRESHOLD_MB = int(os.getenv("PRESERVICA_S3_THRESHOLD", "100"))


class UploadProgressMessage(Message):
    """Message sent when upload progress updates."""

    def __init__(self, percentage: int) -> None:
        self.percentage = percentage
        super().__init__()


class UploadProgressMessage(Message):
    """Message sent when upload progress updates."""

    def __init__(self, percentage: int) -> None:
        self.percentage = percentage
        super().__init__()


class UploadProgressCallback:
    """Callback class to update Textual progress bar during upload."""

    def __init__(self, filename: str, app):
        self._filename = filename
        self._size = float(os.path.getsize(filename))
        self._seen_so_far = 0
        self._lock = threading.Lock()
        self.app = app
        self._last_percentage = -1

    def __call__(self, bytes_amount):
        with self._lock:
            self._seen_so_far += bytes_amount
            percentage = int((self._seen_so_far / self._size) * 100)

            # Throttle: only update every 5% to avoid overwhelming the event loop
            if percentage >= self._last_percentage + 5 or (
                percentage == 100 and self._last_percentage != 100
            ):
                self._last_percentage = percentage
                # post_message is thread-safe and doesn't block
                self.app.post_message(UploadProgressMessage(percentage))


class PreservicaTree(Tree):
    """A tree widget for browsing Preservica folders."""

    def __init__(self, *args, **kwargs):
        super().__init__("Preservica Folders", *args, **kwargs)
        self.entity_client = None
        self.folder_map = {}  # Maps tree node IDs to folder UUIDs
        # Add initial loading message
        self.root.add_leaf("⏳ Loading folders...")

    async def on_mount(self) -> None:
        """Initialize the Preservica connection and load root folders."""
        try:
            self.entity_client = EntityAPI(
                username=USERNAME, password=PASSWORD, server=SERVER
            )
            # Clear loading message
            self.root.remove_children()
            await self.load_root_folders()
        except Exception as e:
            # Clear loading message and show error
            self.root.remove_children()
            self.root.add_leaf(f"❌ Error: {e}")

    async def load_root_folders(self) -> None:
        """Load root folders from Preservica."""
        try:
            # Get root folders (descendants with None parent)
            for entity in self.entity_client.descendants(None):
                if entity.entity_type.name == "FOLDER":
                    node = self.root.add(entity.title, expand=False)
                    self.folder_map[node.id] = entity.reference
                    # Add a placeholder to show it's expandable
                    node.add_leaf("Loading...")
                elif entity.entity_type.name == "ASSET":
                    # Add assets as non-selectable leaves
                    self.root.add_leaf(f"📄 {entity.title}")
        except Exception as e:
            self.root.add_leaf(f"Error loading folders: {e}")

    async def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Load child folders when a node is expanded."""
        node = event.node

        # Check if this is a folder node that needs loading
        if node.id in self.folder_map and node.children:
            # Remove placeholder
            for child in list(node.children):
                child.remove()

            # Load actual children
            folder_uuid = self.folder_map[node.id]
            try:
                for entity in self.entity_client.descendants(folder_uuid):
                    if entity.entity_type.name == "FOLDER":
                        child_node = node.add(entity.title, expand=False)
                        self.folder_map[child_node.id] = entity.reference
                        # Add placeholder for expandable folders
                        child_node.add_leaf("Loading...")
                    elif entity.entity_type.name == "ASSET":
                        # Add assets as non-selectable leaves
                        node.add_leaf(f"📄 {entity.title}")
            except Exception as e:
                node.add_leaf(f"Error: {e}")


class StatusBar(Static):
    """Status bar at the bottom showing current selections and messages."""

    message = reactive("")

    def render(self) -> str:
        return self.message

    def update_message(self, msg: str) -> None:
        self.message = msg


class PreservicaUploadApp(App):
    """Textual app for uploading files to Preservica."""

    # Disable command palette
    ENABLE_COMMAND_PALETTE = False

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("u", "upload", "Upload"),
    ]

    CSS = """
    Screen {
        layout: vertical;
    }
    
    Header {
        height: 1;
    }
    
    #panels-container {
        layout: horizontal;
        height: 1fr;
    }
    
    #local-panel {
        border: solid $primary;
        width: 1fr;
    }
    
    #preservica-panel {
        border: solid $secondary;
        width: 1fr;
    }
    
    .panel-title {
        background: $boost;
        color: $text;
        text-align: center;
        text-style: bold;
        height: 1;
    }
    
    DirectoryTree, PreservicaTree {
        height: 1fr;
    }
    
    StatusBar {
        background: $panel;
        color: $text;
        height: 1;
    }
    
    #progress-container {
        height: 3;
        padding: 1;
    }
    
    ProgressBar {
        height: 1;
    }
    
    #button-container {
        height: 3;
        align: center middle;
        layout: horizontal;
    }
    
    Button {
        margin: 0 1;
    }
    
    Footer {
        height: 1;
    }
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.selected_local_path: Path | None = None
        self.selected_preservica_folder: str | None = None
        self.upload_client = None

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()

        # Panels container (horizontal layout for side-by-side panels)
        with Horizontal(id="panels-container"):
            # Left panel: Local file system (start from current dir, can navigate up)
            with Container(id="local-panel"):
                yield Label("Local File System", classes="panel-title")
                # Start from current directory
                yield DirectoryTree(Path.cwd(), id="local-tree")

            # Right panel: Preservica folders
            with Container(id="preservica-panel"):
                yield Label("Preservica Folders", classes="panel-title")
                yield PreservicaTree(id="preservica-tree")

        # Status bar
        yield StatusBar(id="status-bar")

        # Progress bar container
        with Container(id="progress-container"):
            yield ProgressBar(id="progress-bar", show_eta=False)

        # Buttons
        with Horizontal(id="button-container"):
            yield Button("Upload Selected", id="upload-btn", variant="primary")
            yield Button("Refresh", id="refresh-btn", variant="default")

        yield Footer()

    async def on_mount(self) -> None:
        try:
            self.upload_client = UploadAPI(
                username=USERNAME, password=PASSWORD, server=SERVER
            )
            # Hide progress bar initially
            progress_bar = self.query_one("#progress-bar", ProgressBar)
            progress_bar.display = False

            self.update_status(
                "Ready. Select a local file and Preservica folder, then click Upload."
            )
        except Exception as e:
            self.update_status(f"Error initializing upload client: {e}")

    def on_directory_tree_file_selected(
        self, event: DirectoryTree.FileSelected
    ) -> None:
        """Handle local file selection."""
        self.selected_local_path = event.path
        self.update_status(f"Selected local file: {event.path.name}")

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """Handle local directory selection."""
        self.selected_local_path = event.path
        self.update_status(f"Selected local folder: {event.path.name}")

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        """Handle Preservica folder selection."""
        # Get the PreservicaTree widget
        tree = self.query_one("#preservica-tree", PreservicaTree)
        node = event.node
        # Only allow selection of nodes that are in folder_map (actual folders, not assets)
        if node.id in tree.folder_map:
            self.selected_preservica_folder = tree.folder_map[node.id]
            self.update_status(f"Selected Preservica folder: {node.label}")
        else:
            # Clear selection if an asset leaf is highlighted
            self.selected_preservica_folder = None
            self.update_status("Please select a Preservica folder (not an asset)")

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "upload-btn":
            self.action_upload()
        elif event.button.id == "refresh-btn":
            await self.action_refresh()

    def on_upload_progress_message(self, message: UploadProgressMessage) -> None:
        """Handle upload progress messages."""
        progress_bar = self.query_one("#progress-bar", ProgressBar)
        progress_bar.update(progress=message.percentage)

    @work(thread=True, exclusive=True)
    def action_upload(self) -> None:
        """Upload the selected file to the selected Preservica folder."""
        if not self.selected_local_path:
            self.call_from_thread(
                self.update_status, "❌ Please select a local file or folder first"
            )
            return

        if not self.selected_preservica_folder:
            self.call_from_thread(
                self.update_status, "❌ Please select a Preservica folder first"
            )
            return

        try:
            # Show file size
            file_size_mb = self.selected_local_path.stat().st_size / (1024 * 1024)
            self.call_from_thread(
                self.update_status, f"📁 File size: {file_size_mb:.2f} MB"
            )

            # Show folder being uploaded to
            self.call_from_thread(
                self.update_status,
                f"📤 Uploading to folder: {self.selected_preservica_folder.title}",
            )

            if self.selected_local_path.is_file():
                # Upload single file
                from pyPreservica import simple_asset_package

                # Create asset package
                self.call_from_thread(
                    self.update_status, f"📦 Creating asset package..."
                )
                zip_package = simple_asset_package(
                    preservation_file=str(self.selected_local_path),
                    parent_folder=self.selected_preservica_folder,
                )

                # Show package info
                package_size_mb = os.path.getsize(zip_package) / (1024 * 1024)
                self.call_from_thread(
                    self.update_status,
                    f"📦 Package created: {os.path.basename(zip_package)}",
                )
                self.call_from_thread(
                    self.update_status, f"📦 Package size: {package_size_mb:.2f} MB"
                )

                # Determine upload method based on package size
                use_s3 = package_size_mb >= S3_THRESHOLD_MB
                if use_s3:
                    self.call_from_thread(
                        self.update_status,
                        f"📦 Large file detected - using S3 upload...",
                    )

                # Upload the package
                self.call_from_thread(self.update_status, f"⬆️  Starting upload...")

                # Show progress bar
                def show_progress():
                    progress_bar = self.query_one("#progress-bar", ProgressBar)
                    progress_bar.display = True
                    progress_bar.update(total=100, progress=0)

                self.call_from_thread(show_progress)

                # Create callback for upload progress
                callback = UploadProgressCallback(zip_package, self)

                # Choose upload method based on size
                if use_s3:
                    result = self.upload_client.upload_zip_package_to_S3(
                        path_to_zip_package=zip_package,
                        bucket_name=BUCKET,
                        folder=self.selected_preservica_folder,
                        callback=callback,
                        delete_after_upload=True,
                    )
                else:
                    result = self.upload_client.upload_zip_package(
                        path_to_zip_package=zip_package,
                        folder=self.selected_preservica_folder,
                        callback=callback,
                        delete_after_upload=True,
                    )

                # Upload complete
                def hide_progress():
                    progress_bar = self.query_one("#progress-bar", ProgressBar)
                    progress_bar.display = False

                self.call_from_thread(hide_progress)
                self.call_from_thread(
                    self.update_status,
                    f"✅ Upload complete! Check Preservica web UI for ingest progress.",
                )

            elif self.selected_local_path.is_dir():
                # Upload folder by zipping it first
                self.call_from_thread(
                    self.update_status,
                    f"📦 Zipping folder {self.selected_local_path.name}...",
                )

                # Create a temporary zip file of the folder
                temp_dir = tempfile.gettempdir()
                zip_basename = self.selected_local_path.name
                zip_path = os.path.join(temp_dir, zip_basename)

                # Create zip archive (without .zip extension, shutil adds it)
                zip_file = shutil.make_archive(
                    zip_path,
                    "zip",
                    self.selected_local_path.parent,
                    self.selected_local_path.name,
                )

                # Show package info
                package_size_mb = os.path.getsize(zip_file) / (1024 * 1024)
                self.call_from_thread(
                    self.update_status,
                    f"📦 Package created: {os.path.basename(zip_file)}",
                )
                self.call_from_thread(
                    self.update_status, f"📦 Package size: {package_size_mb:.2f} MB"
                )

                # Determine upload method based on package size
                use_s3 = package_size_mb >= S3_THRESHOLD_MB
                if use_s3:
                    self.call_from_thread(
                        self.update_status,
                        f"📦 Large file detected - using S3 upload...",
                    )

                # Upload the zip directly
                self.call_from_thread(self.update_status, f"⬆️  Starting upload...")

                # Show progress bar
                def show_progress():
                    progress_bar = self.query_one("#progress-bar", ProgressBar)
                    progress_bar.display = True
                    progress_bar.update(total=100, progress=0)

                self.call_from_thread(show_progress)

                # Create callback for upload progress
                callback = UploadProgressCallback(zip_file, self)

                # Choose upload method based on size
                if use_s3:
                    result = self.upload_client.upload_zip_package_to_S3(
                        path_to_zip_package=zip_file,
                        bucket_name=BUCKET,
                        folder=self.selected_preservica_folder,
                        callback=callback,
                        delete_after_upload=True,
                    )
                else:
                    result = self.upload_client.upload_zip_package(
                        path_to_zip_package=zip_file,
                        folder=self.selected_preservica_folder,
                        callback=callback,
                        delete_after_upload=True,
                    )

                # Upload complete
                def hide_progress():
                    progress_bar = self.query_one("#progress-bar", ProgressBar)
                    progress_bar.display = False

                self.call_from_thread(hide_progress)
                self.call_from_thread(
                    self.update_status,
                    f"✅ Upload complete! Check Preservica web UI for ingest progress.",
                )

            else:
                self.call_from_thread(
                    self.update_status,
                    "❌ Selected path is neither a file nor a folder",
                )

        except Exception as e:
            import traceback

            error_detail = traceback.format_exc()
            self.call_from_thread(self.update_status, f"❌ Upload failed: {e}")

            def hide_progress_on_error():
                progress_bar = self.query_one("#progress-bar", ProgressBar)
                progress_bar.display = False

            self.call_from_thread(hide_progress_on_error)
            # Log full error to see what's happening
            with open("upload_error.log", "w") as f:
                f.write(error_detail)

    async def action_refresh(self) -> None:
        """Refresh the Preservica folder tree."""
        tree = self.query_one("#preservica-tree", PreservicaTree)
        tree.clear()
        tree.folder_map.clear()
        await tree.load_root_folders()
        self.update_status("Refreshed Preservica folders")

    def update_status(self, message: str) -> None:
        """Update the status bar message."""
        status_bar = self.query_one("#status-bar", StatusBar)
        status_bar.update_message(message)


def main():
    """Entry point for the console script."""
    parser = argparse.ArgumentParser(
        description="Preservica Upload Tool - TUI for uploading files to Preservica"
    )
    parser.add_argument(
        "-u",
        "--update",
        "--upgrade",
        action="store_true",
        help="Update the tool by pulling the latest changes from git",
    )

    args = parser.parse_args()

    if args.update:
        # Find the installation directory using __file__
        install_dir = Path(__file__).parent.resolve()

        print(f"Updating preservica-upload from: {install_dir}")
        print("Running git pull...\n")

        try:
            result = subprocess.run(
                ["git", "pull"],
                cwd=install_dir,
                capture_output=True,
                text=True,
                check=True,
            )
            print(result.stdout)
            if result.stderr:
                print(result.stderr)
            print(
                "\n✅ Update complete! Run 'preservica-upload' to use the updated version."
            )
        except subprocess.CalledProcessError as e:
            print(f"❌ Error updating: {e}")
            print(e.stderr)
            sys.exit(1)
        except FileNotFoundError:
            print("❌ Error: git command not found. Please install git.")
            sys.exit(1)

        return

    # Normal operation - launch the TUI
    app = PreservicaUploadApp()
    app.run()


if __name__ == "__main__":
    main()
