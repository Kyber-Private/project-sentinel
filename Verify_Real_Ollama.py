"""REAL integration preflight: invokes a running Sentinel backend and local Ollama.

No mocks, no API keys. Creates a fresh Nova sample, waits through agent calls,
skips clarification questions, checks the 4 actual agent runs and PDF.
Run using backend/.venv/Scripts/python.exe, or Python 3.11+.
"""
from __future__ import annotations
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE = "http://127.0.0.1:8000"
LOG = Path(__file__).resolve().parent / "OLLAMA_LIVE_TEST_RESULT.txt"
lines = []

def say(message):
    message = str(message)
    lines.append(message)
    print(message, flush=True)

def call(method, path, payload=None, timeout=45):
    data = json.dumps(payload).encode('utf-8') if payload is not None else None
    request = urllib.request.Request(BASE+path, data=data, method=method,
        headers={'Content-Type':'application/json'} if data is not None else {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read()
        if path.endswith('.pdf'):
            return body
        return json.loads(body)

def poll(inv_id, max_seconds=1400):
    started = time.monotonic()
    last = None
    while time.monotonic() - started < max_seconds:
        d = call('GET', f'/api/investigations/{inv_id}')
        stage = (d.get('status'), d.get('stage_message'))
        if stage != last:
            say(f'Status: {stage[0]} - {stage[1]}')
            last = stage
        if d.get('status') not in ('extracting','analyzing'):
            return d
        time.sleep(3)
    raise RuntimeError('Timed out waiting for AI agents. Inspect backend console.')

def run():
    say('PROJECT SENTINEL - REAL OLLAMA END-TO-END CHECK')
    say('Checks a FRESH analysis, not cached results. May take several minutes.')
    health = call('GET','/api/health')
    say('Health: '+json.dumps(health))
    assert health.get('provider')=='ollama' and health.get('ai_enabled'), \
        'Wrong backend is occupying port 8000. Must be the local Ollama backend.'
    assert health.get('model')=='qwen3:8b', 'Expected qwen3:8b, got: '+str(health.get('model'))
    ping = call('POST','/api/health/openai-test', timeout=360)
    say('Direct Qwen3 structured-response check: '+json.dumps(ping))
    assert ping.get('ok'), 'Ollama structured response failed.'
    created=call('POST','/api/investigations/sample')
    inv_id=created['id']
    say('New investigation: '+inv_id)
    call('POST',f'/api/investigations/{inv_id}/analyze')
    doc=poll(inv_id)
    if doc.get('status')=='error':
        raise RuntimeError('Extraction error: '+str(doc.get('error')))
    if doc.get('status')=='awaiting_answers':
        say('Skipping '+str(len(doc.get('questions') or []))+' clarification questions for reproducibility.')
        for q in doc.get('questions') or []:
            if q.get('status') in ('open','pending'):
                call('POST',f'/api/investigations/{inv_id}/questions/{q["id"]}/answer',{'skip':True})
        call('POST',f'/api/investigations/{inv_id}/continue')
        doc=poll(inv_id)
    assert doc.get('status')=='complete', 'Investigation did not finish: '+str(doc.get('error') or doc.get('status'))
    outlook=doc.get('outlook') or {}
    review=outlook.get('agent_review') or {}
    runs=review.get('runs') or []
    say('Agent calls: '+json.dumps(runs,indent=2))
    failed=review.get('failed') or []
    assert not failed, 'Failed AI agents: '+str(failed)
    for name in ('data_analyst','emily','sebas','alex'):
        matches=[r for r in runs if r.get('agent')==name and r.get('status')=='success'
                 and 'qwen3:8b' in str(r.get('model'))]
        assert matches, f'{name} did not successfully invoke qwen3:8b. Find agent failures above.'
        say('PASSED agent: '+name)
    projects=outlook.get('projects') or []
    say('Project results: '+json.dumps(projects, indent=2)[:2500])
    assert len(projects)==2, 'Expected two projects; got '+str(len(projects))
    assert any('Alpha' in str(p.get('project')) and 550000 <= float(p.get('eac') or 0) <= 590000 for p in projects), \
        'Project Alpha final-cost estimate is missing or out of range.'
    assert any('Beacon' in str(p.get('project')) and 315000 <= float(p.get('eac') or 0) <= 350000 for p in projects), \
        'Project Beacon final-cost estimate is missing or out of range.'
    overall=(outlook.get('overall') or {})
    say('Headline: '+json.dumps(overall))
    assert overall.get('label') in ('LIKELY DETERIORATING','CONCLUSION WITHHELD'), \
        'Unexpected financial headline: '+str(overall.get('label'))
    pdf=call('GET',f'/api/investigations/{inv_id}/report.pdf', timeout=120)
    assert pdf[:4]==b'%PDF' and len(pdf)>2000, 'PDF export failed.'
    say('PDF generated: '+str(len(pdf))+' bytes')
    say('ALL REAL OLLAMA CHECKS PASSED. Ready for GitHub candidate review.')

if __name__=='__main__':
    try:
        run()
    except Exception as exc:
        say('FAILED: '+repr(exc))
        say('Do not replace the GitHub version until this failure is resolved.')
        status=1
    else:
        status=0
    try:
        LOG.write_text('\n'.join(lines)+'\n', encoding='utf-8')
        say('Test log: '+str(LOG))
    except Exception as exc:
        say('Could not save log: '+str(exc))
    sys.exit(status)
