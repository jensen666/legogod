// ============================================================
// 统一 API 客户端
//
// 页面唯一网络入口，统一负责：
// - API Base URL 规范化、API 路径拼接与产物 URL（/files、/views、/viz）解析；
// - JSON Content-Type、Bearer 内存凭据、超时（AbortController + Promise.race 双保险）；
// - HTTP 状态与 error/code/requestId 的统一错误对象 ApiError；
// - 网络错误（不可达/超时/中断，network=true）与业务错误（4xx/5xx，network=false）区分；
// - 每个请求生成并发送 X-Request-ID，只用于关联故障。
//
// 硬约束（改动前先读）：
// - 本模块必须能被 node 直接 import 做单测：不得在模块顶层访问 window/document/
//   localStorage/sessionStorage/cookie，必须用 typeof window !== 'undefined' 守卫。
// - API 令牌只存模块内存变量：绝不写入 localStorage/sessionStorage/cookie/URL/日志；
//   静态包不得内置令牌，浏览器部署的令牌只允许由宿主显式注入内存。
// - 日志只打印方法、去查询串的路径、状态码、耗时与 requestId，绝不打印令牌或请求头。
// ============================================================

// ---------- 运行时配置：API Base URL ----------
// 空串 = 同源组合部署；独立 Web 由 Python 静态服务在 GET /runtime-config.js 动态生成
// window.LEGOGOD_CONFIG = {"apiBaseUrl": "<--api-url 值>"}。
let baseWarned = false;

// 读取 window.LEGOGOD_CONFIG.apiBaseUrl 原始值；node/构建期没有 window 时按同源处理。
function rawBaseConfig() {
  if (typeof window === 'undefined' || !window) return '';
  const cfg = window.LEGOGOD_CONFIG;
  if (!cfg || typeof cfg !== 'object') return '';
  return typeof cfg.apiBaseUrl === 'string' ? cfg.apiBaseUrl : '';
}

/**
 * 规范化 API Base URL：空 = 同源；去掉尾部 `/`；拒绝含 `@`（userinfo）、`?`、`#` 的值。
 * 非法值退回空串并 console.warn 一次，避免请求被拼到意外的跨源地址上。
 */
export function apiBaseUrl() {
  const raw = rawBaseConfig().trim();
  if (!raw) return '';
  const normalized = raw.replace(/\/+$/, '');
  if (!normalized) return '';
  // 配置由宿主静态服务生成、不是用户输入；这里只做防御性拒绝：
  // `@` 会把主机伪装成用户名，`?`/`#` 会让 base+path 拼接产生歧义。
  if (/[@?#]/.test(normalized)) {
    if (!baseWarned) {
      baseWarned = true;
      // 不打印原值：userinfo 形式可能带账号口令，回退即可。
      console.warn('[api] LEGOGOD_CONFIG.apiBaseUrl 含非法字符（@、? 或 #），已回退为同源');
    }
    return '';
  }
  return normalized;
}

/**
 * 把以 `/` 开头的 API/产物路径按 Base URL 解析成可请求地址。
 * base 为空时保持相对路径（同源）；否则返回 `base + path`。
 */
export function apiUrl(path) {
  const p = String(path ?? '');
  if (!p.startsWith('/')) throw new TypeError('apiUrl() 的 path 必须以 / 开头：' + p);
  const base = apiBaseUrl();
  return base ? base + p : p;
}

// ---------- 产物 URL（API 只返回相对名称，客户端按 Base URL 解析） ----------
const ARTIFACT_KINDS = new Set(['files', 'views', 'viz']);

/**
 * 生成产物 URL：kind ∈ files|views|viz，name 会被 encodeURIComponent（服务端只给相对文件名）。
 * name 为空/非字符串或 kind 非法抛 TypeError，避免把空 href 或任意路径拼进页面。
 */
export function artifactUrl(kind, name) {
  if (!ARTIFACT_KINDS.has(kind)) {
    throw new TypeError('artifactUrl() 的 kind 必须是 files/views/viz：' + kind);
  }
  if (typeof name !== 'string' || !name) {
    throw new TypeError('artifactUrl() 的 name 必须是非空字符串');
  }
  return apiUrl('/' + kind + '/' + encodeURIComponent(name));
}

/** 模型/方案/步骤等 /files 产物 URL。 */
export const files = name => artifactUrl('files', name);
/** 视觉评审图 /views 产物 URL。 */
export const views = name => artifactUrl('views', name);
/** 独立 3D 页 /viz 产物 URL。 */
export const viz = name => artifactUrl('viz', name);

// ---------- Bearer 凭据：只放模块内存，绝不落持久化/URL/日志 ----------
let apiToken = null;

/**
 * 由宿主显式注入 API 令牌（浏览器里通常是部署方在内存中调用，不从静态包读取）。
 * 令牌只保存到本模块闭包变量；请求时加 `Authorization: Bearer <token>`。
 */
export function setApiToken(token) {
  const t = typeof token === 'string' ? token.trim() : '';
  apiToken = t || null;
  console.debug('[api] 内存凭据' + (apiToken ? '已设置' : '已清空'));  // 绝不打印令牌本身
}

/** 清除内存中的 API 令牌（之后请求不再带 Authorization）。 */
export function clearApiToken() {
  apiToken = null;
  console.debug('[api] 内存凭据已清空');
}

/** 当前是否持有内存 API 令牌（不返回令牌内容）。 */
export function hasApiToken() {
  return !!apiToken;
}

// ---------- 统一错误对象 ----------
/**
 * API 错误：status 为 HTTP 状态（网络/超时为 0）；code/requestId 取自后端响应，可空；
 * network=true 表示服务不可达/超时/请求中断，页面应提示连接问题而不是业务失败。
 */
export class ApiError extends Error {
  constructor(message, { status = 0, code = null, requestId = null, network = false } = {}) {
    super(String(message || 'API 请求失败'));
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
    this.network = network;
  }
}

// ---------- 请求标识（只关联故障，不含 desc/模型输出/令牌/本机路径） ----------
function newRequestId() {
  const cryptoObj = typeof globalThis !== 'undefined' ? globalThis.crypto : undefined;
  if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
    try { return cryptoObj.randomUUID(); } catch (e) { /* 退化到时间戳+随机 */ }
  }
  const rand = Math.random().toString(36).slice(2, 10) || '0';
  return `lg-${Date.now().toString(36)}-${rand}`;
}

// ---------- 内部工具 ----------
// 日志用 URL：去掉查询串与 hash（q 是用户需求文本；令牌按设计不进 URL，仍统一不打印）。
function logUrl(url) {
  const s = String(url || '');
  return s.split('?')[0].split('#')[0];
}

// 网络错误提示里的服务来源：配置了 Base 就显示 Base，否则显示“同源”。
function originLabel() {
  return apiBaseUrl() || '同源';
}

function reasonOf(e) {
  const msg = e && (e.message || String(e));
  return String(msg || '未知错误').trim();
}

/** 网络层失败统一转成 ApiError(network=true)；超时与不可达用不同文案。 */
function networkFailure(e, timedOut, requestId) {
  if (e instanceof ApiError) return e;
  if (timedOut) {
    return new ApiError(`API 请求超时（${originLabel()}）：${reasonOf(e)}`,
      { status: 0, network: true, requestId });
  }
  return new ApiError(`无法连接 API 服务（${originLabel()}）：${reasonOf(e)}`,
    { status: 0, network: true, requestId });
}

function hasHeader(headers, name) {
  const target = name.toLowerCase();
  return Object.keys(headers || {}).some(k => k.toLowerCase() === target);
}

function headerValue(res, name) {
  try {
    const h = res && res.headers;
    if (h && typeof h.get === 'function') return h.get(name) || null;
  } catch (e) { /* mock/异常响应头不可读时忽略 */ }
  return null;
}

// 读响应 JSON：空 body / 非 JSON / mock 未实现 json 时统一返回 null。
async function readJsonBody(res) {
  if (!res || typeof res.json !== 'function') return null;
  try { return await res.json(); } catch (e) { return null; }
}

function errorCodeOf(body) {
  return body && typeof body.code === 'string' && body.code ? body.code : null;
}

function errorRequestIdOf(body) {
  return body && typeof body.requestId === 'string' && body.requestId ? body.requestId : null;
}

/**
 * 底层 JSON 请求：负责超时/网络错误/HTTP 错误/200 带 error 的统一处理。
 * 成功返回解析后的 JSON；2xx 空 body 返回 null。
 */
async function fetchJson(url, { method = 'GET', headers = {}, body, timeout = 15000, requestId = '' } = {}) {
  const finalHeaders = Object.assign({}, headers);
  if (!hasHeader(finalHeaders, 'X-Request-ID')) {
    finalHeaders['X-Request-ID'] = requestId || newRequestId();
  }
  const rid = finalHeaders['X-Request-ID'];
  const init = { method, headers: finalHeaders };
  if (body !== undefined) init.body = body;
  const ctl = typeof AbortController === 'function' ? new AbortController() : null;
  if (ctl) init.signal = ctl.signal;

  let timedOut = false;
  let timer = null;
  let timeoutError = null;
  let res;
  const started = Date.now();
  console.debug('[api] →', method, logUrl(url), rid);
  try {
    let fetchPromise;
    try {
      fetchPromise = Promise.resolve(fetch(url, init));
    } catch (e) {
      throw networkFailure(e, false, rid);
    }
    if (timeout > 0) {
      const limit = timeout;
      const timeoutPromise = new Promise((_, reject) => {
        timer = setTimeout(() => {
          timedOut = true;
          if (ctl) ctl.abort();  // 通知真实 fetch 尽快结束
          timeoutError = new ApiError(`API 请求超时（${originLabel()}，${limit}ms）`,
            { status: 0, network: true, requestId: rid });
          reject(timeoutError);
        }, limit);
      });
      // 超时后真实 fetch 仍可能以 AbortError 拒绝：先挂 catch，避免 unhandledRejection。
      fetchPromise.catch(() => {});
      try {
        res = await Promise.race([fetchPromise, timeoutPromise]);
      } catch (e) {
        throw timedOut && timeoutError ? timeoutError : networkFailure(e, timedOut, rid);
      }
    } else {
      try {
        res = await fetchPromise;
      } catch (e) {
        throw networkFailure(e, timedOut, rid);
      }
    }
    if (!res) throw new ApiError('API 响应为空', { status: 0, network: true, requestId: rid });
    const status = typeof res.status === 'number' ? res.status : 0;
    const ok = typeof res.ok === 'boolean' ? res.ok : (status >= 200 && status < 300);
    const respRid = headerValue(res, 'X-Request-ID') || rid;
    const data = await readJsonBody(res);
    console.debug('[api] ←', status, method, logUrl(url), `${Date.now() - started}ms`, respRid);
    if (!ok) {
      const message = (data && typeof data.error === 'string' && data.error) ? data.error : `HTTP ${status}`;
      throw new ApiError(message, {
        status,
        code: errorCodeOf(data),
        requestId: errorRequestIdOf(data) || respRid,
        network: false,
      });
    }
    // 兼容行为：2xx 但 body 带 error 字符串仍视为失败（与服务端既有约定一致）。
    if (data && typeof data.error === 'string' && data.error) {
      throw new ApiError(data.error, {
        status,
        code: errorCodeOf(data),
        requestId: errorRequestIdOf(data) || respRid,
        network: false,
      });
    }
    return data === undefined ? null : data;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

// ---------- 对外请求入口 ----------
/**
 * 请求统一 API 路径（`path` 以 / 开头，按 Base URL 解析）。
 * @param {string} path /api/... 路径
 * @param {{method?:string, body?:any, timeout?:number, headers?:object}} [opts]
 *        body 为对象时自动 JSON.stringify 并加 Content-Type: application/json；
 *        timeout 为 0 表示不设超时；始终发送 X-Request-ID（crypto.randomUUID 优先）。
 * @returns {Promise<any>} 解析后的 JSON；2xx 空 body 为 null；失败抛 ApiError。
 */
export async function request(path, { method = 'GET', body, timeout = 15000, headers = {} } = {}) {
  const url = apiUrl(path);
  const hdrs = Object.assign({}, headers || {});
  let payload;
  if (body !== undefined && body !== null) {
    payload = typeof body === 'string' ? body : JSON.stringify(body);
    if (!hasHeader(hdrs, 'Content-Type')) hdrs['Content-Type'] = 'application/json';
  }
  if (apiToken) hdrs.Authorization = `Bearer ${apiToken}`;
  return fetchJson(url, { method, headers: hdrs, body: payload, timeout });
}

/**
 * 读取绝对或相对 URL 的 JSON（产物文件用：调用方通常传 files()/views()/viz()）。
 * 错误语义与 request 相同：网络/超时 → ApiError(network=true)，HTTP 非 2xx → ApiError(status)。
 */
export async function getJson(url, { timeout = 15000 } = {}) {
  const hdrs = {};
  if (apiToken) hdrs.Authorization = `Bearer ${apiToken}`;
  return fetchJson(String(url), { method: 'GET', headers: hdrs, timeout });
}

// ---------- API 路径常量（路径不加 /v1、不重命名现有字段） ----------
export const API = Object.freeze({
  BUILD: '/api/build',
  RETRY: '/api/retry',
  JOBS: '/api/jobs',
  PARTS: '/api/parts',
  HEALTH: '/api/health',
  job: id => '/api/job/' + encodeURIComponent(id),
});

// ---------- 常用接口便捷封装（页面统一经此访问，不各自拼路径） ----------
export const api = {
  /** 创建任务：body {desc, mode} → {id, mode}；生成耗时长，给 30s 超时。 */
  build(desc, mode) {
    return request(API.BUILD, { method: 'POST', body: { desc, mode }, timeout: 30000 });
  },
  /** 手动重试：body {jobId} → {id, mode}（服务端决定沿用原任务模式）。 */
  retry(jobId) {
    return request(API.RETRY, { method: 'POST', body: { jobId }, timeout: 15000 });
  },
  /** 任务详情：GET /api/job/<id> → 任务快照。 */
  job(id, { timeout = 10000 } = {}) {
    return request(API.job(id), { timeout });
  },
  /** 取消任务：DELETE /api/job/<id> → {cancelling:true}。 */
  cancel(id) {
    return request(API.job(id), { method: 'DELETE', timeout: 10000 });
  },
  /**
   * 任务列表：只把非空 q/status/outcome/page/pageSize 拼进查询串（数字字符串化）。
   * 无参时请求 /api/jobs（服务端返回全量 {jobs} 兼容结构）。
   */
  jobs(params = {}, { timeout = 10000 } = {}) {
    const qs = new URLSearchParams();
    for (const key of ['q', 'status', 'outcome']) {
      const v = params[key];
      if (v !== undefined && v !== null && String(v) !== '') qs.set(key, String(v));
    }
    for (const key of ['page', 'pageSize']) {
      const v = params[key];
      if (v !== undefined && v !== null && String(v) !== '') qs.set(key, String(v));
    }
    const query = qs.toString();
    return request(API.JOBS + (query ? '?' + query : ''), { timeout });
  },
  /** 零件目录：GET /api/parts → {parts:[...]}。 */
  parts() {
    return request(API.PARTS, { timeout: 15000 });
  },
  /** 最小健康信息：GET /api/health → {ok, apiVersion, status}。 */
  health() {
    return request(API.HEALTH, { timeout: 5000 });
  },
  /** 读取产物 JSON（/files 等）：与模块级 getJson 同一实现，页面统一写 api.getJson(...)。 */
  getJson(url, { timeout = 15000 } = {}) {
    return getJson(url, { timeout });
  },
};
