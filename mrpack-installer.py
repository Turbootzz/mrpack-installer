#!/usr/bin/env python3
"""
Modrinth Modpack Installer for Minecraft Servers

A tool to install and update Modrinth modpacks on dedicated servers,
automatically filtering out client-only mods.

Usage:
    python mrpack-installer.py install       # Fresh install
    python mrpack-installer.py update        # Smart update
    python mrpack-installer.py force-update  # Reinstall current version
    python mrpack-installer.py check         # Check versions
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

import yaml

# Cross-platform permission handling
IS_UNIX = sys.platform != "win32"
if IS_UNIX:
    import pwd
    import grp


@dataclass
class Config:
    """Configuration loaded from config.yaml"""
    modpack_id: str
    instance_dir: Path
    perm_user: Optional[str] = None
    perm_group: Optional[str] = None
    preserved_mods: list[str] = field(default_factory=list)
    client_only_mods: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, config_path: Path) -> "Config":
        """Load configuration from YAML file."""
        with open(config_path) as f:
            data = yaml.safe_load(f)

        permissions = data.get("permissions", {}) or {}

        return cls(
            modpack_id=data["modpack_id"],
            instance_dir=Path(data["instance_dir"]),
            perm_user=permissions.get("user"),
            perm_group=permissions.get("group"),
            preserved_mods=data.get("preserved_mods", []),
            client_only_mods=data.get("client_only_mods", []),
        )


class ModpackInstaller:
    """Handles downloading and installing Modrinth modpacks."""

    API_BASE = "https://api.modrinth.com/v2"
    USER_AGENT = "mrpack-installer/1.0 (github.com/mrpack-installer)"
    MAX_WORKERS = 10

    def __init__(self, config: Config):
        self.config = config
        self.mods_dir = config.instance_dir / "mods"
        self.version_file = config.instance_dir / ".modpack_version"

    def _api_request(self, endpoint: str) -> dict:
        """Make a request to the Modrinth API."""
        url = f"{self.API_BASE}/{endpoint}"
        req = Request(url, headers={"User-Agent": self.USER_AGENT})

        try:
            with urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except (URLError, HTTPError) as e:
            print(f"✗ API request failed: {e}")
            sys.exit(1)

    def _download_file(
        self,
        url: str,
        dest: Path,
        expected_size: Optional[int] = None,
        expected_hashes: Optional[dict] = None
    ) -> bool:
        """Download a file from URL to destination with optional hash verification."""
        req = Request(url, headers={"User-Agent": self.USER_AGENT})

        try:
            with urlopen(req, timeout=60) as resp:
                data = resp.read()

            if expected_size and len(data) != expected_size:
                print(f"  ✗ Size mismatch for {dest.name}")
                return False

            # Verify hash if provided
            if expected_hashes:
                if "sha512" in expected_hashes:
                    actual_hash = hashlib.sha512(data).hexdigest()
                    if actual_hash != expected_hashes["sha512"]:
                        print(f"  ✗ SHA512 hash mismatch for {dest.name}")
                        return False
                elif "sha1" in expected_hashes:
                    actual_hash = hashlib.sha1(data).hexdigest()
                    if actual_hash != expected_hashes["sha1"]:
                        print(f"  ✗ SHA1 hash mismatch for {dest.name}")
                        return False

            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return True

        except Exception as e:
            print(f"  ✗ Failed to download {dest.name}: {e}")
            return False

    def _is_client_only(self, filename: str, env: Optional[dict] = None) -> bool:
        """Check if a mod is client-only based on env data and blacklist."""
        # Check env field from modpack metadata
        if env and env.get("server") == "unsupported":
            return True

        # Check against blacklist patterns
        filename_lower = filename.lower()
        for pattern in self.config.client_only_mods:
            if pattern.lower() in filename_lower:
                return True

        return False

    def _is_preserved(self, filename: str) -> bool:
        """Check if a mod should be preserved (not removed during updates)."""
        filename_lower = filename.lower()
        for pattern in self.config.preserved_mods:
            if pattern.lower() in filename_lower:
                return True
        return False

    def _fix_permissions(self, path: Path) -> None:
        """Fix file/directory permissions if configured (Unix only)."""
        if not IS_UNIX:
            return

        if not self.config.perm_user:
            return

        try:
            uid = pwd.getpwnam(self.config.perm_user).pw_uid
            gid = grp.getgrnam(self.config.perm_group or self.config.perm_user).gr_gid

            if path.is_dir():
                for root, dirs, files in os.walk(path):
                    os.chown(root, uid, gid)
                    for d in dirs:
                        os.chown(os.path.join(root, d), uid, gid)
                    for f in files:
                        os.chown(os.path.join(root, f), uid, gid)
            else:
                os.chown(path, uid, gid)

        except (KeyError, PermissionError) as e:
            print(f"  ⚠ Could not fix permissions: {e}")

    def get_latest_version(self) -> dict:
        """Fetch the latest version info from Modrinth."""
        versions = self._api_request(f"project/{self.config.modpack_id}/version")
        if not versions:
            print("✗ No versions found for modpack")
            sys.exit(1)
        return versions[0]  # API returns newest first

    def get_installed_version(self) -> Optional[str]:
        """Get the currently installed version, if any."""
        if self.version_file.exists():
            return self.version_file.read_text().strip()
        return None

    def _save_version(self, version_id: str) -> None:
        """Save the installed version ID."""
        self.version_file.write_text(version_id)
        self._fix_permissions(self.version_file)

    def check_versions(self) -> None:
        """Display current and latest version info."""
        installed = self.get_installed_version()
        latest = self.get_latest_version()

        print(f"Modpack: {self.config.modpack_id}")
        print(f"Installed: {installed or 'Not installed'}")
        print(f"Latest: {latest['version_number']} ({latest['id']})")

        if installed == latest["id"]:
            print("✓ Up to date!")
        elif installed:
            print("↑ Update available")
        else:
            print("→ Run 'install' to install")

    def clean_mods(self, keep_preserved: bool = True) -> None:
        """Remove mods from the mods directory."""
        if not self.mods_dir.exists():
            return

        for file in self.mods_dir.iterdir():
            if file.is_file() and file.suffix == ".jar":
                if keep_preserved and self._is_preserved(file.name):
                    print(f"  ✓ Preserving: {file.name}")
                    continue
                file.unlink()
                print(f"  ✗ Removed: {file.name}")

        # Keep user/ subdirectory intact
        user_dir = self.mods_dir / "user"
        if user_dir.exists():
            print(f"  ✓ Preserving: user/ directory")

    def install(self, force: bool = False) -> None:
        """Install the modpack."""
        latest = self.get_latest_version()
        installed = self.get_installed_version()

        version_id = latest["id"]
        version_num = latest["version_number"]

        if installed == version_id and not force:
            print(f"✓ Already installed: {version_num}")
            print("  Use 'force-update' to reinstall")
            return

        print(f"Installing {version_num}...")

        # Find mrpack file in version files
        mrpack_file = None
        for f in latest["files"]:
            if f["filename"].endswith(".mrpack"):
                mrpack_file = f
                break

        if not mrpack_file:
            print("✗ No .mrpack file found in version")
            sys.exit(1)

        # Download mrpack to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir = Path(tmpdir)
            mrpack_path = tmpdir / mrpack_file["filename"]

            print(f"Downloading {mrpack_file['filename']}...")
            if not self._download_file(mrpack_file["url"], mrpack_path):
                sys.exit(1)

            # Extract mrpack (it's a zip file)
            extract_dir = tmpdir / "extracted"
            with zipfile.ZipFile(mrpack_path, 'r') as zf:
                zf.extractall(extract_dir)

            # Parse modpack index
            index_path = extract_dir / "modrinth.index.json"
            if not index_path.exists():
                print("✗ Invalid mrpack: missing modrinth.index.json")
                sys.exit(1)

            with open(index_path) as f:
                index = json.load(f)

            # Clean existing mods
            print("\nCleaning mods directory...")
            self.mods_dir.mkdir(parents=True, exist_ok=True)
            self.clean_mods(keep_preserved=True)

            # Process files from index
            print("\nProcessing modpack files...")
            mods_to_download = []
            skipped_client = 0
            skipped_other = 0

            for file_entry in index.get("files", []):
                file_path = file_entry["path"]
                env = file_entry.get("env", {})

                # Skip non-mod files (resourcepacks, etc)
                if not file_path.startswith("mods/"):
                    skipped_other += 1
                    continue

                filename = Path(file_path).name

                # Skip client-only mods
                if self._is_client_only(filename, env):
                    print(f"  ⊘ Skipping client mod: {filename}")
                    skipped_client += 1
                    continue

                # Queue for download with hash verification
                download_url = file_entry["downloads"][0]
                file_size = file_entry.get("fileSize")
                file_hashes = file_entry.get("hashes", {})
                mods_to_download.append((download_url, filename, file_size, file_hashes))

            # Download mods in parallel
            print(f"\nDownloading {len(mods_to_download)} mods...")
            downloaded = 0
            failed = 0

            with ThreadPoolExecutor(max_workers=self.MAX_WORKERS) as executor:
                futures = {}
                for url, filename, size, hashes in mods_to_download:
                    dest = self.mods_dir / filename
                    future = executor.submit(self._download_file, url, dest, size, hashes)
                    futures[future] = filename

                for future in as_completed(futures):
                    filename = futures[future]
                    if future.result():
                        downloaded += 1
                        print(f"  ✓ {filename}")
                    else:
                        failed += 1

            # Process overrides
            overrides_dir = extract_dir / "overrides"
            server_overrides_dir = extract_dir / "server-overrides"

            override_mods = 0
            override_skipped = 0

            for override_src in [overrides_dir, server_overrides_dir]:
                if not override_src.exists():
                    continue

                override_mods_dir = override_src / "mods"
                if override_mods_dir.exists():
                    for mod_file in override_mods_dir.iterdir():
                        if not mod_file.is_file() or mod_file.suffix != ".jar":
                            continue

                        if self._is_client_only(mod_file.name):
                            print(f"  ⊘ Skipping override client mod: {mod_file.name}")
                            override_skipped += 1
                            continue

                        dest = self.mods_dir / mod_file.name
                        shutil.copy2(mod_file, dest)
                        override_mods += 1
                        print(f"  ✓ Override: {mod_file.name}")

                # Copy other override files (config, etc) - but not mods or client-overrides
                for item in override_src.iterdir():
                    if item.name == "mods":
                        continue

                    dest = self.config.instance_dir / item.name
                    if item.is_dir():
                        if dest.exists():
                            shutil.rmtree(dest)
                        shutil.copytree(item, dest)
                        print(f"  ✓ Override: {item.name}/")
                    else:
                        shutil.copy2(item, dest)
                        print(f"  ✓ Override: {item.name}")

            # Fix permissions (Unix only)
            if IS_UNIX and self.config.perm_user:
                print("\nFixing permissions...")
                self._fix_permissions(self.config.instance_dir)

            # Save version
            self._save_version(version_id)

            # Summary
            print(f"\n{'='*50}")
            print(f"Installation complete: {version_num}")
            print(f"  Downloaded: {downloaded} mods")
            print(f"  From overrides: {override_mods} mods")
            print(f"  Skipped (client-only): {skipped_client + override_skipped}")
            print(f"  Skipped (other): {skipped_other}")
            if failed:
                print(f"  Failed: {failed}")
            print(f"{'='*50}")


def main():
    parser = argparse.ArgumentParser(
        description="Install and update Modrinth modpacks for Minecraft servers"
    )
    parser.add_argument(
        "command",
        choices=["install", "update", "force-update", "check"],
        help="Command to run"
    )
    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to config file (default: config.yaml)"
    )

    args = parser.parse_args()

    # Find config file
    config_path = Path(args.config)
    if not config_path.exists():
        # Try looking next to the script
        script_dir = Path(__file__).parent
        config_path = script_dir / "config.yaml"

    if not config_path.exists():
        print(f"✗ Config file not found: {args.config}")
        print("  Create a config.yaml file (see README.md)")
        sys.exit(1)

    # Load config
    try:
        config = Config.load(config_path)
    except Exception as e:
        print(f"✗ Failed to load config: {e}")
        sys.exit(1)

    # Run command
    installer = ModpackInstaller(config)

    if args.command == "check":
        installer.check_versions()
    elif args.command == "install":
        installer.install()
    elif args.command == "update":
        installer.install()
    elif args.command == "force-update":
        installer.install(force=True)


if __name__ == "__main__":
    main()
