"""Aonzi's Resource Converter desktop application.

Run this file with Python.  It installs its two runtime dependencies when needed,
then serves the local HTML interface inside a pywebview window.
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


def ensure_runtime_packages() -> None:
    """Install the small runtime surface before importing either dependency."""
    required = {"webview": "pywebview", "aiohttp": "aiohttp"}
    missing = [package for module, package in required.items() if importlib.util.find_spec(module) is None]
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", *missing])


ensure_runtime_packages()

import aiohttp  # noqa: E402
import webview  # noqa: E402


API_ROOT = "https://api.modrinth.com/v2"
USER_AGENT = "Aonzi-Resource-Converter/1.0 (desktop application)"
CONTENT_TYPES = {
    "mod": {"extensions": {".jar"}, "label": "mods", "folder": "Mods"},
    "resourcepack": {"extensions": {".zip"}, "label": "resource packs", "folder": "Resource Packs"},
    "datapack": {"extensions": {".zip"}, "label": "data packs", "folder": "Datapacks"},
    "shader": {"extensions": {".zip"}, "label": "shaders", "folder": "Shaders"},
    "modpack": {"extensions": {".mrpack", ".zip"}, "label": "modpacks", "folder": "Modpacks"},
    "plugin": {"extensions": {".jar"}, "label": "plugins", "folder": "Plugins"},
}


class ModUpdaterAPI:
    def __init__(self) -> None:
        self._output_root = Path.home() / "Documents"
        self.processed_resources_dir = self._output_root / "Processed resources"
        self._ensure_output_directories()
        # Public attributes of a js_api object are recursively inspected by
        # pywebview. Keeping the native WinForms window private avoids noisy
        # accessibility/UI-thread errors in the Windows console.
        self._window: Any = None
        self._events: list[dict[str, str]] = []
        self._event_lock = threading.Lock()
        self._running = False
        self._summary: dict[str, Any] | None = None
        self._progress = 0.0

    def set_window(self, window: Any) -> None:
        self._window = window

    def minimize(self) -> None:
        if self._window is not None:
            self._window.minimize()

    def close(self) -> None:
        if self._window is not None:
            self._window.destroy()

    def get_paths(self) -> dict[str, str]:
        return {"processed": str(self.processed_resources_dir)}

    def _ensure_output_directories(self) -> None:
        self.processed_resources_dir.mkdir(parents=True, exist_ok=True)
        for config in CONTENT_TYPES.values():
            (self.processed_resources_dir / config["folder"]).mkdir(exist_ok=True)

    def _output_directory(self, content_type: str) -> Path:
        destination = self.processed_resources_dir / CONTENT_TYPES[content_type]["folder"]
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    def get_game_versions(self) -> list[str]:
        """Load Modrinth's current game-version tags, newest first."""
        async def fetch_versions() -> list[str]:
            timeout = aiohttp.ClientTimeout(total=20)
            async with aiohttp.ClientSession(timeout=timeout, headers={"User-Agent": USER_AGENT}) as session:
                versions = await self._request(session, "GET", "/tag/game_version")
            versions.sort(key=lambda item: item.get("date", ""), reverse=True)
            return [item["version"] for item in versions if item.get("version")]

        return asyncio.run(fetch_versions())

    def choose_output_folder(self) -> dict[str, str] | None:
        """Choose a parent folder for the processed resources directory."""
        if self._window is None:
            return None
        selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
        if not selected:
            return None
        self._output_root = Path(selected[0] if isinstance(selected, (tuple, list)) else selected)
        self.processed_resources_dir = self._output_root / "Processed resources"
        self._ensure_output_directories()
        return self.get_paths()

    def open_output_directory(self) -> bool:
        try:
            self._ensure_output_directories()
            os.startfile(str(self.processed_resources_dir))
            return True
        except OSError:
            return False

    def choose_files(self, mode: str, content_type: str = "mod") -> list[str]:
        if self._window is None:
            return []
        config = CONTENT_TYPES.get(content_type, CONTENT_TYPES["mod"])
        extensions = config["extensions"]
        file_pattern = ";".join(f"*{extension}" for extension in sorted(extensions))
        if mode == "folder":
            selected = self._window.create_file_dialog(webview.FileDialog.FOLDER)
            if not selected:
                return []
            folder = Path(selected[0] if isinstance(selected, (tuple, list)) else selected)
            return [str(path) for path in folder.rglob("*") if path.is_file() and path.suffix.lower() in extensions]
        selected = self._window.create_file_dialog(
            webview.FileDialog.OPEN,
            allow_multiple=True,
            file_types=(f"Minecraft {config['label']} ({file_pattern})", "All files (*.*)"),
        )
        return list(selected or [])

    def choose_jars(self, mode: str) -> list[str]:
        """Compatibility endpoint for older local copies of the frontend."""
        return self.choose_files(mode, "mod")

    def start_update(self, files: list[str], target_version: str, loader: str, content_type: str = "mod") -> dict[str, Any]:
        if self._running:
            return {"ok": False, "error": "An update is already running."}
        config = CONTENT_TYPES.get(content_type)
        if not config:
            return {"ok": False, "error": "That converter type is not supported."}
        file_paths = [Path(file) for file in files if Path(file).is_file() and Path(file).suffix.lower() in config["extensions"]]
        if not file_paths:
            return {"ok": False, "error": f"Choose at least one {config['label']} file first."}
        self._running = True
        self._summary = None
        with self._event_lock:
            self._events.clear()
            self._progress = 4.0
        threading.Thread(
            target=lambda: asyncio.run(self._update_all(file_paths, target_version, loader.lower(), content_type)),
            daemon=True,
        ).start()
        return {"ok": True}

    def poll_events(self) -> dict[str, Any]:
        with self._event_lock:
            events, self._events = self._events[:], []
            progress = self._progress
        return {"events": events, "running": self._running, "summary": self._summary, "progress": round(progress, 1)}

    def clear_console(self) -> None:
        with self._event_lock:
            self._events.clear()

    def _log(self, message: str, level: str = "info") -> None:
        event = {"time": datetime.now().strftime("%H:%M:%S"), "message": message, "level": level}
        with self._event_lock:
            self._events.append(event)

    def _set_progress(self, value: float) -> None:
        """Publish real workflow progress for the UI rather than inferring it from logs."""
        with self._event_lock:
            self._progress = max(0.0, min(100.0, value))

    @staticmethod
    def _sha512(path: Path) -> str:
        digest = hashlib.sha512()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _best_file(version: dict[str, Any]) -> dict[str, Any] | None:
        files = version.get("files") or []
        return next((item for item in files if item.get("primary")), files[0] if files else None)

    async def _request(self, session: aiohttp.ClientSession, method: str, path: str, **kwargs: Any) -> Any:
        async with session.request(method, f"{API_ROOT}{path}", **kwargs) as response:
            if response.status >= 400:
                detail = await response.text()
                raise RuntimeError(f"Modrinth returned {response.status}: {detail[:180]}")
            return await response.json()

    async def _download(self, session: aiohttp.ClientSession, file_data: dict[str, Any], destination: Path) -> Path:
        filename = file_data.get("filename") or "downloaded-mod.jar"
        target = destination / filename
        async with session.get(file_data["url"]) as response:
            response.raise_for_status()
            total = int(response.headers.get("Content-Length", 0))
            written = 0
            with target.open("wb") as handle:
                async for chunk in response.content.iter_chunked(1024 * 128):
                    handle.write(chunk)
                    written += len(chunk)
                    if total and written % (1024 * 1024) < len(chunk):
                        self._log(f"Downloading {filename}: {written * 100 // total}%")
        expected = file_data.get("hashes", {}).get("sha512")
        if expected and self._sha512(target) != expected:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"Checksum verification failed for {filename}.")
        return target

    async def _find_version(
        self, session: aiohttp.ClientSession, project_id: str, target: str, loader: str, content_type: str = "mod"
    ) -> dict[str, Any] | None:
        params = {"game_versions": json.dumps([target])}
        if content_type in {"mod", "shader", "plugin", "modpack"}:
            params["loaders"] = json.dumps([loader])
        versions = await self._request(session, "GET", f"/project/{project_id}/version", params=params)
        return versions[0] if versions else None

    async def _update_all(self, paths: list[Path], target: str, loader: str, content_type: str) -> None:
        successes: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        total_paths = len(paths)
        self._set_progress(4)
        content_label = CONTENT_TYPES[content_type]["label"]
        loader_label = f" / {loader.title()}" if content_type in {"mod", "shader", "plugin", "modpack"} else ""
        self._log(f"Starting {len(paths)} {content_label} conversion(s) for Minecraft {target}{loader_label}.")
        timeout = aiohttp.ClientTimeout(total=180)
        headers = {"User-Agent": USER_AGENT}
        try:
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                self._log("Hashing selected mod files with SHA-512…")
                hashes: dict[str, Path] = {}
                for hash_index, path in enumerate(paths, start=1):
                    try:
                        hashes[self._sha512(path)] = path
                        self._log(f"Hashed {path.name}")
                    except Exception as error:
                        failures.append({"file": path.name, "reason": f"Could not hash file: {error}"})
                    self._set_progress(4 + 12 * hash_index / total_paths)
                if not hashes:
                    return
                self._log("Querying Modrinth for matching source files…")
                self._set_progress(17)
                matches = await self._request(session, "POST", "/version_files", json={"hashes": list(hashes), "algorithm": "sha512"})
                self._set_progress(20)
                for index, (digest, original) in enumerate(hashes.items(), start=1):
                    try:
                        self._set_progress(20 + 75 * (index - 1) / len(hashes))
                        source = matches.get(digest)
                        if not source:
                            raise RuntimeError("This file is not indexed by Modrinth, so its project could not be identified.")
                        project_id = source.get("project_id")
                        project = await self._request(session, "GET", f"/project/{project_id}")
                        project_type = project.get("project_type")
                        loader_types = {"mod", "plugin"}
                        if project_type != content_type and not {project_type, content_type} <= loader_types:
                            raise RuntimeError(f"This file belongs to a {project_type or 'different'} project, not {content_label}.")
                        candidate = await self._find_version(session, project_id, target, loader, content_type)
                        if not candidate:
                            target_description = f"{target}/{loader.title()}" if content_type in {"mod", "shader", "plugin", "modpack"} else target
                            raise RuntimeError(f"Specified version '{target_description}' wasn't found on Modrinth for this {content_label} project.")
                        file_data = self._best_file(candidate)
                        if not file_data:
                            raise RuntimeError("The compatible Modrinth release contains no downloadable jar.")
                        self._log(f"Compatible update found for {original.name}: {candidate.get('version_number', 'unknown version')}")
                        saved = await self._download(session, file_data, self._output_directory(content_type))
                        successes.append({
                            "original": original.name,
                            "updated": saved.name,
                            "version": candidate.get("version_number", "Unknown"),
                        })
                        self._log(f"Updated {original.name} → {saved.name}", "success")
                    except Exception as error:
                        failures.append({"file": original.name, "reason": str(error)})
                        self._log(f"Failed {original.name}: {error}", "error")
                    self._log(f"Progress: {index}/{len(hashes)} files processed.")
                    self._set_progress(20 + 75 * index / len(hashes))
        except Exception as error:
            self._log(f"Update session failed: {error}", "error")
            failures.append({"file": "Update session", "reason": str(error)})
        finally:
            self._summary = {"successes": successes, "failures": failures, "target": target, "loader": loader}
            self._running = False
            self._set_progress(100)
            self._log(f"Finished: {len(successes)} updated, {len(failures)} failed.", "success" if not failures else "warning")


def main() -> None:
    api = ModUpdaterAPI()
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    html_file = bundle_root / "index.html"
    # A custom drag region is safer than easy_drag: only the page's slim top
    # bar can move the frameless window, never cards, lists, or controls.
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
    window = webview.create_window(
        "Aonzi's Resource Converter",
        html_file.as_uri(),
        js_api=api,
        width=1440,
        height=840,
        min_size=(1080, 650),
        frameless=True,
        easy_drag=False,
        background_color="#f3f4f6",
    )
    api.set_window(window)
    webview.start(debug=False)


if __name__ == "__main__":
    main()
