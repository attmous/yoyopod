"""Bounded remote-audio cache for backend-issued playback URLs."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from loguru import logger


@dataclass(frozen=True, slots=True)
class CachedPlaybackAsset:
    path: str
    cache_hit: bool


class RemotePlaybackCache:
    """Store remote playback assets on disk with a simple size-bounded LRU policy."""

    def __init__(self, root: Path, max_bytes: int) -> None:
        self.root = Path(root)
        self.max_bytes = max(32 * 1024 * 1024, int(max_bytes))
        self.root.mkdir(parents=True, exist_ok=True)
        self._prune_lock = threading.Lock()

    def prepare(
        self,
        *,
        track_id: str,
        media_url: str,
        checksum_sha256: str | None = None,
        extension: str = ".mp3",
    ) -> CachedPlaybackAsset:
        checksum_suffix = (checksum_sha256 or "nochecksum")[:16]
        target_path = self._target_path_for(
            track_id=track_id,
            checksum_suffix=checksum_suffix,
            extension=extension,
        )

        if target_path.exists():
            os.utime(target_path, None)
            logger.info("Remote playback cache hit for {}", track_id)
            self._prune(protected_paths={target_path})
            return CachedPlaybackAsset(path=str(target_path), cache_hit=True)

        logger.info("Remote playback cache miss for {}, downloading asset", track_id)
        downloaded_path = self._download(
            media_url=media_url,
            target_path=target_path,
            checksum_sha256=checksum_sha256,
        )
        self._prune(protected_paths={downloaded_path})
        return CachedPlaybackAsset(path=str(downloaded_path), cache_hit=False)

    def _download(
        self,
        *,
        media_url: str,
        target_path: Path,
        checksum_sha256: str | None,
    ) -> Path:
        fd, tmp_path_raw = tempfile.mkstemp(prefix="yoyopod-cache-", suffix=".part", dir=self.root)
        os.close(fd)
        tmp_path = Path(tmp_path_raw)

        hash_obj = hashlib.sha256()

        try:
            request = urllib.request.Request(
                media_url,
                headers={"User-Agent": "YoYoPod/remote-playback-cache"},
            )
            with urllib.request.urlopen(request, timeout=30) as response, tmp_path.open("wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    handle.write(chunk)
                    hash_obj.update(chunk)

            if checksum_sha256 and hash_obj.hexdigest() != checksum_sha256:
                raise ValueError("checksum_mismatch")

            tmp_path.replace(target_path)
            return target_path
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def _prune(self, *, protected_paths: set[Path] | None = None) -> None:
        protected = {path.resolve(strict=False) for path in (protected_paths or set())}

        with self._prune_lock:
            files: list[tuple[Path, float, int]] = []
            for entry in self.root.glob("*"):
                try:
                    if not entry.is_file():
                        continue
                    stat = entry.stat()
                except FileNotFoundError:
                    continue
                files.append((entry, stat.st_mtime, stat.st_size))

            files.sort(key=lambda item: item[1])
            total_size = sum(item[2] for item in files)
            for entry, _mtime, size in files:
                if total_size <= self.max_bytes:
                    break
                try:
                    if entry.resolve(strict=False) in protected:
                        continue
                    entry.unlink(missing_ok=True)
                    total_size -= size
                except FileNotFoundError:
                    continue

    def _target_path_for(
        self,
        *,
        track_id: str,
        checksum_suffix: str,
        extension: str,
    ) -> Path:
        safe_track_id = self._sanitize_filename_component(track_id)
        safe_extension = self._sanitize_extension(extension)
        target_path = self.root / f"{safe_track_id}-{checksum_suffix}{safe_extension}"

        resolved_root = self.root.resolve(strict=False)
        resolved_target = target_path.resolve(strict=False)
        if resolved_target.parent != resolved_root:
            raise ValueError("unsafe_cache_path")
        return resolved_target

    @staticmethod
    def _sanitize_filename_component(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value).strip())
        normalized = normalized.strip(".-")
        return normalized or "track"

    @staticmethod
    def _sanitize_extension(value: str) -> str:
        normalized = re.sub(r"[^A-Za-z0-9.]+", "", str(value).strip())
        if not normalized:
            return ".mp3"
        if not normalized.startswith("."):
            normalized = f".{normalized}"
        return normalized[:16]
