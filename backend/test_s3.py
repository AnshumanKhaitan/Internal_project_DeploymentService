"""Final integration test — all fixes from session 3."""
import sys
sys.path.insert(0, '.')

from app.services.manifest_scanner import ManifestScanner
from app.services.deployment_planner import DeploymentPlanner, _build_fallback_plan, _safe
from app.services.execution_engine import ExecutionEngine
from app.services.container_lifecycle import _port_from_service
from app.main import app
from app.api.routes import router

print("=== _safe() ===")
assert _safe(None) == ''
assert _safe('None') == ''
assert _safe('null') == ''
assert _safe('  ') == ''
assert _safe('node') == 'node'
print("OK")

print("=== Fallback plans (production commands) ===")
cases = [
    ('node',    'nextjs',   [], 'node',   'npm run start'),   # NOT npm run dev
    ('node',    'react',    [], 'node',   'serve'),
    ('node',    'vite',     [], 'node',   'serve'),
    ('node',    'express',  [], 'node',   'npm start'),
    ('python',  'fastapi',  ['main.py'],  'python', 'uvicorn'),
    ('python',  'flask',    ['app.py'],   'python', 'flask'),
    ('python',  'django',   [],           'python', 'manage.py'),
    ('unknown', 'nextjs',   [],           'node',   'npm run start'),
]
for rt, fw, ep, exp_rt, exp_substr in cases:
    fp = _build_fallback_plan(rt, fw, ep)
    svc = fp['services'][0]
    assert svc['runtime'] == exp_rt, f"FAIL {rt}/{fw}: runtime={svc['runtime']}"
    assert exp_substr in svc['start_command'], f"FAIL {rt}/{fw}: '{exp_substr}' not in '{svc['start_command']}'"
    assert 'npm run dev' not in svc['start_command'], f"FAIL {rt}/{fw}: dev command leaked!"
    assert 'next dev' not in svc['start_command'], f"FAIL {rt}/{fw}: next dev leaked!"
    for k, v in svc.items():
        assert v is not None, f"FAIL {rt}/{fw}: {k}=None"
print("OK")

print("=== Dev command blocking ===")
# Simulate scanner returning npm run dev for Next.js (should be blocked by planner)
plan = _build_fallback_plan('node', 'nextjs', [], install_cmd='npm install', start_cmd='npm run dev')
assert 'npm run dev' not in plan['services'][0]['start_command'], "FAIL: dev command not blocked"
assert plan['services'][0]['start_command'] == 'npm run start', f"FAIL: {plan['services'][0]['start_command']}"
print("OK: npm run dev → npm run start")

print("=== Next.js Dockerfile (production) ===")
df = ExecutionEngine.generate_dockerfile({
    'runtime': 'node',
    'install_command': 'npm install',
    'start_command': 'npm run start',
    'framework': 'nextjs'
})
assert 'npm run build' in df, "FAIL: no npm run build in Next.js Dockerfile"
assert 'npm run start' in df or 'npm start' in df, "FAIL: no start command"
assert 'npm run dev' not in df, "FAIL: dev command in Next.js Dockerfile"
assert 'NODE_ENV=production' in df, "FAIL: not production mode"
print(f"OK: Next.js Dockerfile ({len(df)} bytes)")

print("=== Python Dockerfile (full system deps) ===")
df2 = ExecutionEngine.generate_dockerfile({
    'runtime': 'python',
    'install_command': 'pip install -r requirements.txt',
    'start_command': 'uvicorn main:app --host 0.0.0.0 --port 8000',
    'framework': 'fastapi'
})
assert 'build-essential' in df2, "FAIL: no build-essential"
assert 'libpq-dev' in df2, "FAIL: no libpq-dev"
assert 'libssl-dev' in df2, "FAIL: no libssl-dev"
assert 'setuptools wheel' in df2, "FAIL: no wheel"
assert 'no-cache-dir' in df2, "FAIL: no pip no-cache-dir"
assert '--reload' not in df2, "FAIL: --reload in production!"
print(f"OK: Python Dockerfile ({len(df2)} bytes)")

print("=== Vite/React Dockerfile (build+serve) ===")
df3 = ExecutionEngine.generate_dockerfile({
    'runtime': 'node',
    'install_command': 'npm install',
    'start_command': 'npx serve -s dist -l 4173',
    'framework': 'vite'
})
assert 'npm run build' in df3, "FAIL: no build step for Vite"
assert 'serve' in df3, "FAIL: no serve for Vite"
print(f"OK: Vite Dockerfile ({len(df3)} bytes)")

print("=== Scanner: Next.js returns production command ===")
from pathlib import Path
import tempfile, json as _json
with tempfile.TemporaryDirectory() as tmpdir:
    pkg = {"name": "test", "dependencies": {"next": "^14.0.0"}, "scripts": {"dev": "next dev", "build": "next build", "start": "next start"}}
    (Path(tmpdir) / "package.json").write_text(_json.dumps(pkg))
    result = ManifestScanner.scan(tmpdir)
    assert result['framework'] == 'nextjs', f"FAIL: {result['framework']}"
    assert 'npm run dev' not in result['start_command'], f"FAIL: dev command in scanner: {result['start_command']}"
    assert result['start_command'] == 'npm run start', f"FAIL: {result['start_command']}"
    print(f"OK: Scanner Next.js → start_command='{result['start_command']}'")

print("=== Routes loaded ===")
routes = [r.path for r in router.routes]
assert '/health' in routes
assert '/upload' in routes
assert '/preview/{deployment_id}' in routes
assert '/preview/{deployment_id}/{path:path}' in routes
assert '/deployments/{deployment_id}/cleanup' in routes
print("OK:", routes)

print()
print("=== ALL SESSION 3 TESTS PASSED ===")
