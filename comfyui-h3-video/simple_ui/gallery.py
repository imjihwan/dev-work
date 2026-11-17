"""Local result gallery with persistent first-reference image associations."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
import uuid

class VideoGallery:
    def __init__(self, output, home, thumbnailer=None):
        self.output = Path(output).resolve()
        self.home = Path(home)
        self.lock = threading.RLock()
        self.scan_lock = threading.Lock()
        self.items = {}
        self.scanned_at = 0
        self.state = None
        self.thumbnailer = thumbnailer

    def _load_state(self):
        if self.state is None:
            try:
                self.state = json.loads((self.home / "state.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.state = {}

    def _save_state(self):
        self.home.mkdir(parents=True, exist_ok=True)
        temporary = self.home / "state.json.tmp"
        temporary.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, self.home / "state.json")

    def _path(self, relative):
        relative = Path(relative)
        path = (self.output / relative).resolve()
        if (relative.is_absolute() or not relative.parts or ".." in relative.parts or relative.parts[0] not in ("video", "story")
                or not any(path.is_relative_to(self.output / name) for name in ("video", "story"))
                or path.suffix.lower() not in (".mp4", ".webm", ".mov", ".m4v")):
            raise ValueError("갤러리의 영상 경로가 올바르지 않습니다.")
        return path

    def _item(self, path):
        relative = path.relative_to(self.output).as_posix()
        path = self._path(relative)
        stat = path.stat()
        if not stat.st_size or time.time() - stat.st_mtime < 3:
            return None
        identity = hashlib.sha256(relative.encode()).hexdigest()
        version = hashlib.sha256(f"{identity}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()
        return {"id": identity, "relative": relative, "version": version, "bytes": stat.st_size,
                "created_at": stat.st_mtime, "video": {"filename": path.name,
                "subfolder": path.parent.relative_to(self.output).as_posix(), "type": "output"}}

    def refresh(self, force=False):
        with self.scan_lock:
            if not force and time.monotonic() - self.scanned_at < 4:
                return
            items = {}
            for name in ("video", "story"):
                base = self.output / name
                if base.is_symlink() or base.is_junction() or not base.resolve().is_relative_to(self.output) or not base.is_dir():
                    continue
                for directory, dirs, files in os.walk(base, followlinks=False):
                    dirs[:] = [entry for entry in dirs if not (Path(directory) / entry).is_symlink() and not (Path(directory) / entry).is_junction()]
                    for filename in files:
                        path = Path(directory) / filename
                        if path.suffix.lower() not in (".mp4", ".webm", ".mov", ".m4v") or path.is_symlink():
                            continue
                        try:
                            item = self._item(path)
                        except (OSError, ValueError):
                            continue
                        if item:
                            items[item["id"]] = item
            with self.lock:
                self._load_state()
                self.items = items
                self.scanned_at = time.monotonic()

    @staticmethod
    def _source_name(name):
        return name if isinstance(name, str) and re.fullmatch(r"simpleui_[0-9a-f]{10}\.(jpg|png|webp)", name) else None

    @staticmethod
    def _source_version(name):
        return hashlib.sha256(("source-image-480-v1:" + name).encode()).hexdigest()

    def remember(self, entries):
        """Save only the output-to-first-input link; never decode media or store prompts."""
        with self.lock:
            self._load_state()
            changed = False
            for entry in entries:
                video, images = entry.get("video") or {}, entry.get("images") or []
                name = self._source_name(images[0]) if isinstance(images, list) and images else None
                if not name or video.get("type", "output") != "output":
                    continue
                try:
                    relative = Path(video.get("subfolder", "")) / video.get("filename", "")
                    self._path(relative)
                except (TypeError, ValueError):
                    continue
                identity = hashlib.sha256(relative.as_posix().encode()).hexdigest()
                flags = self.state.setdefault(identity, {})
                if flags.get("source_image") != name:
                    flags["source_image"] = name
                    changed = True
                if (entry.get("regenerated") or (entry.get("ui") or {}).get("regeneration")) and not flags.get("regenerated"):
                    flags["regenerated"] = True
                    changed = True
            if changed:
                try:
                    self._save_state()
                except OSError:
                    # Reload persisted state on retry; otherwise the in-memory
                    # mutation would make the failed write look already saved.
                    self.state = None
                    raise

    def list(self, offset=0, limit=48, mode="all", order="newest", query="", known="", metadata=(), focus=None):
        if mode not in ("all", "favorites", "trash") or order not in ("newest", "oldest"):
            raise ValueError("갤러리 필터가 올바르지 않습니다.")
        offset, limit = max(0, int(offset)), max(1, min(200, int(limit)))
        self.remember(metadata)
        self.refresh()
        saved = {}
        for entry in metadata:
            video = entry.get("video") or {}
            if video.get("type", "output") != "output":
                continue
            relative = Path(video.get("subfolder", "")) / video.get("filename", "")
            saved[hashlib.sha256(relative.as_posix().encode()).hexdigest()] = entry
        with self.lock:
            counts = {"all": 0, "favorites": 0, "trash": 0}
            results = []
            for identity, item in self.items.items():
                flags = self.state.get(identity, {})
                trash = bool(flags.get("trashed_at"))
                favorite = bool(flags.get("favorite"))
                counts["trash" if trash else "all"] += 1
                if favorite and not trash:
                    counts["favorites"] += 1
                if (mode == "trash") != trash or (mode == "favorites" and not favorite):
                    continue
                details = saved.get(identity, {})
                date = datetime.datetime.fromtimestamp(item["created_at"]).strftime("%Y-%m-%d %H:%M:%S")
                search = f"{date} {details.get('model', '')} {item['video']['filename']}".casefold()
                if query.strip().casefold() not in search:
                    continue
                source = self._source_name(flags.get("source_image"))
                result = {key: item[key] for key in ("id", "created_at", "bytes", "video")}
                result.update(favorite=favorite, trashed=trash,
                              thumbnail=f"/api/gallery/thumbnail?id={identity}&v={self._source_version(source)}" if source else None,
                              thumbnail_kind="source", thumbnail_state="ready" if source else "missing")
                result.update({key: details[key] for key in ("width", "height", "duration", "model", "steps", "seed", "loras") if key in details})
                result["source_id"] = details.get("id") if details.get("mode") in ("REF2VA", "I2VA", "FL2VA") else None
                result["regenerated"] = bool(flags.get("regenerated") or details.get("regenerated"))
                results.append(result)
            results.sort(key=lambda item: (item["created_at"], item["id"]), reverse=order == "newest")
            if focus and mode == "all" and order == "newest" and not query.strip():
                results.sort(key=lambda item: item["source_id"] == focus, reverse=True)
            revision = hashlib.sha256(json.dumps([results, counts], sort_keys=True).encode()).hexdigest()
            return {"items": [] if known == revision else results[offset:offset + limit], "total": len(results),
                    "counts": counts, "revision": revision, "unchanged": known == revision}

    def update(self, request):
        ids, action = request.get("ids"), request.get("action")
        if (not isinstance(ids, list) or not ids or len(ids) > 200 or not all(isinstance(identity, str) for identity in ids)
                or action not in ("favorite", "trash", "restore")):
            raise ValueError("변경할 영상과 동작을 선택해 주세요.")
        if action == "favorite" and not isinstance(request.get("value"), bool):
            raise ValueError("즐겨찾기 상태가 올바르지 않습니다.")
        self.refresh()
        with self.lock:
            if any(identity not in self.items for identity in ids):
                raise ValueError("목록이 바뀌었습니다. 새로고침한 뒤 다시 선택해 주세요.")
            for identity in set(ids):
                flags = self.state.setdefault(identity, {})
                if action == "favorite":
                    flags["favorite"] = request["value"]
                elif action == "trash":
                    flags["trashed_at"] = time.time()
                else:
                    flags.pop("trashed_at", None)
            self._save_state()
        return {"ok": True, "ids": list(dict.fromkeys(ids))}

    def thumbnail(self, identity, version):
        with self.lock:
            self._load_state()
            name = self._source_name(self.state.get(identity, {}).get("source_image"))
            if not name or version != self._source_version(name):
                raise FileNotFoundError("원본 이미지 정보를 찾지 못했습니다.")
            path = self.home / "source_thumbnails" / (version + ".webp")
            if path.is_file():
                cached = path.read_bytes()
                if (len(cached) >= 12 and cached[:4] == b"RIFF" and cached[8:12] == b"WEBP"
                        and int.from_bytes(cached[4:8], "little") == len(cached) - 8):
                    return cached
                # A partial/empty cache must not become a permanent blank tile.
                path.unlink()
            if self.thumbnailer is None:
                raise FileNotFoundError("원본 사진을 불러올 수 없습니다.")
        # 썸네일 만들기(ComfyUI 호출, 최대 수십 초)는 잠금 밖에서: 잠금을 쥔 채 기다리면 이력·상태 조회까지 멈춘다
        data = self.thumbnailer(name)
        # 캐시 파일 읽기(위)와 교체는 같은 잠금 안에서: Windows 에서 읽는 중인 파일을 바꾸면 PermissionError
        with self.lock:
            if path.is_file():
                return data  # 그사이 다른 요청이 먼저 만들었다
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(f"{path.stem}.{uuid.uuid4().hex}.tmp")
            try:
                temporary.write_bytes(data)
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        return data
