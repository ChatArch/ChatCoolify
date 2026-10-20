"""Private bare-Git build inputs for Coolify; not a runtime/deployment engine."""
from __future__ import annotations

from pathlib import Path
import subprocess
import time

from .platform_artifact import validate_archive, digest

FRONTEND_DOCKERFILE = '''FROM python:3.12-alpine
WORKDIR /app
COPY runtime.py /app/runtime.py
COPY artifact.zip /app/artifact.zip
RUN python -m zipfile -e /app/artifact.zip /app/site && rm /app/artifact.zip
ARG ARTIFACT_SHA256
USER 1005:1005
EXPOSE 8080
CMD ["python", "/app/runtime.py"]
'''


class GitSources:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, project_id):
        if not project_id.isalnum() or not 1 <= len(project_id) <= 80:
            raise ValueError('Invalid source project id')
        return self.root / (project_id + '.git')

    def commit_files(self, project_id, files, message):
        repo = self.path(project_id)
        if not repo.exists():
            subprocess.run(['git', 'init', '--bare', str(repo)], check=True, capture_output=True)
        head = subprocess.run(['git', '--git-dir', str(repo), 'rev-parse', '--verify', 'refs/heads/main'],
                              capture_output=True, text=True)
        parent = head.stdout.strip() if head.returncode == 0 else None
        stream = bytearray()
        for number, (name, content) in enumerate(sorted(files.items()), 1):
            if name not in {'Dockerfile', 'artifact.zip', 'runtime.py', 'package.whl', 'bootstrap.py'}:
                raise ValueError('Uncontrolled build input name')
            stream.extend(f'blob\nmark :{number}\ndata {len(content)}\n'.encode() + content + b'\n')
        stamp = int(time.time())
        encoded = message.encode()
        stream.extend(f'commit refs/heads/main\ncommitter ChatCoolify Platform <deploy@localhost> {stamp} +0000\ndata {len(encoded)}\n'.encode() + encoded + b'\n')
        if parent:
            stream.extend(f'from {parent}\n'.encode())
        stream.extend(b'deleteall\n')
        for number, name in enumerate(sorted(files), 1):
            stream.extend(f'M 100644 :{number} {name}\n'.encode())
        stream.extend(b'\ndone\n')
        subprocess.run(['git', '--git-dir', str(repo), 'fast-import', '--quiet'],
                       input=bytes(stream), check=True, capture_output=True)
        return subprocess.check_output(['git', '--git-dir', str(repo), 'rev-parse', 'refs/heads/main'], text=True).strip()

    def frontend(self, project_id, archive):
        files,docker_digest=frontend_files(archive)
        return self.commit_files(project_id, files, 'Frontend artifact ' + digest(archive)),docker_digest


def frontend_files(archive):
    validate_archive(archive)
    artifact_digest=digest(archive)
    runtime=Path(__file__).with_name('platform_runtime.py').read_bytes()
    dockerfile=FRONTEND_DOCKERFILE.replace('ARG ARTIFACT_SHA256',
        f'ENV PLATFORM_ARTIFACT_SHA256={artifact_digest}\nLABEL io.chatcoolify.artifact.sha256="{artifact_digest}"\n'
        f'LABEL io.chatcoolify.runtime.sha256="{digest(runtime)}"')
    return {'Dockerfile':dockerfile.encode(),'artifact.zip':archive,'runtime.py':runtime},digest(dockerfile.encode())
