#!/usr/bin/env python3
"""Create/configure this authorized repository after gh auth login completes."""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config.json').read_text())
REPO=CONFIG['repository']


def run(args,**kw):return subprocess.run([str(a) for a in args],check=True,**kw)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--key-home',type=Path,required=True)
    p.add_argument('--key-id',required=True)
    a=p.parse_args()
    if not re.fullmatch(r'[A-Fa-f0-9]{40}',a.key_id):raise ValueError('Use full signing fingerprint')
    identity=json.loads(run(['gh','api','user'],capture_output=True,text=True).stdout)
    owner=REPO.split('/')[0]
    if identity['login'].lower()!=owner.lower():raise ValueError('Authenticated GitHub account does not match requested repository owner')
    found=subprocess.run(['gh','repo','view',REPO,'--json','nameWithOwner'],capture_output=True,text=True)
    if found.returncode:
        run(['gh','repo','create',REPO,'--public','--description','Unofficial native Fedora aTrust RPM adaptation with signed DNF updates'])
    run(['git','remote','add','origin',f'https://github.com/{REPO}.git'],cwd=ROOT) if subprocess.run(['git','remote','get-url','origin'],cwd=ROOT,capture_output=True).returncode else None
    public=ROOT/'RPM-GPG-KEY-atrust-fedora'
    env=dict(os.environ,GNUPGHOME=str(a.key_home.resolve()))
    with public.open('wb') as f:run(['gpg','--batch','--armor','--export',a.key_id],stdout=f,env=env)
    # Secret is sent directly to GitHub's encrypted secret API, never printed or committed.
    secret=run(['gpg','--batch','--armor','--export-secret-keys',a.key_id],capture_output=True,env=env).stdout
    run(['gh','secret','set','RPM_SIGNING_PRIVATE_KEY_B64','--repo',REPO],input=base64.b64encode(secret))
    run(['gh','variable','set','RPM_SIGNING_KEY_ID','--repo',REPO,'--body',a.key_id])
    run(['git','add','.'],cwd=ROOT)
    pending=subprocess.run(['git','diff','--cached','--quiet'],cwd=ROOT)
    if pending.returncode:
        run(['git','-c',f'user.name={identity["login"]}','-c',f'user.email={identity["id"]}+{identity["login"]}@users.noreply.github.com',
             'commit','-m','Build and publish signed Fedora aTrust RPM updates'],cwd=ROOT)
    run(['git','-c','credential.helper=','-c','credential.helper=!gh auth git-credential',
         'push','-u','origin','main'],cwd=ROOT)
    pages=subprocess.run(['gh','api',f'repos/{REPO}/pages'],capture_output=True,text=True)
    if pages.returncode:
        run(['gh','api',f'repos/{REPO}/pages','-X','POST','-f','build_type=workflow'])
    else:
        run(['gh','api',f'repos/{REPO}/pages','-X','PUT','-f','build_type=workflow'])
    run(['gh','workflow','run','update.yml','--repo',REPO])
    print(f'Repository configured: https://github.com/{REPO}')


if __name__=='__main__':main()
