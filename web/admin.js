const adminLoginView = document.querySelector("#adminLoginView");
const adminLoginForm = document.querySelector("#adminLoginForm");
const adminUsername = document.querySelector("#adminUsername");
const adminPassword = document.querySelector("#adminPassword");
const adminLoginError = document.querySelector("#adminLoginError");
const adminLoginSubmit = document.querySelector("#adminLoginSubmit");
const adminHeader = document.querySelector(".admin-header");
const adminLayout = document.querySelector(".admin-layout");
const adminLogoutButton = document.querySelector("#adminLogoutButton");
const summaryCards = document.querySelector("#summaryCards");
const dashboardUpdatedAt = document.querySelector("#dashboardUpdatedAt");
const trafficChart = document.querySelector("#trafficChart");
const sopFunnel = document.querySelector("#sopFunnel");
const intentPie = document.querySelector("#intentPie");
const stageBars = document.querySelector("#stageBars");
const sourcePie = document.querySelector("#sourcePie");
const agentTable = document.querySelector("#agentTable");
const ragSummaryCards = document.querySelector("#ragSummaryCards");
const ragTrendChart = document.querySelector("#ragTrendChart");
const ragComparison = document.querySelector("#ragComparison");
const ragRecentTable = document.querySelector("#ragRecentTable");
const rangeButtons = document.querySelectorAll("[data-range]");
const adminConfigPath = document.querySelector("#adminConfigPath");
const adminConfigForm = document.querySelector("#adminConfigForm");
const adminConfigStatus = document.querySelector("#adminConfigStatus");
const saveConfigButton = document.querySelector("#saveConfigButton");
const restartServiceButton = document.querySelector("#restartServiceButton");

const SERIES_COLORS = ["#0f766e", "#2563eb", "#f59e0b", "#16a34a", "#dc2626", "#7c3aed"];
const PIE_COLORS = ["#0f766e", "#2563eb", "#f59e0b", "#16a34a", "#dc2626", "#64748b"];
const ADMIN_AUTH_KEY = "sales-agent-admin-auth";

let activeRange = "7d";

async function fetchJson(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: adminAuthHeaders(options.headers || {}),
  });
  if ((response.status === 401 || response.status === 403) && url.startsWith("/api/admin/")) {
    logoutAdmin("登录已失效，请重新登录。");
  }
  if (!response.ok) {
    let detail = "";
    try {
      const payload = await response.json();
      detail = typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail || payload);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `请求失败（HTTP ${response.status}）`);
  }
  return response.json();
}

function readAdminAuth() {
  try {
    const raw = window.localStorage.getItem(ADMIN_AUTH_KEY);
    const auth = raw ? JSON.parse(raw) : null;
    if (!auth?.access_token || Number(auth.expires_at || 0) * 1000 <= Date.now()) {
      window.localStorage.removeItem(ADMIN_AUTH_KEY);
      return null;
    }
    return auth;
  } catch {
    window.localStorage.removeItem(ADMIN_AUTH_KEY);
    return null;
  }
}

function adminAuthHeaders(extraHeaders = {}) {
  const token = readAdminAuth()?.access_token || "";
  return {
    Accept: "application/json",
    ...extraHeaders,
    ...(token && location.pathname === "/admin" ? { Authorization: `Bearer ${token}` } : {}),
  };
}

function showAdminLogin(message = "") {
  adminLoginView.hidden = false;
  adminHeader.hidden = true;
  adminLayout.hidden = true;
  adminLoginError.textContent = message;
  adminLoginError.hidden = !message;
  adminPassword.value = "";
  adminUsername.focus();
}

function showAdminApp() {
  adminLoginView.hidden = true;
  adminHeader.hidden = false;
  adminLayout.hidden = false;
}

async function handleAdminLogin(event) {
  event.preventDefault();
  const username = adminUsername.value.trim();
  const password = adminPassword.value;
  if (!username || !password) {
    showAdminLogin("请输入管理员账号和密码。");
    return;
  }
  adminLoginSubmit.disabled = true;
  adminLoginError.hidden = true;
  try {
    const response = await fetch("/api/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!response.ok) {
      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }
      throw new Error(payload.detail || "管理员账号或密码错误。");
    }
    const auth = await response.json();
    window.localStorage.setItem(ADMIN_AUTH_KEY, JSON.stringify(auth));
    showAdminApp();
    await initializeAdmin();
  } catch (error) {
    showAdminLogin(error.message || "登录失败，请稍后重试。");
  } finally {
    adminLoginSubmit.disabled = false;
  }
}

function logoutAdmin(message = "") {
  window.localStorage.removeItem(ADMIN_AUTH_KEY);
  showAdminLogin(message);
}

async function loadDashboard() {
  const bucket = activeRange === "24h" ? "hour" : "day";
  const [summary, timeseries, distribution, agents, funnel] = await Promise.all([
    fetchJson("/api/admin/dashboard/summary"),
    fetchJson(`/api/admin/dashboard/timeseries?range=${encodeURIComponent(activeRange)}&bucket=${bucket}`),
    fetchJson("/api/admin/dashboard/distribution"),
    fetchJson(`/api/admin/dashboard/agent-performance?range=${encodeURIComponent(activeRange)}`),
    fetchJson("/api/admin/dashboard/sop-funnel"),
  ]);
  renderSummary(summary);
  renderTrafficChart(timeseries);
  renderBars(stageBars, distribution.sop_stage || []);
  renderPie(intentPie, distribution.purchase_intent || []);
  renderPie(sourcePie, distribution.message_source || []);
  renderAgentTable(agents.agents || []);
  renderFunnel(funnel.stages || []);
  await loadSalesRagDashboard(bucket);
}

function renderSummary(summary) {
  dashboardUpdatedAt.textContent = `更新时间：${formatDateTime(summary.generated_at)}`;
  summaryCards.innerHTML = "";
  for (const card of summary.cards || []) {
    const node = document.createElement("article");
    node.className = "metric-card";
    node.innerHTML = `<span>${escapeHtml(card.label)}</span><strong>${formatValue(card.value)}${card.suffix || ""}</strong>`;
    summaryCards.appendChild(node);
  }
}

async function loadSalesRagDashboard(bucket) {
  const [summary, timeseries, comparison, recent] = await Promise.all([
    fetchJson(`/api/admin/dashboard/sales-rag/summary?range=${encodeURIComponent(activeRange)}`),
    fetchJson(`/api/admin/dashboard/sales-rag/timeseries?range=${encodeURIComponent(activeRange)}&bucket=${bucket}`),
    fetchJson(`/api/admin/dashboard/sales-rag/comparison?range=${encodeURIComponent(activeRange)}`),
    fetchJson("/api/admin/dashboard/sales-rag/recent-uses?limit=8"),
  ]);
  renderMetricCards(ragSummaryCards, summary.cards || []);
  renderLineChart(ragTrendChart, timeseries.series || []);
  renderRagComparison(comparison.groups || []);
  renderRagRecentTable(recent.items || []);
}

async function loadAdminConfig() {
  const payload = await fetchJson("/api/admin/config");
  adminConfigPath.textContent = `配置文件：${payload.env_file || ".env"}`;
  renderAdminConfig(payload.items || []);
}

function renderAdminConfig(items) {
  adminConfigForm.innerHTML = "";
  let currentGroup = "";
  for (const item of items) {
    if (item.group !== currentGroup) {
      currentGroup = item.group;
      const groupTitle = document.createElement("div");
      groupTitle.className = "config-group-title";
      groupTitle.textContent = currentGroup;
      adminConfigForm.appendChild(groupTitle);
    }
    const field = document.createElement("label");
    field.className = "config-field";
    const label = document.createElement("span");
    label.textContent = item.label || item.key;
    field.appendChild(label);
    const input = document.createElement("input");
    input.dataset.configKey = item.key;
    input.dataset.configType = item.type || "string";
    input.title = item.description || item.key;
    if (item.type === "bool") {
      input.type = "checkbox";
      input.checked = ["true", "1", "yes", "on"].includes(String(item.value).toLowerCase());
    } else {
      input.type = item.type === "int" || item.type === "float" ? "number" : "text";
      if (input.type === "number") {
        input.step = item.type === "float" ? "0.1" : "1";
        input.min = "0";
      }
      input.value = item.value ?? "";
    }
    field.appendChild(input);
    const description = document.createElement("small");
    description.textContent = item.description || "";
    field.appendChild(description);
    adminConfigForm.appendChild(field);
  }
}

function readAdminConfig() {
  const updates = {};
  adminConfigForm.querySelectorAll("[data-config-key]").forEach((input) => {
    const key = input.dataset.configKey;
    updates[key] = input.dataset.configType === "bool" ? input.checked : input.value;
  });
  return updates;
}

function setConfigStatus(message, kind = "") {
  adminConfigStatus.textContent = message;
  adminConfigStatus.className = `config-status${kind ? ` ${kind}` : ""}`;
}

async function saveAdminConfig() {
  saveConfigButton.disabled = true;
  setConfigStatus("正在保存配置……");
  try {
    const result = await fetchJson("/api/admin/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ updates: readAdminConfig() }),
    });
    const rejected = result.rejected?.length ? `，已忽略：${result.rejected.join(", ")}` : "";
    setConfigStatus(`已保存 ${result.saved?.length || 0} 项${rejected}。点击“重启服务”后生效。`, "success");
  } catch (error) {
    setConfigStatus(error.message || "配置保存失败。", "error");
  } finally {
    saveConfigButton.disabled = false;
  }
}

async function restartAdminService() {
  restartServiceButton.disabled = true;
  setConfigStatus("正在请求 Windows Python 服务重启……");
  try {
    const result = await fetchJson("/api/admin/restart", { method: "POST" });
    setConfigStatus(result.message || "服务正在重启，请稍候刷新页面。", "success");
  } catch (error) {
    setConfigStatus(error.message || "服务重启失败。", "error");
    restartServiceButton.disabled = false;
  }
}

function renderMetricCards(target, cards) {
  target.innerHTML = "";
  for (const card of cards) {
    const node = document.createElement("article");
    node.className = "metric-card";
    node.innerHTML = `<span>${escapeHtml(card.label)}</span><strong>${formatValue(card.value)}${card.suffix || ""}</strong>`;
    target.appendChild(node);
  }
}

function renderTrafficChart(payload) {
  const wanted = new Set(["new_sessions", "customer_messages", "ai_replies", "handover", "safety_triggers", "sales_rag_hits"]);
  const series = (payload.series || []).filter((item) => wanted.has(item.key));
  renderLineChart(trafficChart, series);
}

function renderLineChart(target, series) {
  if (!series.length) {
    target.innerHTML = `<div class="empty-note">暂无趋势数据</div>`;
    return;
  }
  const width = 900;
  const height = 250;
  const padding = { top: 16, right: 18, bottom: 34, left: 38 };
  const pointsCount = Math.max(...series.map((item) => item.points.length), 1);
  const maxValue = Math.max(...series.flatMap((item) => item.points.map((point) => Number(point.value) || 0)), 1);
  const x = (index) => padding.left + (index * (width - padding.left - padding.right)) / Math.max(pointsCount - 1, 1);
  const y = (value) => height - padding.bottom - ((Number(value) || 0) * (height - padding.top - padding.bottom)) / maxValue;
  const paths = series.map((item, seriesIndex) => {
    const d = item.points.map((point, index) => `${index === 0 ? "M" : "L"}${x(index).toFixed(1)} ${y(point.value).toFixed(1)}`).join(" ");
    const color = SERIES_COLORS[seriesIndex % SERIES_COLORS.length];
    return `<path d="${d}" fill="none" stroke="${color}" stroke-width="2.5" />`;
  }).join("");
  const labels = (series[0]?.points || [])
    .filter((_, index, items) => index === 0 || index === items.length - 1 || index === Math.floor(items.length / 2))
    .map((point, index, items) => {
      const pointIndex = series[0].points.indexOf(point);
      const anchor = index === 0 ? "start" : index === items.length - 1 ? "end" : "middle";
      return `<text class="axis-label" x="${x(pointIndex)}" y="${height - 10}" text-anchor="${anchor}">${shortTime(point.time)}</text>`;
    }).join("");
  target.innerHTML = `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="趋势图">
      <line x1="${padding.left}" y1="${height - padding.bottom}" x2="${width - padding.right}" y2="${height - padding.bottom}" stroke="#d9dee7" />
      <line x1="${padding.left}" y1="${padding.top}" x2="${padding.left}" y2="${height - padding.bottom}" stroke="#d9dee7" />
      <text class="axis-label" x="8" y="${y(maxValue) + 4}">${maxValue}</text>
      ${paths}
      ${labels}
    </svg>
    <div class="legend">
      ${series.map((item, index) => `<span><i style="background:${SERIES_COLORS[index % SERIES_COLORS.length]}"></i>${escapeHtml(item.label)}</span>`).join("")}
    </div>
  `;
}

function renderBars(target, items) {
  if (!items.length) {
    target.innerHTML = `<div class="empty-note">暂无分布数据</div>`;
    return;
  }
  const maxValue = Math.max(...items.map((item) => item.value), 1);
  target.innerHTML = items.map((item, index) => {
    const width = Math.max(2, (Number(item.value) || 0) / maxValue * 100);
    return `
      <div class="bar-row">
        <strong title="${escapeHtml(item.label)}">${escapeHtml(item.label)}</strong>
        <div class="bar-track"><div class="bar-fill" style="width:${width}%;background:${PIE_COLORS[index % PIE_COLORS.length]}"></div></div>
        <span>${item.value}</span>
      </div>
    `;
  }).join("");
}

function renderPie(target, items) {
  if (!items.length) {
    target.innerHTML = `<div class="empty-note">暂无分布数据</div>`;
    return;
  }
  const total = items.reduce((sum, item) => sum + (Number(item.value) || 0), 0) || 1;
  let offset = 0;
  const circles = items.map((item, index) => {
    const percent = (Number(item.value) || 0) / total * 100;
    const circle = `<circle class="pie-segment" pathLength="100" r="42" cx="55" cy="55" fill="transparent" stroke="${PIE_COLORS[index % PIE_COLORS.length]}" stroke-width="20" stroke-dasharray="${percent} ${100 - percent}" stroke-dashoffset="${-offset}" />`;
    offset += percent;
    return circle;
  }).join("");
  target.innerHTML = `
    <div class="pie-layout">
      <svg width="120" height="120" viewBox="0 0 110 110" role="img" aria-label="占比图">
        <circle r="42" cx="55" cy="55" fill="transparent" stroke="#eef2f7" stroke-width="20" />
        ${circles}
      </svg>
      <div class="pie-list">
        ${items.map((item, index) => `
          <div>
            <span><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${PIE_COLORS[index % PIE_COLORS.length]};margin-right:6px"></i>${escapeHtml(item.label)}</span>
            <strong>${item.value}</strong>
          </div>
        `).join("")}
      </div>
    </div>
  `;
}

function renderFunnel(stages) {
  if (!stages.length) {
    sopFunnel.innerHTML = `<div class="empty-note">暂无 SOP 阶段数据</div>`;
    return;
  }
  const first = Math.max(Number(stages[0]?.reached) || 0, 1);
  sopFunnel.innerHTML = stages.map((stage, index) => {
    const width = Math.max(8, (Number(stage.reached) || 0) / first * 100);
    const label = `${stage.conversion_from_previous ?? 0}%`;
    return `
      <div class="funnel-row">
        <strong title="${escapeHtml(stage.stage)}">${escapeHtml(stage.stage)}</strong>
        <div class="funnel-track">
          <div class="funnel-fill" style="width:${width}%;background:${SERIES_COLORS[index % SERIES_COLORS.length]}">${label}</div>
        </div>
        <span>${stage.reached}人</span>
      </div>
    `;
  }).join("");
}

function renderAgentTable(agents) {
  if (!agents.length) {
    agentTable.innerHTML = `<div class="empty-note">暂无 Agent 调用数据</div>`;
    return;
  }
  agentTable.innerHTML = `
    <table class="agent-table">
      <thead>
        <tr>
          <th>节点</th>
          <th>调用量</th>
          <th>成功</th>
          <th>失败</th>
          <th>成功率</th>
          <th>平均耗时</th>
        </tr>
      </thead>
      <tbody>
        ${agents.map((agent) => `
          <tr>
            <td>${escapeHtml(agent.label || agent.node)}</td>
            <td>${agent.total}</td>
            <td>${agent.success}</td>
            <td>${agent.failed}</td>
            <td>${agent.success_rate}%</td>
            <td>${agent.avg_elapsed_ms}ms</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function renderRagComparison(groups) {
  if (!groups.length) {
    ragComparison.innerHTML = `<div class="empty-note">暂无 RAG 对比数据</div>`;
    return;
  }
  const rows = [
    ["sessions", "会话数", ""],
    ["avg_message_count", "平均轮次", ""],
    ["high_intent_rate", "高意向率", "%"],
    ["handover_rate", "转人工率", "%"],
    ["continue_reply_rate", "继续回复率", "%"],
  ];
  const maxByKey = Object.fromEntries(
    rows.map(([key]) => [key, Math.max(...groups.map((group) => Number(group[key]) || 0), 1)])
  );
  ragComparison.innerHTML = rows.map(([key, label, suffix], rowIndex) => `
    <div class="rag-compare-row">
      <strong>${label}</strong>
      ${groups.map((group, index) => {
        const value = Number(group[key]) || 0;
        const width = Math.max(2, value / maxByKey[key] * 100);
        return `
          <div class="rag-compare-group">
            <span>${escapeHtml(group.label)}：${formatValue(value)}${suffix}</span>
            <div class="bar-track"><div class="bar-fill" style="width:${width}%;background:${SERIES_COLORS[(rowIndex + index) % SERIES_COLORS.length]}"></div></div>
          </div>
        `;
      }).join("")}
    </div>
  `).join("");
}

function renderRagRecentTable(items) {
  if (!items.length) {
    ragRecentTable.innerHTML = `<div class="empty-note">暂无销售案例命中明细</div>`;
    return;
  }
  ragRecentTable.innerHTML = `
    <table class="agent-table">
      <thead>
        <tr>
          <th>时间</th>
          <th>会话</th>
          <th>命中</th>
          <th>使用</th>
          <th>最高分</th>
          <th>平均分</th>
          <th>案例片段</th>
        </tr>
      </thead>
      <tbody>
        ${items.map((item) => `
          <tr>
            <td>${escapeHtml(formatDateTime(item.created_at))}</td>
            <td>${escapeHtml(shortId(item.session_id))}</td>
            <td>${item.hit_count}</td>
            <td>${item.used ? "是" : "否"}</td>
            <td>${formatValue(item.max_score)}</td>
            <td>${formatValue(item.avg_score)}</td>
            <td>${escapeHtml((item.reference_ids || []).map(shortId).join(", "))}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

function formatDateTime(value) {
  if (!value) return "未知";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function shortTime(value) {
  if (!value) return "";
  if (value.includes(" ")) return value.split(" ")[1] || value;
  return value.slice(5);
}

function shortId(value) {
  const text = String(value || "");
  if (text.length <= 10) return text;
  return `${text.slice(0, 6)}...${text.slice(-4)}`;
}

function formatValue(value) {
  if (typeof value === "number") return Number.isInteger(value) ? value : value.toFixed(1);
  return value ?? "";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

rangeButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    activeRange = button.dataset.range || "7d";
    rangeButtons.forEach((item) => item.classList.toggle("active", item === button));
    await loadDashboard();
  });
});

adminLoginForm.addEventListener("submit", handleAdminLogin);
adminLogoutButton.addEventListener("click", () => logoutAdmin());
saveConfigButton.addEventListener("click", saveAdminConfig);
restartServiceButton.addEventListener("click", restartAdminService);

async function initializeAdmin() {
  await Promise.all([loadDashboard(), loadAdminConfig()]);
}

if (readAdminAuth()) {
  showAdminApp();
  initializeAdmin().catch((error) => {
    console.error("管理员端加载失败", error);
    dashboardUpdatedAt.textContent = error.message || "管理员端加载失败";
  });
} else {
  showAdminLogin();
}
