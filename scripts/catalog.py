"""Read vendor data as text; never execute downloaded JavaScript."""
import re
import urllib.parse

ALLOWED_HOSTS = {'atrustcdn.sangfor.com'}


def validated_url(url):
    u = urllib.parse.urlsplit(url)
    if u.scheme != 'https' or u.hostname not in ALLOWED_HOSTS or u.username or u.password or u.port not in (None,443):
        raise ValueError('Source URL must use the configured official HTTPS CDN')
    if not re.fullmatch(r'/standard/linux/[0-9.]+/ubuntu/amd64/aTrustInstaller_amd64\.deb', u.path):
        raise ValueError('Unexpected official Ubuntu amd64 package path')
    if u.query or u.fragment:
        raise ValueError('Unexpected source URL query/fragment')
    return url


def parse(text):
    rows = re.findall(r"name:\s*'Ubuntu_X86[^']*?([0-9]+(?:\.[0-9]+)+)'\s*,\s*url:\s*'([^']+)'", text)
    versions = {}
    for version, url in rows:
        validated_url(url)
        path_version = urllib.parse.urlsplit(url).path.split('/')[3]
        if path_version != version:
            raise ValueError('Catalog version does not match package URL')
        if version in versions and versions[version] != url:
            raise ValueError('Conflicting catalog entries')
        versions[version] = url
    if not versions:
        raise ValueError('No Ubuntu x86_64 packages found; catalog layout may have changed')
    return versions


def latest(versions):
    return max(versions, key=lambda v:tuple(int(x) for x in v.split('.')))
