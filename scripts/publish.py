#!/usr/bin/env python3
"""Sign a release, publish immutable RPMs, and prepare signed DNF metadata."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/'config.json').read_text())


def run(args,**kw):return subprocess.run([str(x) for x in args],check=True,**kw)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def verify_manifest(dist):
    m=json.loads((dist/'manifest.json').read_text())
    if m.get('schema')!=1 or m.get('name')!='cn.com.sangfor.atrust':raise ValueError('Unexpected manifest')
    if Path(m['rpm']).name!=m['rpm'] or not m['rpm'].endswith('.rpm'):raise ValueError('Unsafe RPM filename')
    if not re.fullmatch(r'v[0-9.]+-[0-9]+\.local\.fc44',m['tag']):raise ValueError('Unexpected release tag')
    if sha(dist/m['rpm'])!=m['rpm_sha256']:raise ValueError('RPM hash does not match build manifest')
    if m['checks'].get('missing_libraries')!=0:raise ValueError('Runtime verification failed')
    return m


def sign(dist,key_id):
    m=verify_manifest(dist)
    rpm=dist/m['rpm']
    if not re.fullmatch(r'[A-Fa-f0-9]{40}',key_id):raise ValueError('Signing key must be a complete fingerprint')
    with tempfile.TemporaryDirectory() as db:
        candidate=Path(db)/rpm.name
        shutil.copy2(rpm,candidate)
        run(['rpmsign','--addsign','--key-id',key_id,candidate])
        public=Path(db)/(key_id.lower()+'.key')
        with public.open('wb') as f:run(['gpg','--batch','--armor','--export',key_id],stdout=f)
        run(['rpmkeys','--define','_keyring fs','--define',f'_keyringpath {db}/','--checksig',candidate])
        # Failed signing/verification leaves the unsigned build intact.
        shutil.copy2(candidate,rpm)
    m['rpm_sha256']=sha(rpm);m['signing_key']=key_id
    (dist/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    (dist/'SHA256SUMS').write_text(f"{m['rpm_sha256']}  {m['rpm']}\n")
    return m


def assemble(dist,site,key_id,archive,offline=False):
    m=verify_manifest(dist)
    repo=CONFIG['repository']
    package_root=archive/'packages';package_root.mkdir(parents=True,exist_ok=True)
    # Keep immutable releases; the metadata base points at GitHub Releases.
    if offline:
        existing=[]
    else:
        releases=run(['gh','api',f'repos/{repo}/releases','--paginate','--slurp'],capture_output=True,text=True)
        existing=[r for page in json.loads(releases.stdout) for r in page]
    kept=[x for x in existing if not x['draft'] and not x['prerelease'] and re.fullmatch(r'v[0-9.]+-[0-9]+\.local\.fc44',x['tag_name'])]
    kept=sorted(kept,key=lambda x:x['published_at'],reverse=True)[:2]
    for rel in kept:
        tag=rel['tag_name'];target=package_root/tag;target.mkdir(exist_ok=True)
        run(['gh','release','download',tag,'--repo',repo,'--pattern','*.rpm','--dir',target,'--skip-existing'])
    target=package_root/m['tag'];target.mkdir(exist_ok=True)
    shutil.copy2(dist/m['rpm'],target/m['rpm'])
    metadata=site/'rpm/fedora/44/x86_64';metadata.mkdir(parents=True,exist_ok=True)
    run(['createrepo_c','--no-database','--checksum','sha256',
         '--baseurl',f'https://github.com/{repo}/releases/download/',package_root])
    shutil.copytree(package_root/'repodata',metadata/'repodata',dirs_exist_ok=True)
    repomd=metadata/'repodata/repomd.xml'
    run(['gpg','--batch','--yes','--armor','--local-user',key_id,'--detach-sign',repomd])
    public=site/'RPM-GPG-KEY-atrust-fedora'
    with public.open('wb') as f:run(['gpg','--batch','--armor','--export',key_id],stdout=f)
    run(['gpg','--batch','--verify',str(repomd)+'.asc',repomd])
    owner,name=repo.split('/')
    base=f'https://{owner}.github.io/{name}'
    (site/'atrust-fedora.repo').write_text(f'''[atrust-fedora]
name=aTrust Fedora native adaptation
baseurl={base}/rpm/fedora/$releasever/$basearch/
enabled=1
gpgcheck=1
repo_gpgcheck=1
gpgkey={base}/RPM-GPG-KEY-atrust-fedora
sslverify=1
metadata_expire=6h
skip_if_unavailable=1
includepkgs=cn.com.sangfor.atrust
''')
    (site/'index.html').write_text(f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<title>aTrust Fedora repository</title><h1>aTrust Fedora 更新仓库</h1>
<p>个人非官方 Fedora 44 x86_64 适配。新上游通过构建检查后发布。</p>
<p><a href="https://github.com/{repo}">源码与使用说明</a> ·
<a href="atrust-fedora.repo">DNF 配置</a> · <a href="RPM-GPG-KEY-atrust-fedora">公钥</a></p>
<p>当前版本：{m['version']}-{m['release']}</p></html>''')
    (site/'.nojekyll').touch()
    (site/'manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    return m


def release(dist,m):
    repo=CONFIG['repository'];tag=m['tag']
    found=subprocess.run(['gh','release','view',tag,'--repo',repo,'--json','isDraft'],capture_output=True,text=True)
    if found.returncode==0:
        if not json.loads(found.stdout)['isDraft']:raise ValueError('Published immutable release already exists')
    else:
        run(['gh','release','create',tag,'--repo',repo,'--draft','--target','main',
            '--title',f"aTrust {m['version']} / Fedora {m['release']}",
            '--notes','Official upstream binaries with Fedora compatibility adaptations. Build, ELF dependency and browser regression checks passed. Actual institutional VPN resource access requires user validation.'])
    run(['gh','release','upload',tag,'--repo',repo,dist/m['rpm'],dist/'manifest.json',dist/'SHA256SUMS','--clobber'])
    run(['gh','release','edit',tag,'--repo',repo,'--draft=false'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['sign','release','site'])
    p.add_argument('--dist',type=Path,default=ROOT/'dist')
    p.add_argument('--site',type=Path,default=ROOT/'build/site')
    p.add_argument('--archive',type=Path,default=ROOT/'build/archive')
    p.add_argument('--key-id',default=os.environ.get('RPM_SIGNING_KEY_ID'))
    p.add_argument('--offline',action='store_true',help='Prepare a local repository without querying GitHub')
    a=p.parse_args()
    if not a.key_id:raise ValueError('Missing signing key fingerprint')
    if a.command=='sign':sign(a.dist,a.key_id)
    elif a.command=='release':release(a.dist,verify_manifest(a.dist))
    else:assemble(a.dist,a.site,a.key_id,a.archive,a.offline)


if __name__=='__main__':main()
