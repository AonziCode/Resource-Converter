# Aonz's Resource Converter

Update or downgrade your Minecraft **mods, plugins, modpacks, shaders, resource packs and datapacks** to any version with one click.

Made for players, and especially **server owners** who need to bring a whole folder of mods or plugins up to date (or back down) quickly.

## Features

- **One-click conversion** of a whole folder or any selection of files
- **Update or downgrade** to any Minecraft version you pick
- **Six content types** in one app: mods, plugins, modpacks, shaders, resource packs, datapacks
- **Accurate file identification** using file hashes, not file names
- **Verified downloads** checked against Modrinth's checksums
- **Safe by design**: your original files are never touched
- **Live log, progress bar and summary** showing what worked and why anything failed

## How it works

1. You choose a folder (or individual files), the target Minecraft version and, where relevant, the loader or platform.
2. The app calculates a SHA-512 hash of each file and asks [Modrinth](https://modrinth.com) which project it belongs to.
3. It looks up the newest release of that project that matches your target version and loader.
4. It downloads the file and verifies it against Modrinth's checksum. A mismatched file is deleted.
5. Converted files are saved to a separate output folder, and you get a summary of successes and failures.

## Supported content

| Type | File types | Loader / platform options |
|------|-----------|---------------------------|
| Mods | `.jar` | Fabric, Forge, NeoForge, Quilt |
| Plugins | `.jar` | Bukkit, BungeeCord, Folia, Paper, Purpur, Spigot, Velocity, Waterfall |
| Modpacks | `.mrpack`, `.zip` | Fabric, Forge, NeoForge, Quilt |
| Shaders | `.zip` | Iris, OptiFine |
| Resource packs | `.zip` | none needed |
| Datapacks | `.zip` | none needed |

## Requirements

- **Windows** (the "open output folder" button uses a Windows-only call)
- **Python 3.9 or newer**
- An internet connection

The two dependencies, `pywebview` and `aiohttp`, are installed automatically the first time you run the app.

## Getting started

1. Download or clone this repository.
2. Keep `app.py` and `index.html` in the same folder.
3. Run:

   ```
   python app.py
   ```

4. Pick a converter on the left, choose your files, select the target version and loader, and press **Convert**.

## Where do converted files go?

By default:

```
Documents/Aonzi's mod updator/Updated mods
```

You can change the output location from inside the app.

## Limitations

- Only files that exist on **Modrinth** can be identified. Files that are only on CurseForge, SpigotMC or elsewhere will show up as failures.
- If a project has no release for your chosen version and loader, that file is reported as failed with the reason. The app does not guess.
- The file must match the selected converter type (for example, a mod file in the Plugin converter will be rejected).
- Always back up your server or instance and test the converted files. Newer mod versions can change configs or break compatibility with other mods.

## Project structure

```
app.py       Backend: hashing, Modrinth API calls, downloads, progress events
index.html   Frontend interface shown in the desktop window
```

The app is a small Python backend with an HTML interface, shown in a native window through `pywebview`.

## Roadmap ideas

- CurseForge fallback for files not on Modrinth
- Hangar support for plugins
- Cross-platform support (macOS and Linux)

## Credits

Created by **@aonzi**. Mod data and downloads are provided by the [Modrinth API](https://docs.modrinth.com). This project is not affiliated with Mojang, Microsoft or Modrinth.

## License

Add your license here (for example MIT).
