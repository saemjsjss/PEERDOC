"""Saving uploaded files (and the contents of uploaded ZIPs) safely into a work folder.

Everything about an upload is untrusted: its name, its size, its content, and whatever a
ZIP claims about its members. So:

* Only the bare file name is kept (no folders), cleaned to safe characters and at most
  150 bytes; a ZIP entry like "../../etc/x.pdf" or "C:\\x\\y.pdf" becomes "x.pdf" / "y.pdf"
  inside the folder. The supported-type check runs on that cleaned name.
* Only PDFs and images are kept; anything else is listed as ignored (the list is capped).
  ZIPs inside ZIPs are not opened, encrypted members are ignored, unreadable members are
  skipped, and an archive with too many entries is refused.
* Bytes are counted as they are actually written, never trusted from headers, and capped:
  total upload size, total unpacked size (ZIP bombs), number of files.
* Any unexpected error while reading an archive is a clean 400, never a crash that could
  log a student's file name.

File names are kept only for ordering and traceability: documents are classified by
content, never by name.
"""

from __future__ import annotations

import re
import shutil
import unicodedata
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath

from hklv_ocr.readers import SUPPORTED_SUFFIXES

MAX_FILES = 200
MAX_ZIP_ENTRIES = 2000  # entries listed in one archive, accepted or not
MAX_UPLOAD_BYTES = 150 * 1024 * 1024  # all uploaded bodies together
MAX_UNPACKED_BYTES = 400 * 1024 * 1024  # all files written, including ZIP contents
MAX_IGNORED_LISTED = 50  # ignored files named in the response; the rest are counted
MAX_NAME_BYTES = 150  # Linux allows 255 bytes per name; leave room for " (NNN)" and the suffix
CHUNK = 1024 * 1024
ZIP_MAGIC = b"PK\x03\x04"


class UploadError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@dataclass
class SavedFiles:
    accepted: list[str] = field(default_factory=list)
    ignored: list[dict[str, str]] = field(default_factory=list)
    ignored_more: int = 0
    bytes_written: int = 0

    def ignore(self, name: str, reason: str) -> None:
        if len(self.ignored) < MAX_IGNORED_LISTED:
            self.ignored.append({"name": name[:200], "reason": reason})
        else:
            self.ignored_more += 1


def _keep_char(ch: str) -> bool:
    # Letters, marks (Bangla vowel signs are marks) and digits from any script, plus a few
    # harmless punctuation characters.
    return unicodedata.category(ch)[0] in "LMN" or ch in " .()-_"


def _cut_to_bytes(text: str, limit: int) -> str:
    while len(text.encode("utf-8")) > limit:
        text = text[:-1]
    return text


def safe_name(raw: str | None) -> str:
    """Bare, harmless file name: folders dropped (both / and \\), odd characters replaced,
    at most MAX_NAME_BYTES of UTF-8."""
    name = PureWindowsPath(PurePosixPath(raw or "").name).name  # last part for either separator
    name = unicodedata.normalize("NFC", name)
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    # Split off the extension before cleaning, so " .pdf" stays a PDF ("file.pdf").
    stem, dot, suffix = name.rpartition(".")
    if not dot or not suffix.strip():
        stem, suffix = name, ""
    stem = "".join(ch if _keep_char(ch) else "_" for ch in stem).strip(" .") or "file"
    suffix = re.sub(r"[^A-Za-z0-9]", "", suffix)[:10]
    stem = _cut_to_bytes(stem, MAX_NAME_BYTES).strip(" .") or "file"
    return f"{stem}.{suffix}" if suffix else stem


def _unique(folder: Path, name: str) -> Path:
    target = folder / name
    if not target.exists():
        return target
    stem, suffix = target.stem, target.suffix
    for i in range(2, MAX_FILES + 10):
        candidate = folder / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
    raise UploadError(413, f"too many files (limit {MAX_FILES})")


def supported(name: str) -> bool:
    return Path(name).suffix.lower() in SUPPORTED_SUFFIXES


class _Budget:
    def __init__(self, saved: SavedFiles):
        self.saved = saved

    def add(self, n: int) -> None:
        self.saved.bytes_written += n
        if self.saved.bytes_written > MAX_UNPACKED_BYTES:
            raise UploadError(413, f"files are too large once unpacked (limit {MAX_UNPACKED_BYTES // 2**20} MB)")

    def count_file(self) -> None:
        if len(self.saved.accepted) >= MAX_FILES:
            raise UploadError(413, f"too many files (limit {MAX_FILES})")


def extract_zip(zip_path: Path, folder: Path, saved: SavedFiles, label: str) -> None:
    """Unpack the supported files of one uploaded ZIP into `folder` (flat)."""
    budget = _Budget(saved)
    try:
        archive = zipfile.ZipFile(zip_path)
        entries = archive.infolist()
    except Exception as e:  # noqa: BLE001  (bad archive, bad names, odd compression ...)
        raise UploadError(400, f"{label} is not a readable ZIP file ({type(e).__name__})") from None
    with archive:
        if len(entries) > MAX_ZIP_ENTRIES:
            raise UploadError(413, f"{label} has too many entries (limit {MAX_ZIP_ENTRIES})")
        for info in entries:
            if info.is_dir():
                continue
            entry = info.filename
            parts = re.split(r"[\\/]", entry)
            base = parts[-1]
            if any(p == "__MACOSX" for p in parts) or base.startswith("."):
                continue  # macOS resource forks, hidden files
            shown = f"{label}:{entry}"
            name = safe_name(base)
            if info.flag_bits & 0x1:
                saved.ignore(shown, "encrypted ZIP entry")
                continue
            if name.lower().endswith(".zip"):
                saved.ignore(shown, "ZIP inside a ZIP is not opened")
                continue
            if not supported(name):
                saved.ignore(shown, "not a PDF or image")
                continue
            budget.count_file()
            target = _unique(folder, name)
            try:
                with archive.open(info) as src, open(target, "wb") as dst:
                    while chunk := src.read(CHUNK):
                        budget.add(len(chunk))  # real bytes, whatever the header claims
                        dst.write(chunk)
            except UploadError:
                target.unlink(missing_ok=True)
                raise
            except Exception as e:  # noqa: BLE001  (corrupt deflate/lzma data, CRC errors ...)
                target.unlink(missing_ok=True)
                saved.ignore(shown, f"could not be unpacked ({type(e).__name__})")
                continue
            saved.accepted.append(target.name)


async def save_uploads(files, folder: Path) -> SavedFiles:
    """Write every upload (FastAPI UploadFile) into `folder`; unpack ZIPs; enforce limits."""
    import asyncio

    saved = SavedFiles()
    uploaded = 0
    staging = folder / ".incoming"
    staging.mkdir(exist_ok=True)
    try:
        for upload in files:
            label = safe_name(upload.filename)
            tmp = _unique(staging, label)
            head = b""
            with open(tmp, "wb") as out:
                while chunk := await upload.read(CHUNK):
                    if not head:
                        head = chunk[:4]
                    uploaded += len(chunk)
                    if uploaded > MAX_UPLOAD_BYTES:
                        raise UploadError(413, f"upload is too large (limit {MAX_UPLOAD_BYTES // 2**20} MB)")
                    out.write(chunk)
            if head == ZIP_MAGIC or label.lower().endswith(".zip"):
                await asyncio.to_thread(extract_zip, tmp, folder, saved, label)
            elif supported(label):
                _Budget(saved).count_file()
                _Budget(saved).add(tmp.stat().st_size)
                target = _unique(folder, label)
                shutil.move(str(tmp), target)
                saved.accepted.append(target.name)
            else:
                saved.ignore(label, "not a PDF, image or ZIP")
            tmp.unlink(missing_ok=True)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return saved


def drop_unreadable(folder: Path, saved: SavedFiles, check) -> None:
    """Remove accepted files the OCR reader can't open (empty, truncated, renamed .docx ...),
    listing them as ignored, so one bad file can't sink the whole case. `check(path)`
    raises if the file is unreadable."""
    kept = []
    for name in saved.accepted:
        path = folder / name
        try:
            check(path)
        except Exception as e:  # noqa: BLE001
            path.unlink(missing_ok=True)
            saved.ignore(name, f"unreadable or corrupt file ({type(e).__name__})")
            continue
        kept.append(name)
    saved.accepted = kept
