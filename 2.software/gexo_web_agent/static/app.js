/* G-Exo web console — plain JS, no framework.
 * State via WebSocket (fallback: manual refresh button → GET /api/state).
 * All writes go through /api/action + /api/confirm; success is only shown
 * after the backend reports the controller's real result.
 */
"use strict";

const JOINTS = ["左髋", "左膝", "右髋", "右膝"];
const $ = (id) => document.getElementById(id);

/* ------------------------------------------------ state rendering */

let lastState = null;

function fmt(n, digits = 2) {
  return typeof n === "number" ? n.toFixed(digits) : "--";
}

function renderState(payload) {
  lastState = payload;
  const badge = $("conn-badge");
  if (payload.online) {
    badge.textContent = "在线";
    badge.className = "badge online";
  } else if (payload.state) {
    badge.textContent = "数据超时";
    badge.className = "badge stale";
  } else {
    badge.textContent = "离线";
    badge.className = "badge offline";
  }

  const s = payload.state;
  $("st-online").textContent = payload.online ? "在线" : "失联";
  $("st-online").className = "value " + (payload.online ? "ok" : "err");

  if (!s) return;

  $("st-mode").textContent = s.mode === "assist" ? "助力" : "阻尼训练";
  $("st-assist").textContent = Math.round(s.assist_ratio * 100) + "%";
  $("st-estop").textContent = s.emergency_stop ? "已触发" : "正常";
  $("st-estop").className = "value " + (s.emergency_stop ? "err" : "ok");
  $("st-fault").textContent = s.fault_code ? s.fault_code : "无";
  $("st-fault").className = "value " + (s.fault_code ? "err" : "ok");
  $("st-can").textContent = s.can_online ? "在线" : "离线";
  $("st-can").className = "value " + (s.can_online ? "ok" : "err");
  $("st-battery").textContent =
    Math.round(s.battery_percent) + "% / " + fmt(s.bus_voltage, 1) + "V";
  const maxT = Math.max(...s.motor_temperature);
  $("st-temp").textContent = fmt(maxT, 1) + "℃";
  $("st-temp").className = "value " + (maxT >= 70 ? "err" : maxT >= 55 ? "warn" : "ok");

  $("st-updated").textContent = payload.last_update_ms
    ? new Date(payload.last_update_ms).toLocaleTimeString()
    : "--";

  // joints
  const tbody = $("joint-table").querySelector("tbody");
  tbody.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const tr = document.createElement("tr");
    const t = s.motor_temperature[i];
    tr.innerHTML =
      `<td>${JOINTS[i]}</td><td>${fmt(s.joint_position[i])}</td>` +
      `<td>${fmt(s.joint_velocity[i])}</td><td>${fmt(s.command_torque[i], 1)}</td>` +
      `<td>${fmt(s.estimated_torque[i], 1)}</td>` +
      `<td class="${t >= 70 ? "hot" : ""}">${fmt(t, 1)}</td>`;
    tbody.appendChild(tr);
  }

  // imu
  const grid = $("imu-grid");
  grid.innerHTML = "";
  for (let i = 0; i < 4; i++) {
    const div = document.createElement("div");
    div.className = "imu";
    div.innerHTML =
      `<span class="name">IMU ${i + 1}</span>` +
      `<span class="${s.imu_online[i] ? "ok" : "err"} value">${s.imu_online[i] ? "在线" : "离线"}</span><br>` +
      `<span class="${s.imu_calibrated[i] ? "ok" : "warn"} value" style="font-size:.72rem">` +
      `${s.imu_calibrated[i] ? "已标定" : "未标定"}</span>`;
    grid.appendChild(div);
  }

  $("debug-raw").textContent = JSON.stringify(s, null, 2);
}

/* ------------------------------------------------ websocket + fallback */

let ws = null;
let wsRetryMs = 1000;

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    try {
      renderState(JSON.parse(ev.data));
    } catch (_) {/* ignore malformed frame */}
  };
  ws.onopen = () => { wsRetryMs = 1000; };
  ws.onclose = () => {
    $("conn-badge").textContent = "连接断开";
    $("conn-badge").className = "badge offline";
    setTimeout(connectWs, wsRetryMs);
    wsRetryMs = Math.min(wsRetryMs * 2, 15000);
  };
}

async function refreshState() {
  try {
    const r = await fetch("/api/state");
    renderState(await r.json());
  } catch (_) {
    $("conn-badge").textContent = "后端不可达";
    $("conn-badge").className = "badge offline";
  }
}

/* ------------------------------------------------ action status banner */

function showActionStatus(kind, text) {
  const el = $("action-status");
  el.hidden = false;
  el.className = "action-status " + kind;
  el.textContent = text;
}

function describeResult(v) {
  const label = { set_mode: "模式切换", adjust_assist: "助力调节" }[v.action] || v.action;
  switch (v.status) {
    case "success":
      return ["success", `✅ ${label}执行成功${v.message ? "：" + v.message : ""}`];
    case "failed":
      return ["error", `❌ ${label}执行失败：${v.message || v.error_code}`];
    case "timeout":
      return ["error", `⏱ ${label}超时：${v.message || "控制器未响应"}`];
    case "rejected":
      return ["error", `🚫 ${label}被拒绝：${v.message || v.error_code}`];
    case "cancelled":
      return ["pending", "已取消"];
    case "expired":
      return ["error", "确认超时，请重新发起"];
    case "pending_confirmation":
      return ["pending", "等待确认…"];
    case "sent":
      return ["pending", "已发送，等待控制器…"];
    default:
      return ["pending", v.status];
  }
}

/* ------------------------------------------------ actions */

async function postAction(action, params) {
  showActionStatus("pending", "已发送，等待控制器…");
  let r;
  try {
    r = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, params }),
    });
  } catch (_) {
    showActionStatus("error", "❌ 后端不可达");
    return null;
  }
  if (r.status === 422) {
    const d = await r.json();
    showActionStatus("error", "🚫 " + (d.detail || "参数非法"));
    return null;
  }
  const v = await r.json();
  const [kind, text] = describeResult(v);
  showActionStatus(kind, text);
  return v;
}

/* confirm dialog */
let pendingConfirm = null;

function openConfirm(requestId, text) {
  pendingConfirm = requestId;
  $("confirm-text").textContent = text;
  $("confirm-overlay").hidden = false;
}

async function resolveConfirm(approve) {
  $("confirm-overlay").hidden = true;
  if (!pendingConfirm) return;
  const rid = pendingConfirm;
  pendingConfirm = null;
  if (!approve) {
    // tell backend so the record is closed out
    await fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: rid, approve: false }),
    }).catch(() => {});
    showActionStatus("pending", "已取消");
    return;
  }
  showActionStatus("pending", "已确认，等待控制器…");
  try {
    const r = await fetch("/api/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: rid, approve: true }),
    });
    const v = await r.json();
    const [kind, text] = describeResult(v);
    showActionStatus(kind, text);
  } catch (_) {
    showActionStatus("error", "❌ 后端不可达");
  }
}

async function requestModeSwitch(mode) {
  const v = await postAction("set_mode", { mode });
  if (v && v.status === "pending_confirmation") {
    const label = mode === "assist" ? "助力模式" : "阻尼训练模式";
    openConfirm(v.request_id, `确定要切换到「${label}」吗？请确保穿戴者站立静止。`);
  }
}

/* ------------------------------------------------ chat */

function appendMsg(cls, text, sources) {
  const log = $("chat-log");
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  if (sources && sources.length) {
    const src = document.createElement("span");
    src.className = "sources";
    src.textContent = "来源：" + sources.map((s) => s.file + (s.section ? " · " + s.section : "")).join("；");
    div.appendChild(src);
  }
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
}

async function sendChat() {
  const input = $("chat-text");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendMsg("user", text);
  $("chat-send").disabled = true;
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const v = await r.json();
    appendMsg("bot", v.reply || "（无回复）", v.sources);
    if (v.need_confirmation && v.command) {
      const mode = (v.command.params && v.command.params.mode) === "assist" ? "助力模式" : "阻尼训练模式";
      openConfirm(v.command.request_id, `确定要切换到「${mode}」吗？请确保穿戴者站立静止。`);
    }
    if (v.command && !v.need_confirmation) {
      const [kind, text2] = describeResult(v.command);
      showActionStatus(kind, text2);
    }
  } catch (_) {
    appendMsg("bot", "后端不可达，请检查服务是否启动。");
  } finally {
    $("chat-send").disabled = false;
  }
}

/* ------------------------------------------------ debug scenario switch */

async function initDebug() {
  try {
    const r = await fetch("/api/debug/scenario");
    if (!r.ok) { $("dbg-scenario").parentElement.hidden = true; return; }
    const d = await r.json();
    const sel = $("dbg-scenario");
    d.available.forEach((s) => {
      const opt = document.createElement("option");
      opt.value = opt.textContent = s;
      if (s === d.scenario) opt.selected = true;
      sel.appendChild(opt);
    });
    sel.onchange = () =>
      fetch("/api/debug/scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: sel.value }),
      });
  } catch (_) {
    $("dbg-scenario").parentElement.hidden = true;
  }
}

/* ------------------------------------------------ wire up */

$("btn-assist-mode").onclick = () => requestModeSwitch("assist");
$("btn-damping-mode").onclick = () => requestModeSwitch("damping");
$("btn-assist-up").onclick = () => postAction("adjust_assist", { delta: 0.1 });
$("btn-assist-down").onclick = () => postAction("adjust_assist", { delta: -0.1 });
$("btn-refresh").onclick = refreshState;
$("confirm-yes").onclick = () => resolveConfirm(true);
$("confirm-no").onclick = () => resolveConfirm(false);
$("chat-send").onclick = sendChat;
$("chat-text").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(); });
document.querySelectorAll(".hint").forEach((b) => {
  b.onclick = () => { $("chat-text").value = b.textContent; sendChat(); };
});

refreshState();
connectWs();
initDebug();
