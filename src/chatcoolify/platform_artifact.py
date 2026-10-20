"""Bounded, deterministic frontend artifacts; no deployment side effects."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path, PurePosixPath
import stat
import zipfile
import zlib

from .client import CoolifyError

MAX_UPLOAD = 8 * 1024 * 1024
MAX_EXPANDED = 32 * 1024 * 1024
MAX_FILES = 2000


class PlatformError(CoolifyError):
    def __init__(self, status, detail):
        self.status = status
        super().__init__(detail)


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


def validate_archive(data):
    if not isinstance(data, bytes) or len(data) > MAX_UPLOAD:
        raise PlatformError(413, 'Artifact exceeds 8 MiB upload limit')
    files = {}
    entries=set()
    directories=set()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            if len(z.infolist()) > MAX_FILES:
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
                if total > MAX_EXPANDED:
                    raise PlatformError(413, 'Expanded artifact exceeds 32 MiB')
                with z.open(entry) as stream:
                    content = stream.read(min(entry.file_size + 1, MAX_EXPANDED + 1))
                if len(content) != entry.file_size:
                    raise PlatformError(422, 'Artifact entry size mismatch')
                files[name] = content
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


def make_archive(directory):
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
        if len(paths) > MAX_FILES:
            raise PlatformError(413, 'Too many frontend files')
    stream = io.BytesIO()
    total = 0
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        for name, path in paths:
            total += path.stat().st_size
            if total > MAX_EXPANDED:
                raise PlatformError(413, 'Frontend exceeds 32 MiB')
            info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            z.writestr(info, path.read_bytes())
    result = stream.getvalue()
    validate_archive(result)
    return result


def digest(data):
    return hashlib.sha256(data).hexdigest()
