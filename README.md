# Modrinth Modpack Installer

A Python tool to install and update [Modrinth](https://modrinth.com) modpacks on dedicated Minecraft servers. Automatically filters out client-only mods that would crash or bloat your server.

## Features

- **Smart client-mod filtering** - Automatically skips client-only mods based on modpack metadata and configurable blacklist
- **Preserve custom mods** - Keep your server-specific mods (Geyser, ViaVersion, etc.) during updates
- **Parallel downloads** - Fast installation with concurrent downloads
- **Permission handling** - Optionally fix file ownership for specific server users
- **Version tracking** - Knows what's installed, only updates when needed

## Requirements

- Python 3.10+
- PyYAML (`pip install pyyaml`)

## Installation

```bash
git clone https://github.com/turbootzz/mrpack-installer.git
cd mrpack-installer
pip install -r requirements.txt
```

## Quick Start

1. Edit `config.yaml` with your modpack ID and server path:
   ```yaml
   modpack_id: "your-modpack-id"
   instance_dir: "/path/to/your/minecraft/server"
   ```

2. Run the installer:
   ```bash
   python mrpack-installer.py install
   ```

## Configuration

### Finding the Modpack ID

The modpack ID is in the Modrinth URL:
- `modrinth.com/modpack/cobblemon-modpack` → ID is `cobblemon-modpack`
- Or use the project ID from the modpack page (e.g., `Jkb29YJU`)

### Configuration Options

```yaml
# Modrinth modpack project ID
modpack_id: "your-modpack-id"

# Path to your Minecraft server (should contain the 'mods' folder)
instance_dir: "/path/to/minecraft/server"

# Optional: Fix file permissions after install
permissions:
  user: "minecraft"   # Set to null to skip
  group: "minecraft"

# Mods to keep during updates (partial matching)
preserved_mods:
  - geyser
  - viaversion
  - spark

# Client-only mods to skip (partial matching)
client_only_mods:
  - modmenu
  - iris
  - sodium-extra
  # ... see config.yaml.example for full list
```

## Usage

```bash
# Check current vs latest version
python mrpack-installer.py check

# Fresh install (clears mods, preserves custom)
python mrpack-installer.py install

# Update to latest version
python mrpack-installer.py update

# Force reinstall current version
python mrpack-installer.py force-update

# Use a different config file
python mrpack-installer.py -c /path/to/config.yaml install
```

## How It Works

1. **Fetches modpack info** from Modrinth API
2. **Downloads the .mrpack file** (which is a zip containing mod list + overrides)
3. **Parses `modrinth.index.json`** to get the list of mods
4. **Filters out client-only mods** using:
   - The `env.server: "unsupported"` field in modpack metadata
   - Your configured `client_only_mods` blacklist patterns
5. **Downloads server-compatible mods** in parallel
6. **Processes overrides folder** (configs, additional mods) with same filtering
7. **Fixes permissions** if configured
8. **Tracks installed version** for future updates

## Preserving Custom Mods

Mods matching patterns in `preserved_mods` are never removed during updates. This is useful for:
- Proxy mods (FabricProxy-Lite)
- Cross-version support (ViaVersion, ViaFabric, ViaBackwards)
- Bedrock support (Geyser, Floodgate)
- Performance monitoring (Spark)

You can also place mods in a `mods/user/` subdirectory - this folder is never touched by the installer.

## Server Panel Examples

<details>
<summary><b>CubeCoders AMP</b></summary>

```yaml
modpack_id: "your-modpack-id"
instance_dir: "/home/amp/.ampdata/instances/YourInstance/Minecraft"
permissions:
  user: "amp"
  group: "amp"
```
</details>

<details>
<summary><b>Pterodactyl</b></summary>

```yaml
modpack_id: "your-modpack-id"
instance_dir: "/var/lib/pterodactyl/volumes/XXXX-XXXX"
permissions:
  user: "pterodactyl"
  group: "pterodactyl"
```
</details>

<details>
<summary><b>Standalone Server</b></summary>

```yaml
modpack_id: "your-modpack-id"
instance_dir: "/opt/minecraft/server"
permissions:
  user: null  # Skip permission fixing
  group: null
```
</details>

## Troubleshooting

### Permission Denied
Run with sudo or as a user with write access to the instance directory.

### Mods Not Loading
Make sure the server is using the correct mod loader (Fabric/Quilt/Forge) and Minecraft version matching the modpack.

### Server Crashes After Install
Check if any client-only mods slipped through. Add them to `client_only_mods` in your config and reinstall:
```bash
python mrpack-installer.py force-update
```

### Missing Dependencies
Some modpacks have mods with dependencies not included. Check the crash log and manually add required mods.

## License

MIT License - see [LICENSE](LICENSE)

## Contributing

PRs welcome! Especially for:
- Expanding the default client-only mod list
- Adding support for other modpack formats
- Improving error handling