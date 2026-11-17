# -*- coding: utf-8 -*-
"""Web 统一 API 客户端单测。

两部分：
1. node 执行 web/api.js（`node --input-type=module -e`，风格对齐 test_web_modes.py）：
   - 同源配置：apiUrl/产物 URL 保持相对路径；令牌只进内存、请求头带 Bearer、URL/全局不含令牌；
   - X-Request-ID 必发；JSON body/Content-Type/方法/查询串；404/400 业务错误与 2xx 带 error 的
     统一 ApiError（message/status/code/requestId/network）；网络不可达与超时 network=true；
   - 独立配置：先设 window.LEGOGOD_CONFIG 再 import，断言完整 Base URL 拼接、尾部斜杠规范化、
     非法 Base（@/?/#）回退同源、请求实际打到配置的 API 地址。
2. Python 侧静态断言：index.html 的运行时配置脚本必须早于 app.js；web/api.js 之外不得存在
   直连 /api、/files、/views、/viz 的 fetch；旧 fetchWithTimeout 已迁走；runtime-config.js 无秘密。

未安装 node 时跳过 node 用例（与 test_ui_frontend.py 同口径），静态用例始终执行。
"""
import glob
import os
import re
import shutil
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")


# ---------------------------------------------------------------- node 用例脚本
# 同源配置（无 window）：默认 Node 进程没有浏览器全局，正好验证模块可被 node 直接 import。
NODE_SAME_ORIGIN = r"""
import { API, ApiError, api, apiBaseUrl, apiUrl, artifactUrl, clearApiToken, files,
         getJson, hasApiToken, request, setApiToken, views, viz } from './web/api.js';

const fail = (msg) => { console.error(msg); process.exit(1); };
const check = (cond, msg) => { if (!cond) fail(msg); };
const eq = (actual, expected, msg) => check(actual === expected,
  msg + '：期望 ' + JSON.stringify(expected) + '，实际 ' + JSON.stringify(actual));

// 1. 同源：无 window 时 Base 为空，API 路径保持相对
eq(apiBaseUrl(), '', '无 window 时 apiBaseUrl 必须为空（同源）');
eq(apiUrl('/api/parts'), '/api/parts', '同源 apiUrl 必须保持相对路径');
check(API.BUILD === '/api/build' && API.RETRY === '/api/retry' && API.JOBS === '/api/jobs'
  && API.PARTS === '/api/parts' && API.HEALTH === '/api/health', 'API 路径常量错误');
eq(API.job('a b'), '/api/job/a%20b', 'API.job 必须 URL 编码');
eq(apiUrl('/files/model_a.json'), '/files/model_a.json', 'apiUrl 产物路径');

// 2. 产物 URL：同源 + 文件名编码；空/非法入参必须抛 TypeError
eq(files('model_a.json'), '/files/model_a.json', '同源 files');
eq(views('x y.png'), '/views/x%20y.png', '同源 views 必须编码空格');
eq(viz('lego-x.html'), '/viz/lego-x.html', '同源 viz');
eq(artifactUrl('files', 'a b.json'), '/files/a%20b.json', 'artifactUrl 编码');
const expectTypeError = (fn, msg) => {
  let ok = false;
  try { fn(); } catch (e) { ok = e instanceof TypeError; }
  check(ok, msg);
};
expectTypeError(() => files(''), 'files("") 必须抛 TypeError');
expectTypeError(() => views(null), 'views(null) 必须抛 TypeError');
expectTypeError(() => viz(undefined), 'viz(undefined) 必须抛 TypeError');
expectTypeError(() => files(123), 'files(123) 必须抛 TypeError');
expectTypeError(() => artifactUrl('bogus', 'x'), 'artifactUrl 非法 kind 必须抛 TypeError');

// 3. mock fetch：记录请求；产物 URL 与请求头随后逐项比对
const calls = [];
const jsonRes = (status, body) => ({
  status,
  ok: status >= 200 && status < 300,
  headers: { get: name => (String(name).toLowerCase() === 'x-request-id' ? 'resp-rid' : null) },
  json: async () => body,
});
globalThis.fetch = async (url, init = {}) => { calls.push({ url, init }); return jsonRes(200, { parts: [{ id: 'p1' }] }); };

// 4. 令牌：只进内存变量；请求头加 Bearer；URL/全局序列化不含令牌；清除后不再带
check(hasApiToken() === false, '初始不得持有令牌');
setApiToken('tok-secret-123');
check(hasApiToken() === true, 'setApiToken 后 hasApiToken 必须为 true');
const partsBody = await api.parts();
eq(partsBody.parts[0].id, 'p1', 'api.parts 必须返回解析后的 JSON');
let call = calls[calls.length - 1];
eq(call.url, '/api/parts', 'api.parts URL');
eq(call.init.headers.Authorization, 'Bearer tok-secret-123', '请求必须带 Authorization: Bearer');
check(!String(call.url).includes('tok-secret-123'), 'URL 不得包含令牌');
let globalDump = '';
try { globalDump = JSON.stringify(globalThis); } catch (e) {
  // node 的 globalThis.global 自引用会循环：退化到去掉自引用的序列化，仍能覆盖令牌是否泄露
  globalDump = JSON.stringify(globalThis, (k, v) => (k === 'global' || k === 'globalThis' ? undefined : v));
}
check(!globalDump.includes('tok-secret-123'), '令牌不得出现在全局对象可序列化内容中');
clearApiToken();
check(hasApiToken() === false, 'clearApiToken 后必须不再持有令牌');
await api.parts();
call = calls[calls.length - 1];
check(!('Authorization' in call.init.headers), '清除令牌后不得再带 Authorization');

// 5. X-Request-ID：每个请求必发非空标识
check(typeof call.init.headers['X-Request-ID'] === 'string' && call.init.headers['X-Request-ID'].length > 0,
  '每个请求必须发送非空 X-Request-ID');

// 6. build/retry：POST + JSON Content-Type + body 字段
globalThis.fetch = async (url, init = {}) => { calls.push({ url, init }); return jsonRes(200, { id: 'job1', mode: 'fast' }); };
const built = await api.build('一座塔', 'fast');
eq(built.id, 'job1', 'api.build 返回值');
call = calls[calls.length - 1];
eq(call.url, '/api/build', 'build URL');
eq(call.init.method, 'POST', 'build 必须 POST');
eq(call.init.headers['Content-Type'], 'application/json', 'build 必须 JSON Content-Type');
const sentBuild = JSON.parse(call.init.body);
eq(sentBuild.desc, '一座塔', 'build body.desc');
eq(sentBuild.mode, 'fast', 'build body.mode');
const retried = await api.retry('job1');
eq(retried.id, 'job1', 'api.retry 返回值');
call = calls[calls.length - 1];
eq(call.url, '/api/retry', 'retry URL');
eq(call.init.method, 'POST', 'retry 必须 POST');
eq(JSON.parse(call.init.body).jobId, 'job1', 'retry body.jobId');

// 7. job/cancel/jobs/health：路径、方法、查询串逐项比对
globalThis.fetch = async (url, init = {}) => { calls.push({ url, init }); return jsonRes(200, { ok: true }); };
await api.job('a b');
call = calls[calls.length - 1];
eq(call.url, '/api/job/a%20b', 'job URL 必须编码');
eq(call.init.method, 'GET', 'job 必须 GET');
await api.cancel('a b');
call = calls[calls.length - 1];
eq(call.url, '/api/job/a%20b', 'cancel URL');
eq(call.init.method, 'DELETE', 'cancel 必须 DELETE');
await api.jobs();
call = calls[calls.length - 1];
eq(call.url, '/api/jobs', '无参 jobs 不得拼查询串');
await api.jobs({ q: '塔', status: 'done', outcome: '', page: 2, pageSize: 20 });
call = calls[calls.length - 1];
eq(call.url, '/api/jobs?q=%E5%A1%94&status=done&page=2&pageSize=20', 'jobs 查询串（空 outcome 不加、数字字符串化）');
await api.health();
call = calls[calls.length - 1];
eq(call.url, '/api/health', 'health URL');

// 8. 2xx 空 body 返回 null
globalThis.fetch = async () => ({ status: 204, ok: true, headers: { get: () => null },
  json: async () => { throw new SyntaxError('no body'); } });
eq(await api.cancel('x'), null, '2xx 空 body 必须返回 null');

// 9. 业务错误：404 解析 error/code/requestId，message/status 精确；network=false
globalThis.fetch = async () => jsonRes(404, { error: 'unknown job', code: 'unknown_job', requestId: 'rid1' });
let err = null;
try { await api.job('nope'); } catch (e) { err = e; }
check(err instanceof ApiError, '404 必须抛 ApiError');
if (err) {
  eq(err.name, 'ApiError', '错误对象 name');
  eq(err.message, 'unknown job', 'ApiError.message 必须取后端 error 字符串');
  eq(err.status, 404, 'ApiError.status');
  eq(err.code, 'unknown_job', 'ApiError.code');
  eq(err.requestId, 'rid1', 'ApiError.requestId');
  eq(err.network, false, '业务错误 network 必须为 false');
}
// 404 且 body 非 JSON：message 退化为 HTTP <status>
globalThis.fetch = async () => ({ status: 404, ok: false, headers: { get: () => null },
  json: async () => { throw new SyntaxError('html'); } });
err = null;
try { await api.job('x'); } catch (e) { err = e; }
check(err instanceof ApiError, '无 JSON body 的 404 也必须抛 ApiError');
if (err) {
  eq(err.message, 'HTTP 404', '无 error 字段时 message 必须为 HTTP <status>');
  eq(err.status, 404, '无 JSON body 的 404 status');
  eq(err.network, false, '无 JSON body 的 404 network 必须为 false');
}
// 200 但 body.error：仍按失败处理
globalThis.fetch = async () => jsonRes(200, { error: '软错误', code: 'soft_fail' });
err = null;
try { await api.parts(); } catch (e) { err = e; }
check(err instanceof ApiError, '2xx 带 error 必须抛 ApiError');
if (err) {
  eq(err.message, '软错误', '2xx 带 error 的 message');
  eq(err.code, 'soft_fail', '2xx 带 error 的 code');
  eq(err.network, false, '2xx 带 error 的 network 必须为 false');
}

// 10. 网络不可达：network=true、status=0、message 含「无法连接」
globalThis.fetch = async () => { throw new TypeError('fetch failed'); };
err = null;
try { await api.parts(); } catch (e) { err = e; }
check(err instanceof ApiError, '网络错误必须抛 ApiError');
if (err) {
  eq(err.network, true, '网络错误 network 必须为 true');
  eq(err.status, 0, '网络错误 status 必须为 0');
  check(err.message.includes('无法连接 API 服务'), '网络错误 message 必须含「无法连接 API 服务」');
  check(err.message.includes('同源'), '同源配置网络错误 message 必须说明来源');
}

// 11. 超时：mock fetch 永不 resolve（也不响应 abort）→ 仍必须按 timeout 抛错
globalThis.fetch = () => new Promise(() => {});
err = null;
try { await request('/api/parts', { timeout: 50 }); } catch (e) { err = e; }
check(err instanceof ApiError, '超时必须抛 ApiError');
if (err) {
  eq(err.network, true, '超时 network 必须为 true');
  eq(err.status, 0, '超时 status 必须为 0');
  check(err.message.includes('超时'), '超时 message 必须含「超时」');
}

// 12. getJson：产物 JSON 读取与同样的错误语义；api.getJson 必须委托同一实现（页面调用形式）
globalThis.fetch = async () => jsonRes(200, { hello: 'world' });
eq((await getJson('/files/model.json')).hello, 'world', 'getJson 必须解析 JSON');
eq((await api.getJson('/files/model.json')).hello, 'world', 'api.getJson 必须委托模块 getJson');
globalThis.fetch = async () => jsonRes(404, { error: 'artifact missing' });
err = null;
try { await getJson('/files/none.json'); } catch (e) { err = e; }
check(err instanceof ApiError, 'getJson 404 必须抛 ApiError');
if (err) {
  eq(err.status, 404, 'getJson 404 status');
  eq(err.message, 'artifact missing', 'getJson 404 message');
  eq(err.network, false, 'getJson 业务错误 network 必须为 false');
}

console.log('ok');
"""

# 独立部署配置：必须在 import api.js 之前写入 window.LEGOGOD_CONFIG。
NODE_INDEPENDENT = r"""
globalThis.window = { LEGOGOD_CONFIG: { apiBaseUrl: 'http://127.0.0.1:8600/' } };
const { apiBaseUrl, apiUrl, files, views, viz } = await import('./web/api.js');

const fail = (msg) => { console.error(msg); process.exit(1); };
const check = (cond, msg) => { if (!cond) fail(msg); };
const eq = (actual, expected, msg) => check(actual === expected,
  msg + '：期望 ' + JSON.stringify(expected) + '，实际 ' + JSON.stringify(actual));

// 1. Base URL 规范化：保留主机端口、去掉尾部斜杠
eq(apiBaseUrl(), 'http://127.0.0.1:8600', '独立部署 apiBaseUrl 必须去掉尾部斜杠');
eq(apiUrl('/api/parts'), 'http://127.0.0.1:8600/api/parts', '独立部署 apiUrl 必须拼完整 Base URL');

// 2. 产物 URL：两种配置下完整值都要按 Base URL 解析
eq(files('model_a.json'), 'http://127.0.0.1:8600/files/model_a.json', '独立部署 files');
eq(views('x y.png'), 'http://127.0.0.1:8600/views/x%20y.png', '独立部署 views 必须编码');
eq(viz('lego-x.html'), 'http://127.0.0.1:8600/viz/lego-x.html', '独立部署 viz');

// 3. 实际请求必须打到配置的 API 地址（而不是同源静态服务）
let seen = [];
globalThis.fetch = async (url) => {
  seen.push(url);
  return { status: 200, ok: true, headers: { get: () => null }, json: async () => ({ parts: [] }) };
};
const { api } = await import('./web/api.js');
await api.parts();
eq(seen[seen.length - 1], 'http://127.0.0.1:8600/api/parts', 'api.parts 必须请求配置的 Base URL');

// 4. 非法 Base：含 @(userinfo)/?/# 一律回退同源，不静默拼到可疑地址
const badValues = [
  'http://user:pass@127.0.0.1:8600',
  'http://127.0.0.1:8600/?x=1',
  'http://127.0.0.1:8600/#hash',
];
for (const bad of badValues) {
  globalThis.window.LEGOGOD_CONFIG.apiBaseUrl = bad;
  eq(apiBaseUrl(), '', '非法 Base 必须回退空串：' + bad);
  eq(apiUrl('/api/parts'), '/api/parts', '非法 Base 回退后必须同源：' + bad);
}

// 5. 空配置 = 同源组合部署
globalThis.window.LEGOGOD_CONFIG.apiBaseUrl = '';
eq(apiUrl('/files/x.json'), '/files/x.json', '空配置必须保持同源相对路径');

console.log('ok');
"""


def _read(path):
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


class WebApiClientNodeTest(unittest.TestCase):
    """node 直接 import web/api.js 的行为断言（真实比对期望值）。"""

    def _run_node(self, source, label):
        node = shutil.which("node")
        if not node:
            self.skipTest("未安装 node，跳过 web/api.js 客户端单测")
        proc = subprocess.run([node, "--input-type=module", "-e", source],
                              cwd=ROOT, capture_output=True, text=True,
                              encoding="utf-8", timeout=30)
        self.assertEqual(proc.returncode, 0, "[%s] %s" % (label, proc.stderr or proc.stdout))
        self.assertIn("ok", proc.stdout, "[%s] node 用例未输出 ok" % label)

    def test_same_origin_artifacts_token_errors_timeout(self):
        self._run_node(NODE_SAME_ORIGIN, "同源")

    def test_independent_base_url(self):
        self._run_node(NODE_INDEPENDENT, "独立部署")


class WebApiClientStaticTest(unittest.TestCase):
    """静态验收：加载顺序、唯一网络入口、运行时配置无秘密。"""

    def test_index_loads_runtime_config_before_app(self):
        html = _read(os.path.join(WEB_DIR, "index.html"))
        cfg = '<script src="/runtime-config.js"></script>'
        app = '<script type="module" src="/web/app.js"></script>'
        self.assertIn(cfg, html, "index.html 必须加载 /runtime-config.js")
        self.assertIn(app, html, "index.html 必须加载 /web/app.js")
        self.assertLess(html.index(cfg), html.index(app),
                        "runtime-config.js 必须在 app.js 之前加载（§6.2-4）")

    def test_no_direct_api_fetch_outside_api_client(self):
        js_files = sorted(glob.glob(os.path.join(WEB_DIR, "*.js"))) + \
            sorted(glob.glob(os.path.join(WEB_DIR, "pages", "*.js")))
        fetch_re = re.compile(r"fetch\s*\(")
        api_path_re = re.compile(r"""['"`][^'"`]*/(?:api|files|views|viz)(?:/|['"`])""")
        scanned = 0
        for path in js_files:
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            # web/api.js 是唯一网络入口；viewer.js 的 /api/parts 是历史注释，不参与直连判定
            if rel in ("web/api.js", "web/viewer.js"):
                continue
            src = _read(path)
            scanned += 1
            for match in fetch_re.finditer(src):
                snippet = src[match.start():match.start() + 240]
                self.assertIsNone(
                    api_path_re.search(snippet),
                    "%s 存在直连 /api、/files、/views 或 /viz 的 fetch：%r" % (rel, snippet[:120]))
        self.assertGreater(scanned, 0, "必须实际扫描到 web 前端脚本")
        api_src = _read(os.path.join(WEB_DIR, "api.js"))
        self.assertIn("fetch(url, init)", api_src, "web/api.js 必须是唯一底层 fetch 调用点")
        self.assertIn("export async function request", api_src, "web/api.js 必须导出 request")

    def test_fetch_with_timeout_removed(self):
        for path in sorted(glob.glob(os.path.join(WEB_DIR, "*.js"))):
            self.assertNotIn("fetchWithTimeout", _read(path),
                             os.path.basename(path) + " 不得再保留 fetchWithTimeout（已迁到 api.js）")

    def test_runtime_config_is_secret_free(self):
        src = _read(os.path.join(WEB_DIR, "runtime-config.js"))
        self.assertIn("window.LEGOGOD_CONFIG = window.LEGOGOD_CONFIG || { apiBaseUrl: '' };", src,
                      "runtime-config.js 必须提供空的 apiBaseUrl 兜底")
        for banned in ("Bearer", "Authorization", "apiToken", "localStorage", "sessionStorage",
                       "document.cookie"):
            self.assertNotIn(banned, src, "runtime-config.js 不得含令牌/持久化样式字符串：%s" % banned)


if __name__ == "__main__":
    unittest.main()
