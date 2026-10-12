"""Known Fedora adaptation; incompatible upstream changes fail the build."""
from pathlib import Path
import hashlib
import subprocess

PROFILE = "fedora44-linux-v1"
HISTORY_GUARD = ('os.platform()===Common.SYS_LINUX&&'
    '(Common.getOsName()===Common.OS_KYLIN_V10||Common.getOsName().indexOf(Common.OS_UBUNTU_16)!=-1)')


class UnsupportedUpstream(RuntimeError):
    pass


def replace_exact(text, before, after, count, label):
    actual = text.count(before)
    if actual != count:
        raise UnsupportedUpstream(f"{label}: expected {count} anchors, found {actual}; publication stopped")
    return text.replace(before, after)


def apply(root: Path):
    required = ["aTrustTray", "resources/bin/aTrustAgent", "resources/bin/libcurl.so",
                "resources/bin/libsqlite3.so", "resources/bin/libmmkv.so",
                "resources/app/src/service/history_addr.js", "resources/app/src/service/util/util.js"]
    for rel in required:
        if not (root / rel).is_file():
            raise UnsupportedUpstream(f"Missing required upstream file: {rel}")
    mmkv = root / "resources/bin/libmmkv.so"
    original_mmkv = hashlib.sha256(mmkv.read_bytes()).hexdigest()
    report = {"profile": PROFILE, "changes": [], "machine_code_modified": False}
    old_std = root / "resources/lib/libstdc++.so.6"
    if old_std.exists() or old_std.is_symlink():
        old_std.unlink()
        report["changes"].append("Use Fedora libstdc++ instead of old bundled copy")
    alias = root / "resources/bin/libcurl.so.4"
    if alias.exists() or alias.is_symlink():
        if not alias.is_symlink() or alias.readlink() != Path("libcurl.so"):
            raise UnsupportedUpstream("Upstream curl ABI/layout changed; review required")
    else:
        alias.symlink_to("libcurl.so")
    report["changes"].append("Keep curl/OpenSSL 1.1 ABI together in client process")

    p = root / "resources/app/src/service/history_addr.js"
    text = p.read_text()
    guards = text.count(HISTORY_GUARD)
    if guards != 6:
        raise UnsupportedUpstream(f"History helper layout changed: found {guards} compatibility guards")
    p.write_text(text.replace(HISTORY_GUARD, "os.platform()===Common.SYS_LINUX"))
    report["changes"].append(f"Use existing native Linux history helper ({guards} sites)")

    p = root / "resources/app/src/service/util/util.js"
    text = p.read_text()
    before = "OpenDefaultBrowser(o,e=true){if(null==o)return;"
    after = before + ('if(os.platform()===Common.SYS_LINUX&&o.startsWith("/")){'
        'try{const g=require("../history_addr").getLastHistoryAddr().addr||process.env.ATRUST_GATEWAY;'
        'if(g){o=new URL(o,g).href}}'
        'catch(r){Log.error(LOG_TAG,"Unable to resolve relative browser URL",r);return}}')
    text = replace_exact(text, before, after, 1, "Relative browser URL")
    before = "shell.openExternal(o).then"
    after = ('if(os.platform()===Common.SYS_LINUX){'
        'const cleanEnv=Object.assign({},process.env);'
        'for(const key of ["LD_LIBRARY_PATH","LD_PRELOAD","QT_QPA_PLATFORM_PLUGIN_PATH","QT_PLUGIN_PATH"]){delete cleanEnv[key]}'
        'childProcess.execFile("/usr/bin/xdg-open",[o],{env:cleanEnv},r=>{'
        'if(r){Log.error(LOG_TAG,"Clean browser launch failed",r)}'
        'else{Log.info(LOG_TAG,"Clean browser launch succeeded")}});return;}' + before)
    text = replace_exact(text, before, after, 1, "External browser environment")
    before = 'Log.info(LOG_TAG,"openDefaultBrowser webUrl:",o);'
    after = ('if(os.platform()===Common.SYS_LINUX){const u=new URL(o);'
        'if(u.pathname==="/passport/v1/public/casLogin") {'
        'if(!u.searchParams.get("clientType")){u.searchParams.set("clientType","SDPBrowserClient")}'
        'if(!u.searchParams.get("platform")){u.searchParams.set("platform","Linux")}'
        'if(!u.searchParams.get("lang")){u.searchParams.set("lang",'
        'require("../../controller/language_controller").currentLanguage()||"zh-CN")}'
        'o=u.href}}' + before)
    text = replace_exact(text, before, after, 1, "CAS common parameters")
    p.write_text(text)
    report["changes"].extend(["Resolve relative URLs against selected gateway",
        "Launch external browser without private loader variables",
        "Fill missing website-standard CAS parameters"])
    for rel in ["resources/app/src/service/history_addr.js", "resources/app/src/service/util/util.js"]:
        subprocess.run(["node", "--check", str(root / rel)], check=True)
    if hashlib.sha256(mmkv.read_bytes()).hexdigest() != original_mmkv:
        raise RuntimeError("MMKV binary unexpectedly changed")
    return report
