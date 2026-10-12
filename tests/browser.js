// Exercise the generated browser method without network, login, or a desktop.
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const text = fs.readFileSync(process.argv[2], 'utf8');
const start = text.indexOf('OpenDefaultBrowser(o,e=true){');
const end = text.indexOf('rebootComputer(){', start);
assert(start >= 0 && end > start, 'Browser method boundaries changed');
const method = text.slice(start, end);
function run(url, gateway, expected) {
  const launches = [];
  const context = {
    URL, Error, JSON, encodeURI, console, LOG_TAG:'test',
    os: {platform: () => 'linux'},
    Common: {SYS_LINUX:'linux', SYS_WIN32:'win32', isURLlegal: u => {
      try { return ['http:', 'https:'].includes(new URL(u).protocol); } catch (_) { return false; }
    }},
    Log: {info(){},warn(){},error(){}},
    process: {env: {ATRUST_GATEWAY:gateway, LD_LIBRARY_PATH:'private', LD_PRELOAD:'private',
      QT_QPA_PLATFORM_PLUGIN_PATH:'private', QT_PLUGIN_PATH:'private', DISPLAY:':0'}},
    require: name => name.includes('history_addr') ? {getLastHistoryAddr: () => ({addr:gateway})} :
      {urlAddLanguageConfig:u=>u, currentLanguage:()=>''},
    childProcess: {execFile(path,args,options,callback) {
      launches.push({path,args,env:options.env});callback(null);
    }},
    shell:{openExternal(){throw Error('Linux browser bypassed clean launcher');}}
  };
  vm.createContext(context);
  vm.runInContext(`class Util {${method}}; new Util().OpenDefaultBrowser(${JSON.stringify(url)});`, context);
  if (!expected) return assert.strictEqual(launches.length, 0);
  assert.strictEqual(launches.length, 1);
  assert.strictEqual(launches[0].path, '/usr/bin/xdg-open');
  for (const k of ['LD_LIBRARY_PATH','LD_PRELOAD','QT_QPA_PLATFORM_PLUGIN_PATH','QT_PLUGIN_PATH'])
    assert(!(k in launches[0].env), `Inherited ${k}`);
  assert.strictEqual(launches[0].env.DISPLAY, ':0');
  const u = new URL(launches[0].args[0]);
  for (const [k,v] of Object.entries(expected)) {
    assert.strictEqual(k === 'host' ? u.host : u.searchParams.get(k), v);
  }
}
run('/passport/v1/public/casLogin?lang=&sfDomain=school.example','https://gateway.example',
  {host:'gateway.example',lang:'zh-CN',platform:'Linux',clientType:'SDPBrowserClient',sfDomain:'school.example'});
run('https://other.example/passport/v1/public/casLogin?clientType=SDPClient&platform=Linux&lang=en-US',
  'https://gateway.example',{host:'other.example',clientType:'SDPClient',lang:'en-US'});
run('https://other.example/oidc/login?state=test','https://gateway.example',
  {host:'other.example',state:'test'});
run('javascript:alert(1)','https://gateway.example',null);
console.log('Browser regression checks passed');
