#!/usr/bin/env python3
"""Isolated seoyoon branch runtime; never migrate/restart the demo database/services.
Run with services/.venv/bin/python infra/seoyoon-dev.py init|up [fixture|live]|down|run <command...>.
Secrets are loaded from .env after shell API keys are removed and are never printed.
"""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'services'))
for name in ('OPENAI_API_KEY','LANGSMITH_API_KEY'):
    os.environ.pop(name,None)
from shared.config import settings
S = settings()
ENV = os.environ.copy()
for name in ('DATABASE_URL','CHECKPOINT_DATABASE_URL','RAG_DATABASE_URL','INDEXER_DATABASE_URL'):
    value = ENV.get(name, '')
    if value:
        parsed = urlsplit(value)
        ENV[name] = urlunsplit(parsed._replace(path='/dayzero_seoyoon'))
ENV.update(APP_ORIGIN='http://localhost:3200', GATEWAY_INTERNAL_URL='http://localhost:8100',
           AGENT_INTERNAL_URL='http://localhost:8101',BUSINESS_MCP_URL='http://localhost:9111/mcp',
           RAG_MCP_URL='http://localhost:9112/mcp', NEXT_DIST_DIR='.next-seoyoon',DAYZERO_MCP_URL='http://localhost:9113/mcp', PYTHONUNBUFFERED='1')
RUN = ROOT / '.run' / 'seoyoon'
RUN.mkdir(parents=True,exist_ok=True)
PYTHON = str(ROOT / 'services/.venv/bin/python')


def down():
    for pid in RUN.glob('*.pid'):
        try:
            os.killpg(int(pid.read_text()),signal.SIGTERM)
        except ProcessLookupError:
            pass
        pid.unlink()


def run(args,cwd=ROOT/'services'):
    return subprocess.run(args,env=ENV,cwd=cwd,check=True)


def up(mode):
    down()
    ENV['LLM_MODE']=mode
    commands = {
        'gateway': [PYTHON,'-m','uvicorn','gateway.app.main:app','--host','127.0.0.1','--port','8100'],
        'business': [PYTHON,'-m','uvicorn','business_mcp.server:app','--host','127.0.0.1','--port','9111'],
        'rag': [PYTHON,'-m','uvicorn','rag_mcp.server:app','--host','127.0.0.1','--port','9112'],
        'agent': [PYTHON,'-m','uvicorn','agent.app.main:app','--host','127.0.0.1','--port','8101'],
        'dayzero': [PYTHON,'-m','dayzero_mcp.server','--port','9113'],
        'web': ['node',str(ROOT/'frontend/node_modules/next/dist/bin/next'),'dev','--port','3200'],
    }
    for name,args in commands.items():
        with (RUN/f'{name}.log').open('a') as log:
            proc = subprocess.Popen(args,cwd=ROOT/('frontend' if name=='web' else 'services'),env=ENV,
                                    stdout=log,stderr=log,stdin=subprocess.DEVNULL,start_new_session=True)
        (RUN/f'{name}.pid').write_text(str(proc.pid))
    import httpx
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            health=httpx.get(ENV['GATEWAY_INTERNAL_URL']+'/api/v1/health',timeout=3).json()
            web=httpx.get(ENV['APP_ORIGIN']+'/api/v1/health',timeout=3)
            if health.get('mode')==mode and health.get('status')=='ok' and web.status_code==200:
                break
        except (httpx.HTTPError,ValueError):
            pass
        time.sleep(.5)
    else:
        raise RuntimeError('Isolated services did not become ready; inspect .run/seoyoon/*.log')
    print(f'Seoyoon {mode}: web :3200, gateway :8100, agent :8101; demo ports unchanged')


if __name__=='__main__':
    command = sys.argv[1]
    if command=='init':
        import psycopg
        with psycopg.connect(S.psycopg_dsn,autocommit=True) as c:
            if not c.execute("SELECT 1 FROM pg_database WHERE datname='dayzero_seoyoon'").fetchone():
                c.execute('CREATE DATABASE dayzero_seoyoon')
        run([PYTHON,'-m','alembic','upgrade','head'])
        run([PYTHON,'-m','scripts.seed'])
        run([PYTHON,'-m','scripts.index_documents'])
    elif command=='up':up(sys.argv[2] if len(sys.argv)>2 else 'live')
    elif command=='down':down()
    elif command=='run':run(sys.argv[2:])
    else:raise SystemExit('unknown command')
