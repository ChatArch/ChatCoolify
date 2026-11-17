"""Bounded, deterministic frontend artifacts; no deployment side effects."""
from __future__ import annotations

import hashlib
import io
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
import stat
import zipfile
import zlib

from .client import CoolifyError

MAX_UPLOAD = 1024 * 1024 * 1024
MAX_EXPANDED = 0
MAX_FILES = 0


class PlatformError(CoolifyError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(detail)


@dataclass(frozen=True)
class ArtifactLimits:
    """Artifact policy; zero disables that business-size/count limit."""
    max_upload_bytes: int = MAX_UPLOAD
    max_expanded_bytes: int = MAX_EXPANDED
    max_files: int = MAX_FILES

    def __post_init__(self):
        for value in asdict(self).values():
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PlatformError(422, 'Artifact limits must be nonnegative integers; zero means unlimited')

    def as_dict(self):
        return asdict(self)

    @classmethod
    def from_values(cls, values):
        fields = {'max_upload_bytes': 'CHATCOOLIFY_MAX_UPLOAD_BYTES',
                  'max_expanded_bytes': 'CHATCOOLIFY_MAX_EXPANDED_BYTES',
                  'max_files': 'CHATCOOLIFY_MAX_ARTIFACT_FILES'}
        parsed = {}
        for name, key in fields.items():
            raw = values.get(key)
            if raw is None or raw == '':
                continue
            if isinstance(raw, bool) or not isinstance(raw, (str, int)):
                raise PlatformError(422, 'Artifact limits must be nonnegative integers; zero means unlimited')
            try:
                parsed[name] = int(raw)
            except (ValueError, TypeError):
                raise PlatformError(422, 'Artifact limits must be nonnegative integers; zero means unlimited') from None
        return cls(**parsed)

    @classmethod
    def from_payload(cls, value):
        keys = {'max_upload_bytes', 'max_expanded_bytes', 'max_files'}
        if not isinstance(value, dict) or set(value) != keys:
            raise PlatformError(502, 'Platform returned an invalid artifact policy')
        try:
            return cls(**value)
        except PlatformError:
            raise PlatformError(502, 'Platform returned an invalid artifact policy') from None


def safe_name(name):
    path = PurePosixPath(name)
    if (not name or len(name) > 512 or path.is_absolute() or '\\' in name
            or any(p in {'', '.', '..'} or p.startswith('.') for p in name.split('/'))
            or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or path.parts[0] in {'__platform', '_platform', 'Dockerfile'}
            or path.name.lower() in {'credentials.json','token.json','tokens.json','id_rsa','id_ed25519'}
            or path.suffix.lower() in {'.pem','.key','.p12','.pfx'}):
        raise PlatformError(422, 'Invalid or reserved artifact path')
    return path


def validate_archive(data, *, limits=None, read_files=True):
    limits = limits or ArtifactLimits()
    if not isinstance(data, bytes) or (limits.max_upload_bytes and len(data) > limits.max_upload_bytes):
        raise PlatformError(413, 'Artifact exceeds configured upload limit')
    files = {}
    entries=set()
    directories=set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if limits.max_files and len(z.infolist()) > limits.max_files:
                raise PlatformError(413, 'Too many artifact entries')
            for entry in z.infolist():
                name = entry.filename.rstrip('/') if entry.is_dir() else entry.filename
                safe_name(name)
                if name in entries:raise PlatformError(422,'Duplicate artifact entry')
                entries.add(name)
                mode = entry.external_attr >> 16
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR} or entry.flag_bits & 1:
                    raise PlatformError(422, 'Non-regular or encrypted artifact entry')
                if entry.is_dir():
                    directories.add(name)
                    continue
                if name in files:
                    raise PlatformError(422, 'Duplicate artifact path')
                total += entry.file_size
                if limits.max_expanded_bytes and total > limits.max_expanded_bytes:
                    raise PlatformError(413, 'Expanded artifact exceeds configured limit')
                with z.open(entry) as stream:
                    chunks = [] if read_files else None
                    actual_size = 0
                    while True:
                        chunk = stream.read(1024 * 1024)
                        if not chunk:
                            break
                        actual_size += len(chunk)
                        if chunks is not None:
                            chunks.append(chunk)
                if actual_size != entry.file_size:
                    raise PlatformError(422, 'Artifact entry size mismatch')
                files[name] = b''.join(chunks) if chunks is not None else b''
            for name in entries:
                if (name in files and name in directories) or any(str(parent) in files for parent in PurePosixPath(name).parents if str(parent)!='.'):
                    raise PlatformError(422,'Artifact file/directory conflict')
    except PlatformError:
        raise
    except (zipfile.BadZipFile, zlib.error, RuntimeError, OSError, ValueError):
        raise PlatformError(422, 'Invalid frontend artifact') from None
    if 'index.html' not in files:
        raise PlatformError(422, 'Frontend artifact requires index.html')
    return files


def make_archive(directory, *, limits=None):
    limits = limits or ArtifactLimits()
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise PlatformError(422, 'Frontend directory required')
    paths = []
    for path in sorted(root.rglob('*')):
        name = path.relative_to(root).as_posix()
        if any(p.startswith('.') for p in path.relative_to(root).parts):
            continue
        safe_name(name)
        if path.is_symlink() or (not path.is_file() and not path.is_dir()):
            raise PlatformError(422, 'Frontend contains a symlink or special file')
        if path.is_file():
            paths.append((name, path))
        if limits.max_files and len(paths) > limits.max_files:
            raise PlatformError(413, 'Too many frontend files')
    stream = io.BytesIO()
    total = 0
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, path in paths:
            total += path.stat().st_size
            if limits.max_expanded_bytes and total > limits.max_expanded_bytes:
                raise PlatformError(413, 'Frontend exceeds configured expanded limit')
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            info.file_size = path.stat().st_size
            with path.open('rb') as source, z.open(info, 'w') as destination:
                while True:
                    chunk = source.read(1024 * 1024)
                    if not chunk:
                        break
                    destination.write(chunk)
                    if limits.max_upload_bytes and stream.tell() > limits.max_upload_bytes:
                        raise PlatformError(413, 'Artifact exceeds configured upload limit')
    result = stream.getvalue()
    validate_archive(result, limits=limits, read_files=False)
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()
