"""Single-page authorization UI (GET /) — inline HTML, zero build step.

Flow: POST /api/v1/auth/start -> open the authorize URL in a new tab -> paste
the redirected callback URL -> POST /api/v1/auth/callback. Token state comes
from GET /api/v1/status, which also surfaces keepalive errors.
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter(tags=["ui"])

# Plain string (no f-string): the page is full of JS/CSS braces.
_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Schwab API 授权管理</title>
<style>
  :root { --bg:#0f1419; --card:#1a2129; --line:#2c3644; --fg:#e6edf3; --muted:#8b98a5;
          --green:#2ea86e; --red:#e5534b; --amber:#d29922; --accent:#4c8dff; }
  * { box-sizing: border-box; }
  body { margin:0; padding:2rem; background:var(--bg); color:var(--fg);
         font:15px/1.6 -apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif; }
  .wrap { max-width:640px; margin:0 auto; }
  h1 { font-size:1.25rem; margin:0 0 1rem; }
  .card { background:var(--card); border:1px solid var(--line); border-radius:10px;
          padding:1.25rem; margin-bottom:1rem; }
  .badge { display:inline-block; padding:.15rem .7rem; border-radius:999px; font-size:.85rem; font-weight:600; }
  .ok  { background:var(--green); color:#04110a; }
  .bad { background:var(--red); color:#fff; }
  .warn{ background:var(--amber); color:#241a00; }
  .muted { color:var(--muted); font-size:.88rem; }
  .kv { display:flex; justify-content:space-between; gap:1rem; padding:.2rem 0; }
  button { background:var(--accent); border:0; color:#fff; border-radius:8px;
           padding:.55rem 1.1rem; font-size:.95rem; cursor:pointer; margin-top:.6rem; }
  button:disabled { opacity:.5; cursor:default; }
  textarea { width:100%; min-height:74px; background:#0b0f14; color:var(--fg);
             border:1px solid var(--line); border-radius:8px; padding:.6rem; font:13px/1.5 ui-monospace,monospace; }
  .msg { margin-top:.7rem; font-size:.88rem; white-space:pre-wrap; word-break:break-all; }
  .msg.err { color:var(--red); }
  .msg.good { color:var(--green); }
  details { margin-top:.9rem; }
  summary { cursor:pointer; color:var(--muted); }
  li { margin:.25rem 0; }
  label.chk { display:flex; gap:.4rem; align-items:center; margin-top:.6rem; color:var(--muted); font-size:.88rem; }
</style>
</head>
<body>
<div class="wrap">
  <h1>Schwab API 授权管理</h1>

  <div class="card">
    <div id="badge" class="badge warn">加载中…</div>
    <div id="detail" class="muted" style="margin-top:.6rem"></div>
    <div id="keepalive" class="msg"></div>
  </div>

  <div class="card">
    <b>第一步：打开 Schwab 登录页</b>
    <div class="muted">新窗口打开授权页面，登录并同意后，浏览器会跳转到一个打不开的 https://127.0.0.1/... 地址
    ——这是正常的，复制地址栏完整 URL。</div>
    <label class="chk"><input type="checkbox" id="force"> 强制重新授权（token 未过期时默认拒绝）</label>
    <button id="startBtn" onclick="startAuth()">打开 Schwab 登录页</button>
    <div id="startMsg" class="msg"></div>
  </div>

  <div class="card">
    <b>第二步：等待自动完成，或粘贴回调 URL</b>
    <div class="muted">若回调地址指向本服务（/api/v1/auth/redirect），登录后授权自动完成，本步可跳过。
    否则：浏览器跳转到打不开的页面属正常现象，复制地址栏完整 URL（30 秒内有效）粘到这里提交。</div>
    <textarea id="callback" placeholder="https://127.0.0.1/?code=...&session=..."></textarea>
    <button id="submitBtn" onclick="submitCallback()">提交授权</button>
    <div id="submitMsg" class="msg"></div>
    <details>
      <summary>授权失败？先检查这几项</summary>
      <ul>
        <li>Schwab 开发者后台 App 状态为 "Ready For Use"</li>
        <li>App key 和 app secret 有效</li>
        <li>authorization code 30 秒内有效——登录后立即粘贴提交</li>
        <li>本服务 CALLBACK_URL 与 App 注册的回调地址完全一致（https 开头、无尾斜杠）</li>
      </ul>
    </details>
  </div>
</div>

<script>
const $ = (id) => document.getElementById(id);

function fmtDuration(sec) {
  if (sec === undefined || sec === null) return "";
  if (sec <= 0) return "已过期";
  const d = Math.floor(sec / 86400), h = Math.floor(sec % 86400 / 3600), m = Math.floor(sec % 3600 / 60);
  if (d > 0) return d + " 天 " + h + " 小时";
  if (h > 0) return h + " 小时 " + m + " 分钟";
  return m + " 分钟";
}

function render(status) {
  const badge = $("badge"), detail = $("detail");
  if (!status.credentials_configured) {
    badge.className = "badge bad"; badge.textContent = "未配置凭据";
    detail.textContent = "需要设置 FA_SCHWAB_APP_KEY / FA_SCHWAB_APP_SECRET 环境变量。";
    return;
  }
  if (!status.authenticated) {
    badge.className = "badge bad"; badge.textContent = "未认证";
    detail.textContent = "完成下方两步授权后即可使用数据接口。";
  } else if (status.refresh_token_expired) {
    badge.className = "badge warn"; badge.textContent = "Refresh token 已过期";
    detail.textContent = "请重新走一遍授权流程。";
  } else {
    badge.className = "badge ok"; badge.textContent = "已认证";
    detail.textContent = "";
    const rows = [
      ["Access token 剩余", fmtDuration(status.access_token_ttl_seconds)],
      ["Refresh token 剩余", fmtDuration(status.refresh_token_ttl_seconds)],
    ];
    for (const [k, v] of rows) {
      if (!v) continue;
      const div = document.createElement("div");
      div.className = "kv";
      div.innerHTML = "<span class='muted'>" + k + "</span><span>" + v + "</span>";
      detail.appendChild(div);
    }
  }
  const ka = status.keepalive || {};
  const lines = ["保活周期: 每 " + (ka.interval_hours ?? "?") + " 小时自动轮换 refresh token"];
  if (ka.last_refresh) lines.push("上次轮换: " + new Date(ka.last_refresh).toLocaleString());
  if (ka.last_error) lines.push("⚠ 最近轮换失败: " + ka.last_error);
  $("keepalive").className = "msg" + (ka.last_error ? " err" : "");
  $("keepalive").textContent = lines.join("\\n");
}

async function refresh() {
  try {
    render(await (await fetch("/api/v1/status")).json());
  } catch (e) {
    $("badge").className = "badge bad"; $("badge").textContent = "服务不可达";
  }
}

async function showHttpError(el, response) {
  let detail = response.status + " " + response.statusText;
  try {
    const body = await response.json();
    if (body.detail) detail = typeof body.detail === "string"
      ? body.detail
      : [body.detail.schwab_status ? "Schwab HTTP " + body.detail.schwab_status : "", body.detail.schwab_body || ""]
          .filter(Boolean).join("\\n") || JSON.stringify(body.detail);
  } catch (_) {}
  el.className = "msg err"; el.textContent = detail;
}

async function startAuth() {
  const msg = $("startMsg"), btn = $("startBtn");
  btn.disabled = true; msg.className = "msg"; msg.textContent = "请求授权地址…";
  try {
    const force = $("force").checked ? "?force=true" : "";
    const response = await fetch("/api/v1/auth/start" + force, { method: "POST" });
    if (response.status === 409) {
      msg.className = "msg good";
      msg.textContent = "已有有效 token，无需重新授权。如需强制重授权，勾选上方选项。";
      return;
    }
    if (!response.ok) { await showHttpError(msg, response); return; }
    const body = await response.json();
    window.open(body.authorize_url, "_blank");
    msg.className = "msg good";
    msg.textContent = "已在新窗口打开 Schwab 登录页。登录后复制地址栏完整 URL 到下方。";
  } catch (e) {
    msg.className = "msg err"; msg.textContent = "请求失败: " + e;
  } finally {
    btn.disabled = false;
  }
}

async function submitCallback() {
  const msg = $("submitMsg"), btn = $("submitBtn"), value = $("callback").value.trim();
  if (!value) { msg.className = "msg err"; msg.textContent = "请先粘贴回调 URL。"; return; }
  btn.disabled = true; msg.className = "msg"; msg.textContent = "交换 token…";
  try {
    const response = await fetch("/api/v1/auth/callback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ callback: value }),
    });
    if (!response.ok) { await showHttpError(msg, response); await refresh(); return; }
    msg.className = "msg good"; msg.textContent = "授权成功，token 已入库。";
    $("callback").value = "";
    await refresh();
  } catch (e) {
    msg.className = "msg err"; msg.textContent = "请求失败: " + e;
  } finally {
    btn.disabled = false;
  }
}

refresh();
setInterval(refresh, 30000);
</script>
</body>
</html>
"""


@router.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    return HTMLResponse(_PAGE)
