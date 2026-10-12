#!/usr/bin/env python3
"""Fetch an official DEB, apply reviewed adaptations, and build a Fedora RPM."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import catalog
import adapt

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / 'config.json').read_text())
NAME = 'cn.com.sangfor.atrust'


def run(args, **kw):
    return subprocess.run([str(x) for x in args], check=True, **kw)


def digest(p):
    h = hashlib.sha256()
    with Path(p).open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
    return h.hexdigest()


def download(url, dest, catalog_file=False):
    if not catalog_file: catalog.validated_url(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + '.part')
    result = run(['curl','--fail','--location','--silent','--show-error','--retry','3',
        '--connect-timeout','20','--max-time','600','--proto','=https','--proto-redir','=https',
        '--output',part,'--write-out','%{url_effective}',url], capture_output=True, text=True)
    if catalog_file:
        if result.stdout != CONFIG['catalog_url']: raise ValueError('Unexpected catalog redirect')
    else: catalog.validated_url(result.stdout)
    part.replace(dest)


def get_catalog(work, offline=False):
    p = work / 'catalog.js'
    if not offline: download(CONFIG['catalog_url'],p,catalog_file=True)
    if not p.exists(): raise ValueError('No cached catalog; run check online first')
    return catalog.parse(p.read_text()), digest(p)


def check(work, offline=False):
    versions, _ = get_catalog(work, offline)
    version = catalog.latest(versions)
    release = f"{CONFIG['packaging_revision']}.local.fc{CONFIG['fedora_release']}"
    print(json.dumps({'version':version,'release':release,'url':versions[version],
                      'tag':f'v{version}-{release}'},indent=2))
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output,'a') as f:
            for k,v in {'version':version,'release':release,'tag':f'v{version}-{release}'}.items():
                f.write(f'{k}={v}\n')


def validate_archive(deb):
    # Validate every member before allowing dpkg-deb to extract it.
    proc = subprocess.Popen(['dpkg-deb','--fsys-tarfile',str(deb)],stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    links = set()
    try:
        with tarfile.open(fileobj=proc.stdout,mode='r|') as archive:
            for m in archive:
                p = Path(m.name.removeprefix('./'))
                if p.is_absolute() or '..' in p.parts:
                    raise ValueError('Unsafe package member path')
                if m.isdev() or m.isfifo(): raise ValueError('Unexpected special package file')
                if any(parent.as_posix() in links for parent in p.parents):
                    raise ValueError('Package member traverses a symlink')
                if m.issym() or m.islnk():
                    target = Path(m.linkname)
                    if target.is_absolute() or '..' in target.parts:
                        raise ValueError('Unsafe package link target')
                    links.add(p.as_posix())
        if proc.wait() != 0: raise ValueError('Unable to inspect DEB payload')
    except Exception:
        proc.terminate();proc.wait();raise


REQUIRES = '''bash, coreutils, systemd, iptables-nft, iproute, procps-ng, psmisc
libX11, libXcomposite, libXdamage, libXext, libXfixes, libXrandr
libXScrnSaver, libXtst, libxcb, libdrm, mesa-libgbm, libxkbcommon
alsa-lib, atk, at-spi2-atk, gtk3, nss, nspr, glib2, pango, cairo
libcurl, libproxy, qt5-qtbase, qt5-qtx11extras, libnsl, libsecret, libstdc++'''


def spec(version, release, payload, assets, group):
    q = lambda p:shlex.quote(str(p)).replace('%','%%')
    installs = '\n'.join(f'install -Dm{mode} {q(assets/src)} %{{buildroot}}{dest}'
        for src,dest,mode in [
            ('atrust','/usr/bin/atrust','755'),
            ('atrust-fedora-daemon','/usr/libexec/atrust-fedora-daemon','755'),
            ('atrust-fedora-initialize','/usr/libexec/atrust-fedora-initialize','755'),
            ('atrust-fedora-backup','/usr/libexec/atrust-fedora-backup','755'),
            ('aTrustDaemon.service','/usr/lib/systemd/system/aTrustDaemon.service','644'),
            ('cn.com.sangfor.atrust.desktop','/usr/share/applications/cn.com.sangfor.atrust.desktop','644')])
    requires = '\n'.join('Requires: '+s for s in REQUIRES.splitlines())
    backup_body=(assets/'atrust-fedora-backup').read_text().replace('%','%%')
    return f'''%global debug_package %{{nil}}
%global __os_install_post %{{nil}}
%global _build_id_links none
%global _binary_payload w3.zstdio
Name: {NAME}
Version: {version}
Release: {release}
Summary: Sangfor aTrust with reviewed Fedora adaptations
License: LicenseRef-Proprietary
URL: https://github.com/{CONFIG['repository']}
BuildArch: x86_64
AutoReqProv: no
{requires}

%description
Unofficial native Fedora adaptation of the official Sangfor Linux client.
Vendor binaries are retained. Reviewed JavaScript compatibility patches
and native Fedora launch/service configuration are applied by this repository.
This personal repository currently targets the {group} group on Fedora 44.

%prep
%build
%install
mkdir -p %{{buildroot}}/usr/share/sangfor
cp -a {q(payload/'usr/share/sangfor/aTrust')} %{{buildroot}}/usr/share/sangfor/
{installs}
install -Dm644 {q(payload/'usr/lib/systemd/system/aTrustShell.service')} %{{buildroot}}/usr/lib/systemd/system/aTrustShell.service
install -Dm644 {q(payload/'usr/lib/systemd/user/aTrustShell.service')} %{{buildroot}}/usr/lib/systemd/user/aTrustShell.service
install -Dm644 {q(payload/'usr/share/pixmaps/aTrust.png')} %{{buildroot}}/usr/share/pixmaps/aTrust.png
mkdir -p %{{buildroot}}/var/lib/atrust
ln -s /var/lib/atrust %{{buildroot}}/usr/share/sangfor/.aTrust

%pre -p /bin/bash
if ! getent group {group} >/dev/null; then
    echo 'Required local group {group} is missing.' >&2
    exit 1
fi
if [ "$1" -gt 1 ]; then
    /bin/bash -s -- --for-upgrade <<'ATRUST_BACKUP_SCRIPT'
{backup_body}
ATRUST_BACKUP_SCRIPT
    if [ "$?" -ne 0 ]; then exit 1; fi
fi

%post
/usr/libexec/atrust-fedora-initialize
/usr/bin/systemctl daemon-reload >/dev/null 2>&1 || :
/usr/bin/update-desktop-database /usr/share/applications >/dev/null 2>&1 || :

%preun
if [ "$1" -eq 0 ]; then
    /usr/bin/systemctl stop aTrustDaemon.service >/dev/null 2>&1 || :
fi

%postun
/usr/bin/systemctl daemon-reload >/dev/null 2>&1 || :
/usr/bin/update-desktop-database /usr/share/applications >/dev/null 2>&1 || :

%posttrans
if [ -f /run/atrust-fedora-upgrade/was-active ]; then
    if [ "$(cat /run/atrust-fedora-upgrade/was-active)" = 1 ]; then
        /usr/bin/systemctl start aTrustDaemon.service || exit 1
    fi
    rm -f /run/atrust-fedora-upgrade/was-active /run/atrust-fedora-upgrade/snapshot
    echo 'aTrust updated. Reopen its desktop window before reconnecting.'
fi

%files
%defattr(-,root,root,-)
%dir /usr/share/sangfor
/usr/share/sangfor/aTrust
/usr/share/sangfor/.aTrust
/usr/bin/atrust
/usr/libexec/atrust-fedora-daemon
/usr/libexec/atrust-fedora-initialize
/usr/libexec/atrust-fedora-backup
/usr/lib/systemd/system/aTrustDaemon.service
/usr/lib/systemd/system/aTrustShell.service
/usr/lib/systemd/user/aTrustShell.service
/usr/share/applications/cn.com.sangfor.atrust.desktop
/usr/share/pixmaps/aTrust.png
%dir %attr(2770,root,{group}) /var/lib/atrust
'''


def libraries(root):
    env = dict(os.environ,LD_LIBRARY_PATH=f'{root}/resources/bin:{root}:/usr/lib64:{root}/resources/lib')
    targets = [root/'aTrustTray']
    targets += list((root/'resources/bin').glob('*'))
    targets += list((root/'resources/bin/plugins/aTrustCore').glob('*'))
    targets += list((root/'resources/app/src/plugins').glob('*.node'))
    targets = [p for p in targets if p.is_file() and p.open('rb').read(4)==b'\x7fELF']
    def inspect(p):
        result = subprocess.run(['ldd',str(p)],env=env,capture_output=True,text=True)
        errors = [s.strip() for s in result.stdout.splitlines() if 'not found' in s]
        return str(p.relative_to(root)), errors
    rows = list(ThreadPoolExecutor(max_workers=4).map(inspect,targets))
    missing = {p:e for p,e in rows if e}
    if missing: raise RuntimeError('Missing runtime libraries: '+json.dumps(missing))
    return {'elf_files':len(rows),'missing_libraries':0}


def build(args):
    work = args.work.resolve();work.mkdir(parents=True,exist_ok=True)
    versions, catalog_hash = get_catalog(work,args.offline)
    version = args.version or catalog.latest(versions)
    if version not in versions: raise ValueError('Version absent from official catalog')
    url = versions[version]
    cache = work/f'aTrustInstaller_{version}_amd64.deb'
    pinned = CONFIG['baseline_sha256'].get(version)
    if args.deb:
        checksum = digest(args.deb)
        expected = args.sha256 or pinned
        if not expected or checksum != expected:
            raise ValueError('Local DEB requires a matching known or explicit SHA256')
        if args.deb.resolve() != cache.resolve(): shutil.copy2(args.deb,cache)
    elif not cache.exists(): download(url,cache)
    checksum = digest(cache)
    if pinned and checksum != pinned: raise ValueError('Baseline DEB hash changed; publication stopped')
    marker = cache.with_suffix('.sha256')
    if marker.exists() and marker.read_text().strip() != checksum:
        raise ValueError('Cached package checksum changed')
    marker.write_text(checksum+'\n')
    fields = run(['dpkg-deb','-f',cache,'Package','Version','Architecture'],capture_output=True,text=True).stdout
    metadata = dict(s.split(': ',1) for s in fields.splitlines())
    if metadata != {'Package':NAME,'Version':version,'Architecture':'amd64'}:
        raise ValueError('Unexpected package name, version, or architecture')
    validate_archive(cache)
    release = f"{CONFIG['packaging_revision']}.local.fc{CONFIG['fedora_release']}"
    staging = work/f'build-{version}-{release}'
    if staging.exists(): shutil.rmtree(staging)
    payload=staging/'payload';assets=staging/'assets';top=staging/'rpmbuild'
    staging.mkdir(parents=True)
    run(['dpkg-deb','-x',cache,payload])
    shutil.copytree(ROOT/'packaging',assets)
    group=CONFIG['runtime_group']
    if not re.fullmatch(r'[a-z_][a-z0-9_-]*',group): raise ValueError('Invalid group name')
    app=payload/'usr/share/sangfor/aTrust'
    report=adapt.apply(app)
    run(['node',ROOT/'tests/browser.js',app/'resources/app/src/service/util/util.js'])
    checks=libraries(app)
    for p in assets.iterdir():
        if p.is_file() and p.read_bytes().startswith(b'#!/bin/bash'): run(['bash','-n',p])
    for directory in ['BUILD','BUILDROOT','RPMS','SRPMS','SPECS','SOURCES']:(top/directory).mkdir(parents=True)
    spec_file=top/'SPECS/atrust.spec';spec_file.write_text(spec(version,release,payload,assets,group))
    with (staging/'rpmbuild.log').open('w') as log:
        run(['rpmbuild','-bb','--define',f'_topdir {top}','--define','_tmppath /tmp',spec_file],stdout=log,stderr=log)
    rpms=list((top/'RPMS/x86_64').glob('*.rpm'))
    if len(rpms)!=1: raise RuntimeError('Unexpected build output')
    run(['rpm','-K',rpms[0]])
    dist=args.dist.resolve();dist.mkdir(parents=True,exist_ok=True)
    rpm=dist/rpms[0].name;shutil.copy2(rpms[0],rpm)
    manifest={'schema':1,'name':NAME,'version':version,'release':release,'architecture':'x86_64',
        'tag':f'v{version}-{release}','rpm':rpm.name,'rpm_sha256':digest(rpm),
        'source_url':url,'source_sha256':checksum,'catalog_sha256':catalog_hash,
        'patch_report':report,'checks':checks,'built_at':datetime.now(timezone.utc).isoformat(),
        'vpn_resource_access_verified':False,'config_sha256':digest(ROOT/'config.json')}
    (dist/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (dist/'SHA256SUMS').write_text(f'{digest(rpm)}  {rpm.name}\n')
    print(json.dumps(manifest,indent=2))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['check','build'])
    p.add_argument('--work',type=Path,default=ROOT/'.work')
    p.add_argument('--dist',type=Path,default=ROOT/'dist')
    p.add_argument('--offline',action='store_true')
    p.add_argument('--version')
    p.add_argument('--deb',type=Path)
    p.add_argument('--sha256')
    args=p.parse_args()
    if args.command=='check':check(args.work,args.offline)
    else:build(args)


if __name__=='__main__':main()
