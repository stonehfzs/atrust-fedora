#!/usr/bin/env python3
"""Commit a monthly upstream check receipt, keeping a durable audit trail."""
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import catalog

ROOT=Path(__file__).resolve().parents[1]
config=json.loads((ROOT/'config.json').read_text())
endpoint=f"repos/{config['repository']}/contents/.checks/upstream.json"
now=datetime.now(timezone.utc)
month=now.strftime('%Y-%m')
found=subprocess.run(['gh','api',endpoint],capture_output=True,text=True)
previous=None
if found.returncode==0:
    previous=json.loads(found.stdout)
    receipt=json.loads(base64.b64decode(previous['content']))
    if receipt['month']==month:
        print('Monthly upstream receipt already exists')
        raise SystemExit(0)
elif '(HTTP 404)' not in found.stderr:
    raise RuntimeError('Unable to read upstream check receipt: '+found.stderr)
source=(ROOT/'.work/catalog.js').read_bytes()
receipt={'schema':1,'month':month,'checked_at':now.isoformat(),
         'catalog_url':config['catalog_url'],
         'catalog_sha256':hashlib.sha256(source).hexdigest(),
         'latest_observed_version':catalog.latest(catalog.parse(source.decode())),
         'meaning':'Official catalog observed; this receipt does not certify package or VPN functionality.'}
data={'message':f'Record official upstream catalog check for {month}',
      'content':base64.b64encode((json.dumps(receipt,indent=2)+'\n').encode()).decode(),
      'branch':'main'}
if previous:data['sha']=previous['sha']
subprocess.run(['gh','api',endpoint,'-X','PUT','--input','-'],
               input=json.dumps(data),text=True,check=True,stdout=subprocess.DEVNULL)
print(f'Recorded official upstream catalog receipt for {month}')
