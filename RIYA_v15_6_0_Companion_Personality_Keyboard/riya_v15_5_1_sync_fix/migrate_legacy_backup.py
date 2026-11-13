#!/usr/bin/env python3
"""Safely import an exported RIYA JSON backup into the local SQLite API."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', required=True, help='Path to JSON exported by RIYA')
    parser.add_argument('--server', default='http://127.0.0.1:8000', help='RIYA local server URL')
    args = parser.parse_args()
    path = Path(args.backup).expanduser().resolve()
    raw = path.read_bytes()
    backup = json.loads(raw.decode('utf-8-sig'))
    if not isinstance(backup, dict) or backup.get('app') != 'RIYA' or not isinstance(backup.get('tasks'), list):
        raise SystemExit('This does not look like a valid RIYA JSON backup.')
    key = 'legacy-import-' + hashlib.sha256(raw).hexdigest()[:48]
    payload = json.dumps({'idempotency_key': key, 'backup': backup}).encode('utf-8')
    req = Request(args.server.rstrip('/') + '/api/db/import', data=payload,
                  headers={'Content-Type': 'application/json'}, method='POST')
    try:
        with urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode('utf-8'))
    except HTTPError as exc:
        detail = exc.read().decode('utf-8', 'replace')[:1000]
        raise SystemExit(f'RIYA rejected the import (HTTP {exc.code}): {detail}')
    except URLError as exc:
        raise SystemExit(f'Cannot reach RIYA at {args.server}: {exc.reason}')
    counts = result.get('imported', {})
    print('Import request completed.')
    print('Imported/upserted:', json.dumps(counts, ensure_ascii=False))
    print('Database task count:', len(result.get('database', {}).get('tasks', [])))
    print('Idempotency key:', key)
    print('Verify in RIYA with: http://127.0.0.1:8000/api/db/status')

if __name__ == '__main__':
    main()
