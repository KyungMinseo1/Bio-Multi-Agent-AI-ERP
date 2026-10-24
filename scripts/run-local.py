"""Local-only unified web/API + worker. Existing environment values are never overwritten."""
import os
from pathlib import Path
import secrets
import signal
import subprocess
import sys
from dotenv import load_dotenv, dotenv_values

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env', override=False)
load_dotenv(ROOT / 'backend' / '.env', override=False)
runtime = ROOT / '.runtime'
runtime.mkdir(mode=0o700, exist_ok=True)
local = runtime / 'local-demo.env'
if not local.exists():
    content = '\n'.join([f'SESSION_SECRET={secrets.token_urlsafe(48)}', 'INITIAL_APPROVER_EMAIL=local-demo@bioflow.test', f'INITIAL_APPROVER_PASSWORD={secrets.token_urlsafe(32)}', 'BIOFLOW_LOCAL_DEMO=1']) + '\n'
    fd = os.open(local, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as output:
        output.write(content)
# Local-demo login is enabled only when this launcher generated the session/account.
if not os.environ.get('SESSION_SECRET'):
    for name, value in dotenv_values(local).items():
        os.environ.setdefault(name, value or '')
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (runtime / 'bioflow.db').as_posix())
os.environ.setdefault('PLANNING_AS_OF', '2026-10-24')
os.environ.setdefault('BIOFLOW_NODE', __import__('shutil').which('node') or 'node')
if not (ROOT / 'dist' / 'index.html').exists() or not (ROOT / 'server-dist' / 'workflow.cjs').exists():
    raise SystemExit('npm run build를 먼저 실행하세요.')
subprocess.run([sys.executable, '-m', 'alembic', 'upgrade', 'head'], cwd=ROOT / 'backend', check=True)
children = [subprocess.Popen([sys.executable, '-m', 'app.worker'], cwd=ROOT / 'backend'), subprocess.Popen([sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', os.environ.get('BIOFLOW_PORT', '4173')], cwd=ROOT / 'backend')]
def stop(*_):
    for child in children:
        if child.poll() is None: child.terminate()
for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, stop)
print('BioFlow 통합 웹/API + worker: http://127.0.0.1:' + os.environ.get('BIOFLOW_PORT', '4173'), flush=True)
try:
    while all(p.poll() is None for p in children):
        try: children[-1].wait(timeout=1)
        except subprocess.TimeoutExpired: pass
finally:
    stop()
    for child in children:
        try: child.wait(timeout=8)
        except subprocess.TimeoutExpired: child.kill()
