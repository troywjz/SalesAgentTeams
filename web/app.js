const salesLoginView = document.querySelector("#salesLoginView");
const salesLoginForm = document.querySelector("#salesLoginForm");
const salesLoginEmail = document.querySelector("#salesLoginEmail");
const salesLoginPassword = document.querySelector("#salesLoginPassword");
const salesLoginError = document.querySelector("#salesLoginError");
const salesLoginSubmit = document.querySelector("#salesLoginSubmit");
const brandBar = document.querySelector(".brand-bar");
const salesLoginName = document.querySelector("#salesLoginName");
const salesLogoutButton = document.querySelector("#salesLogoutButton");
const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const messages = document.querySelector("#messages");
const chatTitle = document.querySelector("#chatTitle");
const typingStatus = document.querySelector("#typingStatus");
const newSessionButton = document.querySelector("#newSessionButton");
const toggleContactsButton = document.querySelector("#toggleContactsButton");
const toggleConsoleButton = document.querySelector("#toggleConsoleButton");
const hideContactsButton = document.querySelector("#hideContactsButton");
const hideConsoleButton = document.querySelector("#hideConsoleButton");
const appShell = document.querySelector(".app-shell");
const workspaceTabs = document.querySelectorAll("[data-workspace-tab]");
const workspaceViews = document.querySelectorAll("[data-workspace-view]");
const leftPanelTitle = document.querySelector("#leftPanelTitle");
const contactSearchWrap = document.querySelector("#contactSearchWrap");
const contactSearchInput = document.querySelector("#contactSearchInput");
const contactDetailTitle = document.querySelector("#contactDetailTitle");
const contactDetailView = document.querySelector("#contactDetailView");
const scheduleTaskEditor = document.querySelector("#scheduleTaskEditor");
const scheduleTaskEmpty = document.querySelector("#scheduleTaskEmpty");
const sessionList = document.querySelector("#sessionList");
const scheduleTaskList = document.querySelector("#scheduleTaskList");
const profileView = document.querySelector("#profileView");
const agentRuns = document.querySelector("#agentRuns");
const graphRuntime = document.querySelector("#graphRuntime");
const stageProgress = document.querySelector("#stageProgress");
const autoFollowupStatus = document.querySelector("#autoFollowupStatus");
const intentProgress = document.querySelector("#intentProgress");
const emotionStatus = document.querySelector("#emotionStatus");
const transferStatus = document.querySelector("#transferStatus");
const confirmModal = document.querySelector("#confirmModal");
const confirmModalTitle = document.querySelector("#confirmModalTitle");
const confirmModalMessage = document.querySelector("#confirmModalMessage");
const confirmModalCancel = document.querySelector("#confirmModalCancel");
const confirmModalOk = document.querySelector("#confirmModalOk");

const ACTIVE_SESSION_KEY = "sales-agent-session-id";
const SESSIONS_KEY = "sales-agent-sessions";
const ACTIVE_WORKSPACE_KEY = "sales-agent-workspace";
const SALES_AUTH_KEY = "sales-agent-sales-auth";
const PREVIEW_LIMIT = 34;
const COMPOSER_MAX_ROWS = 3;
const EMPTY_VALUE = "暂未识别";
// 需高于后端 CHAT_REQUEST_TIMEOUT_SECONDS，避免前端先取消导致无回复落库。
const REQUEST_TIMEOUT_MS = 240000;
const GENERIC_SERVICE_ERROR = "服务暂时不可用，已停止等待。请稍后重试，或联系人工跟进。";
const NETWORK_ERROR_MESSAGE = "无法连接后端服务，请确认 Sales Agent 服务正在运行，并打开 8000/sales 或 8000/customer。";
const HIDDEN_OBJECT_KEYS = new Set(["raw_output"]);
let pendingConfirmAction = null;
let isComposing = false;
let realtimeSocket = null;
let realtimeReconnectTimer = null;
let realtimeReconnectAttempts = 0;
let appInitialized = false;
let salesLoggedIn = false;
const realtimeOpenWaiters = [];
const pendingRealtimeOperations = new Map();

const LEGACY_STAGE_LABELS = {
  ice_breaking: "破冰",
  qualification: "确认适配",
  pain_point: "挖掘痛点",
  course_guidance: "方案推荐",
  pricing: "报价优惠",
  objection: "处理顾虑",
  handover: "转人工",
  closed: "已结束",
};
const HIDDEN_STAGE_NAMES = new Set(["handover", "closed", "转人工", "已结束", "结束"]);

const INTENT_LABELS = {
  greeting: "寒暄开场",
  course_inquiry: "咨询课程",
  price_inquiry: "咨询价格",
  objection: "表达顾虑",
  high_intent: "高意向报名",
  off_topic: "无关话题",
};

const PURCHASE_INTENT_ORDER = ["low", "medium", "high"];
const PURCHASE_INTENT_LABELS = {
  low: "低",
  medium: "中",
  high: "高",
};

const EMOTION_LABELS = {
  neutral: "平稳",
  positive: "积极",
  anxious: "焦虑",
  skeptical: "怀疑",
  impatient: "急切",
};

const SOP_FOLLOWUP_STATUS_LABELS = {
  active: "等待客户回复",
  paused: "暂停推进",
  handover: "人工接管中",
  pending: "等待触达",
  running: "正在触达",
  sent: "已触达",
  cancelled: "已取消",
  failed: "触达失败",
  finished: "已结束",
};

const SCHEDULED_TASK_STATUS_LABELS = {
  pending: "待发送",
  running: "发送中",
  sent: "已发送",
  cancelled: "已取消",
  failed: "发送失败",
};

const ACTION_LABELS = {
  pass: "通过",
  revise: "已修改",
  block: "已拦截",
  transfer: "转人工",
  timeout: "请求超时",
  model_provider_error: "模型服务异常",
  graph_error: "图运行异常",
};

const AGENT_LABELS = {
  intent_agent: "意图识别",
  memory_agent: "客户画像更新",
  sop_agent: "SOP 流程决策",
  knowledge_agent: "知识库检索",
  conversation_agent: "回复生成",
  safety_agent: "安全审核",
  sales_graph: "系统转人工",
};

const GRAPH_NODE_LABELS = {
  load_knowledge: "加载知识",
  intent: "意图识别",
  memory: "客户画像",
  sop: "SOP 流程决策",
  knowledge: "知识匹配",
  conversation: "生成回复",
  safety: "风控审核",
  ask_clarification: "补充追问",
  rewrite_reply: "风控改写",
  handover: "转人工",
  final_reply: "最终回复",
  finalize: "整理状态",
  sales_graph: "系统转人工",
};

const FIELD_LABELS = {
  name: "姓名",
  age: "年龄",
  education: "学历",
  work_status: "工作状态",
  learning_goal: "学习目标",
  budget: "预算",
  urgency: "紧急程度",
  concerns: "主要顾虑",
  purchase_intent: "购买意向",
  intent_category: "客户意图",
  emotion: "客户情绪",
  confidence: "判断置信度",
  reason: "判断依据",
  current_stage: "当前阶段",
  next_action: "下一步动作",
  conversation_goal: "会话目标",
  knowledge_query: "知识检索问题",
  should_transfer: "是否转人工",
  profile_updates: "画像更新",
  matched_skus: "匹配 SKU",
  matched_courses: "匹配 SKU",
  facts: "可用信息",
  policy_notes: "合规提醒",
  missing_info: "缺失信息",
  action: "审核结果",
  approved_reply: "通过后的回复",
  revised_reply: "修改后的回复",
  safe_reply: "安全回复",
  customer_reply: "客户可见回复",
  transfer_reason: "转人工原因",
  handover_summary: "交接摘要",
  risks: "风险点",
  node: "图节点",
  node_label: "节点名称",
  status: "运行状态",
  next_status: "下一步状态",
  completed_runs: "已完成 Agent 数",
  _agent_error: "解析状态",
  value: "输出内容",
  thinking: "思考过程",
  final_reply: "最终回复",
  raw_output: "原始输出",
};

let sessionId = window.localStorage.getItem(ACTIVE_SESSION_KEY) || null;
let sessions = [];
let activeWorkspace = window.localStorage.getItem(ACTIVE_WORKSPACE_KEY) || "home";
const narrowLayoutQuery = window.matchMedia("(max-width: 1180px)");
let contactsVisible = !narrowLayoutQuery.matches;
let consoleVisible = !narrowLayoutQuery.matches;
let refreshInFlight = false;
const agentTurnOpenState = new Map();
const agentRunOpenState = new Map();
let markReadInFlight = new Set();
let scheduledTasks = [];
let activeScheduledTaskId = null;
let scheduleTargets = { stages: [], customers: [] };
let scheduleTargetsLoadedKey = "";
let scheduledTasksLoaded = false;
let scheduleDraftTask = null;

function realtimeUrl(viewer) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const params = new URLSearchParams({ viewer });
  if (viewer === "sales") {
    const token = salesAuthToken();
    if (token) params.set("token", token);
  }
  return `${protocol}//${window.location.host}/ws?${params}`;
}

function connectRealtime() {
  if (!salesLoggedIn) return null;
  if (!salesAuthToken()) {
    logoutSales("登录已过期，请重新登录。");
    return null;
  }
  if (
    realtimeSocket
    && [WebSocket.OPEN, WebSocket.CONNECTING].includes(realtimeSocket.readyState)
  ) {
    return realtimeSocket;
  }

  realtimeSocket = new WebSocket(realtimeUrl("sales"));
  realtimeSocket.addEventListener("open", () => {
    realtimeReconnectAttempts = 0;
    const waiters = realtimeOpenWaiters.splice(0);
    for (const waiter of waiters) waiter.resolve();
  });
  realtimeSocket.addEventListener("message", (event) => {
    try {
      handleRealtimeEvent(JSON.parse(event.data));
    } catch {
      // 忽略无法解析的实时事件，等待下一次数据库快照同步。
    }
  });
  realtimeSocket.addEventListener("close", () => {
    const waiters = realtimeOpenWaiters.splice(0);
    for (const waiter of waiters) waiter.reject(new Error("实时连接已断开。"));
    scheduleRealtimeReconnect();
  });
  return realtimeSocket;
}

function scheduleRealtimeReconnect() {
  if (!salesLoggedIn || document.hidden || realtimeReconnectTimer) return;
  if (!salesAuthToken()) {
    logoutSales("登录已过期，请重新登录。");
    return;
  }
  const delay = Math.min(1000 * 2 ** realtimeReconnectAttempts, 15000);
  realtimeReconnectAttempts += 1;
  realtimeReconnectTimer = window.setTimeout(() => {
    realtimeReconnectTimer = null;
    connectRealtime();
  }, delay);
}

function waitForRealtimeOpen(timeoutMs = 5000) {
  connectRealtime();
  if (realtimeSocket?.readyState === WebSocket.OPEN) {
    return Promise.resolve();
  }
  return new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      const index = realtimeOpenWaiters.findIndex((item) => item.resolve === resolve);
      if (index >= 0) realtimeOpenWaiters.splice(index, 1);
      reject(new Error("实时连接未建立，请稍后重试。"));
    }, timeoutMs);
    realtimeOpenWaiters.push({
      resolve: () => {
        window.clearTimeout(timer);
        resolve();
      },
      reject: (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    });
  });
}

async function sendRealtime(payload, { timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
  await waitForRealtimeOpen();
  const operationId = payload.operation_id || createClientMessageId();
  const message = { ...payload, operation_id: operationId };

  const result = new Promise((resolve, reject) => {
    const timer = window.setTimeout(() => {
      pendingRealtimeOperations.delete(operationId);
      reject(new DOMException("请求超时", "AbortError"));
    }, timeoutMs);
    pendingRealtimeOperations.set(operationId, {
      resolve: (value) => {
        window.clearTimeout(timer);
        resolve(value);
      },
      reject: (error) => {
        window.clearTimeout(timer);
        reject(error);
      },
    });
  });

  realtimeSocket.send(JSON.stringify(message));
  return result;
}

function handleRealtimeEvent(event) {
  if (!event || typeof event !== "object") return;

  if (event.type === "operation_result") {
    const pending = pendingRealtimeOperations.get(event.operation_id);
    if (pending) {
      pendingRealtimeOperations.delete(event.operation_id);
      if (event.ok) {
        pending.resolve(event);
      } else {
        pending.reject(new Error(event.error || "实时操作失败。"));
      }
    }
    return;
  }

  if (event.type === "session_updated" && event.session) {
    upsertSessionSnapshot(event.session);
    return;
  }

  if (event.type === "handover_changed" && event.session_id) {
    const session = ensureSession(event.session_id);
    session.state = event.state || session.state;
    session.agent_runs = [
      ...(session.agent_runs || []),
      ...(Array.isArray(event.agent_runs) ? event.agent_runs : []),
    ];
    session.reply_mode = event.state?.transfer_flag ? "human" : "ai";
    session.updated_at = Date.now();
    renderSessionList();
    if (session.session_id === sessionId) renderActiveSession();
    return;
  }

  if (["session", "status", "node_complete", "final"].includes(event.type)) {
    applyRealtimeGraphEvent(event);
  }
}

function upsertSessionSnapshot(rawSession) {
  const detail = sanitizeSession(rawSession || {});
  if (!detail.session_id) return;
  const previous = sessions.find((session) => session.session_id === detail.session_id);
  const merged = {
    ...(previous || {}),
    ...detail,
    isProcessing: Boolean(detail.isProcessing),
    processingStatus: detail.processingStatus || "",
  };
  sessions = [
    merged,
    ...sessions.filter((session) => session.session_id !== detail.session_id),
  ];
  if (!sessionId) {
    sessionId = detail.session_id;
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }
  renderSessionList();
  if (detail.session_id === sessionId) {
    renderActiveSession();
  }
}

function applyRealtimeGraphEvent(event) {
  const id = event.session_id || sessionId;
  if (!id) return;
  const session = ensureSession(id);
  session.persisted = true;
  session.detail_loaded = session.detail_loaded || event.type !== "session";
  session.isProcessing = event.type !== "final";

  if (event.type === "session") {
    session.state = event.state || session.state;
    setSessionProcessingStatus(session, "正在加载商品、FAQ、SOP 与风控规则");
  } else if (event.type === "status") {
    setSessionProcessingStatus(session, event.status || "正在处理客户消息");
    session.graph_status = {
      ...(session.graph_status || {}),
      node: event.node,
      node_label: event.node_label,
      status: event.status,
      updated_at: Date.now(),
    };
  } else if (event.type === "node_complete") {
    session.state = event.state || session.state;
    session.agent_runs = [
      ...(session.agent_runs || []),
      ...(Array.isArray(event.runs) ? event.runs : []),
    ];
    setSessionProcessingStatus(session, event.next_status || event.status || "正在处理客户消息");
    session.graph_status = {
      ...(session.graph_status || {}),
      node: event.node,
      node_label: event.node_label,
      status: event.status,
      next_status: event.next_status,
      completed_runs: event.completed_runs ?? session.agent_runs.length,
      graph: event.graph || {},
      updated_at: Date.now(),
    };
  } else if (event.type === "final") {
    session.state = event.state || session.state;
    session.agent_runs = event.agent_runs || session.agent_runs || [];
    session.isProcessing = false;
    setSessionProcessingStatus(session, "");
    session.graph_status = {
      node: "finalize",
      node_label: GRAPH_NODE_LABELS.finalize,
      status: event.status || "处理完成",
      completed_runs: session.agent_runs.length,
      updated_at: Date.now(),
    };
  }

  session.updated_at = Date.now();
  renderSessionList();
  if (session.session_id === sessionId) {
    updateSessionLabel();
    typingStatus.hidden = !session.isProcessing;
    typingStatus.textContent = session.isProcessing ? session.processingStatus : "";
    updateComposerMode();
    updateDebugFromState(session.state, session.agent_runs, session.graph_status);
  }
}

async function loadSessionsFromDatabase({ loadActiveDetail = true } = {}) {
  const response = await fetchSales("/api/chat/sales/sessions");
  if (!response.ok) {
    throw new Error(`加载数据库会话失败（HTTP ${response.status}）`);
  }
  const payload = await response.json();
  const localActiveSession = sessionId?.startsWith("local-")
    ? sessions.find((session) => session.session_id === sessionId && !session.persisted)
    : null;
  const loadedSessions = Array.isArray(payload.sessions)
    ? payload.sessions.map(sanitizeSession)
    : [];
  sessions = localActiveSession
    ? [localActiveSession, ...loadedSessions]
    : loadedSessions;

  // 旧版曾把完整聊天记录写入 localStorage；现在只保留当前选中的 session id。
  window.localStorage.removeItem(SESSIONS_KEY);
  if (sessionId && !sessions.some((session) => session.session_id === sessionId)) {
    sessionId = null;
    window.localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
  if (!sessionId && sessions.length > 0) {
    sessionId = sessions[0].session_id;
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }
  if (loadActiveDetail && sessionId) {
    await loadSessionDetail(sessionId);
  }
}

async function loadSessionDetail(id) {
  const existing = sessions.find((session) => session.session_id === id);
  if (!id || (!existing?.persisted && id.startsWith("local-"))) return null;
  const response = await fetchSales(`/api/chat/sales/sessions/${encodeURIComponent(id)}`);
  if (!response.ok) {
    throw new Error(`加载会话详情失败（HTTP ${response.status}）`);
  }
  const payload = await response.json();
  const detail = sanitizeSession(payload.session || {});
  const previous = sessions.find((session) => session.session_id === id);
  const merged = {
    ...(previous || {}),
    ...detail,
    isProcessing: Boolean(detail.isProcessing),
    processingStatus: detail.processingStatus || "",
  };
  if (previous) {
    sessions = sessions.map((session) => (
      session.session_id === id ? merged : session
    ));
  } else {
    sessions = [merged, ...sessions.filter((session) => session.session_id !== id)];
  }
  return merged;
}

async function loadScheduledTasks() {
  const response = await fetchSales("/api/chat/sales/scheduled-tasks");
  if (!response.ok) {
    throw new Error(`加载定时任务失败（HTTP ${response.status}）`);
  }
  const payload = await response.json();
  scheduledTasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  scheduledTasksLoaded = true;
  if (activeScheduledTaskId && !scheduledTasks.some((task) => task.task_id === activeScheduledTaskId)) {
    activeScheduledTaskId = null;
  }
  if (!activeScheduledTaskId && scheduledTasks.length > 0) {
    activeScheduledTaskId = scheduledTasks[0].task_id;
  }
}

async function loadScheduleTargets(targetMode = "all", targetStage = "") {
  const key = `${targetMode}:${targetStage || ""}`;
  const params = new URLSearchParams({
    target_mode: targetMode || "all",
    target_stage: targetStage || "",
  });
  const response = await fetchSales(`/api/chat/sales/scheduled-task-targets?${params}`);
  if (!response.ok) {
    throw new Error(`加载发送对象失败（HTTP ${response.status}）`);
  }
  const payload = await response.json();
  scheduleTargets = {
    stages: Array.isArray(payload.stages) ? payload.stages : [],
    customers: Array.isArray(payload.customers) ? payload.customers : [],
  };
  scheduleTargetsLoadedKey = key;
}

async function ensureScheduleWorkspaceData() {
  if (activeWorkspace !== "schedule") return;
  try {
    if (!scheduledTasksLoaded) {
      await loadScheduledTasks();
    }
    const task = getActiveScheduledTask() || createDraftScheduledTask();
    const key = `${task.target_mode}:${task.target_stage || ""}`;
    if (scheduleTargetsLoadedKey !== key) {
      await loadScheduleTargets(task.target_mode, task.target_stage);
    }
    renderScheduleTasks();
    renderScheduleDetail();
  } catch (error) {
    scheduleTaskEditor.innerHTML = "";
    scheduleTaskEditor.appendChild(createEmptyNote(userFacingErrorMessage(error, "定时任务加载失败。")));
  }
}

function saveSessions() {
  if (sessionId) {
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  } else {
    window.localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
}

function sanitizeSession(session) {
  const messages = Array.isArray(session.messages) ? session.messages.map((message) => {
    const normalized = normalizeMessage(message);
    if (message?.role === "error" && isTechnicalProviderError(message.text)) {
      return { ...normalized, text: GENERIC_SERVICE_ERROR };
    }
    return normalized;
  }) : [];
  const preview = isTechnicalProviderError(session.preview)
    ? GENERIC_SERVICE_ERROR
    : session.preview;
  return {
    ...session,
    customer_id: session.customer_id || session.state?.customer_id || "",
    sales_id: session.sales_id || "",
    sales_name: session.sales_name || "",
    messages,
    preview: preview || truncatePreview(messages.at(-1)?.text || ""),
    persisted: Boolean(session.persisted),
    state: session.state || null,
    agent_runs: Array.isArray(session.agent_runs) ? session.agent_runs : [],
    graph_status: session.graph_status || null,
    sop_followup: session.sop_followup || null,
    stage_options: normalizeStageOptions(session.stage_options || [], session.state?.current_stage),
    detail_loaded: Boolean(session.detail_loaded),
    isProcessing: Boolean(session.isProcessing),
    processingStatus: session.processingStatus || "",
    latest_message_id: session.latest_message_id || messages.at(-1)?.id || "",
    latest_sender_type: session.latest_sender_type || messages.at(-1)?.sender_type || "",
    latest_message_at: session.latest_message_at || messages.at(-1)?.created_at || null,
    message_count: Number(session.message_count || messages.length || 0),
    has_unread: Boolean(session.has_unread),
    unread_count: Number(session.unread_count || 0),
    read_cursor_message_id: session.read_cursor_message_id || "",
    read_cursor_at: session.read_cursor_at || null,
    reply_mode: session.reply_mode || (session.state?.transfer_flag ? "human" : "ai"),
    updated_at: session.updated_at || Date.now(),
  };
}

function normalizeMessage(message) {
  const role = message?.role || "user";
  return {
    id: message?.id || message?.message_id || message?.client_message_id || createClientMessageId(),
    role,
    text: message?.text || message?.content || "",
    sender_type: message?.sender_type || defaultSenderType(role),
    customer_id: message?.customer_id || "",
    sales_id: message?.sales_id || "",
    sales_name: message?.sales_name || "",
    synced: message?.synced !== false,
    created_at: message?.created_at || null,
  };
}

function formatBeijingMessageTime(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const parts = new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const getPart = (type) => parts.find((part) => part.type === type)?.value || "";
  return `${getPart("year")}-${getPart("month")}-${getPart("day")} ${getPart("hour")}:${getPart("minute")}`;
}

function isTechnicalProviderError(text) {
  const value = String(text || "");
  return value.includes("All attempted LLM providers failed")
    || value.includes("Provider '")
    || value.includes("fallback configs by limit");
}

function getActiveSession() {
  return sessions.find((session) => session.session_id === sessionId) || null;
}

function ensureActiveSession() {
  if (!sessionId) {
    sessionId = createLocalSession();
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }
  return ensureSession(sessionId);
}

function ensureSession(id) {
  let session = sessions.find((item) => item.session_id === id);
  if (!session) {
    session = {
      session_id: id,
      preview: "",
      persisted: false,
      messages: [],
      state: null,
      agent_runs: [],
      graph_status: null,
      detail_loaded: true,
      isProcessing: false,
      processingStatus: "",
      updated_at: Date.now(),
    };
    sessions.unshift(session);
  }
  // Ensure isProcessing field exists for legacy sessions
  if (session.isProcessing === undefined) {
    session.isProcessing = false;
  }
  if (session.processingStatus === undefined) {
    session.processingStatus = "";
  }
  if (session.graph_status === undefined) {
    session.graph_status = null;
  }
  return session;
}

function createLocalSession() {
  return `local-${crypto.randomUUID()}`;
}

function createClientMessageId() {
  return `msg-${crypto.randomUUID()}`;
}

function defaultSenderType(role) {
  if (role === "user") return "customer";
  if (role === "assistant") return "salesagent";
  return "system";
}

function truncatePreview(text) {
  const normalized = String(text || "").replace(/\s+/g, " ").trim();
  if (normalized.length <= PREVIEW_LIMIT) return normalized;
  return `${normalized.slice(0, PREVIEW_LIMIT)}...`;
}

function latestMessageId(session) {
  return session?.latest_message_id || session?.messages?.at(-1)?.id || "";
}

function markSessionSeen(session) {
  const latestId = latestMessageId(session);
  if (!session?.session_id || session.session_id.startsWith("local-") || !latestId) return;
  if (!session.has_unread && session.read_cursor_message_id === latestId) return;

  session.has_unread = false;
  session.unread_count = 0;
  session.read_cursor_message_id = latestId;
  if (markReadInFlight.has(session.session_id)) return;

  markReadInFlight.add(session.session_id);
  sendRealtime({
    type: "mark_read",
    session_id: session.session_id,
  }, { timeoutMs: 10000 })
    .catch(() => {
      // 已读游标只影响红点提示，失败时等待下一次实时快照或选择会话重试。
    })
    .finally(() => {
      markReadInFlight.delete(session.session_id);
    });
}

function hasUnreadMessage(session) {
  if (!session || session.session_id === sessionId) return false;
  return Boolean(session.has_unread);
}

function applyCustomerAvatar(node) {
  node.textContent = "#";
}

function appendReplyModeBadge(node, session) {
  const badge = document.createElement("span");
  const isHuman = session.reply_mode === "human" || Boolean(session.state?.transfer_flag);
  badge.className = `session-mode-badge ${isHuman ? "human" : "ai"}`;
  badge.textContent = isHuman ? "人工" : "AI";
  node.appendChild(badge);
}

function getComposerMaxHeight() {
  const styles = window.getComputedStyle(input);
  const lineHeight = Number.parseFloat(styles.lineHeight) || 21;
  const paddingTop = Number.parseFloat(styles.paddingTop) || 0;
  const paddingBottom = Number.parseFloat(styles.paddingBottom) || 0;
  return Math.ceil(lineHeight * COMPOSER_MAX_ROWS + paddingTop + paddingBottom + 2);
}

function resizeComposer() {
  input.style.height = "auto";
  const maxHeight = getComposerMaxHeight();
  const nextHeight = Math.min(input.scrollHeight, maxHeight);
  input.style.height = `${nextHeight}px`;
  input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
}

function applyPanelState() {
  const isNarrow = narrowLayoutQuery.matches;
  appShell.classList.toggle("contacts-hidden", !isNarrow && !contactsVisible);
  appShell.classList.toggle("console-hidden", !isNarrow && !consoleVisible);
  appShell.classList.toggle("contacts-open", isNarrow && contactsVisible);
  appShell.classList.toggle("console-open", isNarrow && consoleVisible);

  toggleContactsButton.classList.toggle("active", contactsVisible);
  toggleConsoleButton.classList.toggle("active", consoleVisible);
  toggleContactsButton.setAttribute("aria-pressed", String(contactsVisible));
  toggleConsoleButton.setAttribute("aria-pressed", String(consoleVisible));
}

function setWorkspace(nextWorkspace) {
  activeWorkspace = nextWorkspace || "home";
  window.localStorage.setItem(ACTIVE_WORKSPACE_KEY, activeWorkspace);
  renderWorkspace();
}

function renderWorkspaceTabs() {
  workspaceTabs.forEach((button) => {
    const isActive = button.dataset.workspaceTab === activeWorkspace;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function renderWorkspace() {
  appShell.classList.toggle("schedule-workspace", activeWorkspace === "schedule");
  renderWorkspaceTabs();
  workspaceViews.forEach((view) => {
    view.hidden = view.dataset.workspaceView !== activeWorkspace;
  });
  leftPanelTitle.textContent = activeWorkspace === "schedule" ? "任务列表" : "联系人";
  contactSearchWrap.hidden = activeWorkspace !== "contacts";
  sessionList.hidden = activeWorkspace === "schedule";
  if (scheduleTaskList) {
    scheduleTaskList.hidden = activeWorkspace !== "schedule";
  }
  newSessionButton.title = activeWorkspace === "schedule" ? "新建定时任务" : "新建客户";
  newSessionButton.setAttribute("aria-label", newSessionButton.title);
  renderSessionList();
  renderActiveWorkspaceContent();
  ensureScheduleWorkspaceData();
}

function renderActiveWorkspaceContent() {
  if (activeWorkspace === "contacts") {
    renderContactDetail();
  } else if (activeWorkspace === "schedule") {
    renderScheduleTasks();
    renderScheduleDetail();
  } else {
    renderActiveSession();
  }
}

function setContactsVisible(nextVisible) {
  contactsVisible = nextVisible;
  if (narrowLayoutQuery.matches && nextVisible) {
    consoleVisible = false;
  }
  applyPanelState();
}

function setConsoleVisible(nextVisible) {
  consoleVisible = nextVisible;
  if (narrowLayoutQuery.matches && nextVisible) {
    contactsVisible = false;
  }
  applyPanelState();
}

function setSessionProcessingStatus(session, statusText) {
  if (!session) return;
  session.processingStatus = statusText || "";
  if (statusText) {
    session.graph_status = {
      ...(session.graph_status || {}),
      status: statusText,
      updated_at: Date.now(),
    };
  }
}

function renderSessionList() {
  sessionList.innerHTML = "";
  if (scheduleTaskList) {
    scheduleTaskList.innerHTML = "";
  }
  if (activeWorkspace === "schedule") {
    renderScheduleTasks();
    return;
  }

  const visibleSessions = getVisibleSessionsForWorkspace();
  if (visibleSessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-session-list";
    empty.textContent = activeWorkspace === "contacts"
      ? "没有匹配的联系人。"
      : "暂无聊天记录。发送第一条消息后会自动创建会话。";
    sessionList.appendChild(empty);
    return;
  }

  for (const session of visibleSessions) {
    const item = document.createElement("button");
    item.type = "button";
    const isActive = session.session_id === sessionId;
    const isProcessing = session.isProcessing;
    item.className = `session-item ${isActive ? "active" : ""} ${isProcessing ? "processing" : ""}`;
    item.addEventListener("click", () => selectSession(session.session_id));

    const avatar = document.createElement("div");
    avatar.className = "session-avatar";
    if (hasUnreadMessage(session)) {
      avatar.classList.add("unread");
      item.setAttribute("aria-label", `${formatSessionName(session.session_id)}，有未查看消息`);
    }
    applyCustomerAvatar(avatar);
    appendReplyModeBadge(avatar, session);

    const meta = document.createElement("div");
    meta.className = "session-meta";

    const name = document.createElement("div");
    name.className = "session-name";
    name.textContent = formatSessionName(session.session_id);

    const preview = document.createElement("div");
    preview.className = "session-preview";
    preview.textContent = isProcessing
      ? (session.processingStatus || "正在处理客户消息")
      : (session.preview || "暂无消息");

    meta.append(name, preview);
    item.append(avatar, meta);
    sessionList.appendChild(item);
  }
}

function getVisibleSessionsForWorkspace() {
  if (activeWorkspace !== "contacts") return sessions;
  const query = String(contactSearchInput?.value || "").trim().toLowerCase();
  return [...sessions]
    .filter((session) => {
      if (!query) return true;
      const haystack = [session.session_id, session.customer_id, session.preview, session.sales_name]
        .join(" ")
        .toLowerCase();
      return haystack.includes(query);
    })
    .sort((a, b) => String(a.session_id || "").localeCompare(String(b.session_id || ""), "zh-CN"));
}

function renderScheduleTasks() {
  const targetList = scheduleTaskList || sessionList;
  targetList.innerHTML = "";
  if (!scheduledTasksLoaded) {
    const empty = document.createElement("div");
    empty.className = "empty-session-list";
    empty.textContent = "正在加载定时任务...";
    targetList.appendChild(empty);
    return;
  }

  const tasks = activeScheduledTaskId === "__draft__"
    ? [createDraftScheduledTask(), ...scheduledTasks]
    : scheduledTasks;
  if (tasks.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-session-list";
    empty.textContent = "暂无定时发送任务。";
    targetList.appendChild(empty);
    return;
  }

  for (const task of tasks) {
    const statusLabel = SCHEDULED_TASK_STATUS_LABELS[task.status] || task.status || "待发送";
    const item = document.createElement("button");
    item.type = "button";
    item.className = `session-item ${task.task_id === activeScheduledTaskId ? "active" : ""}`;
    item.addEventListener("click", () => {
      activeScheduledTaskId = task.task_id;
      loadScheduleTargets(task.target_mode, task.target_stage)
        .finally(() => renderWorkspace());
    });

    const avatar = document.createElement("div");
    avatar.className = "session-avatar task-avatar";
    avatar.textContent = statusLabel.slice(0, 1) || "时";

    const meta = document.createElement("div");
    meta.className = "session-meta";
    const name = document.createElement("div");
    name.className = "session-name";
    name.textContent = task.name || "定时发送";
    const preview = document.createElement("div");
    preview.className = "session-preview";
    preview.textContent = `${statusLabel} · ${formatBeijingMessageTime(task.scheduled_at)} · ${formatScheduledTarget(task)}`;
    meta.append(name, preview);
    item.append(avatar, meta);
    targetList.appendChild(item);
  }
}

function formatSessionName(id) {
  if (!id) return "未命名";
  return id;
}

async function selectSession(id) {
  sessionId = id;
  window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  const selectedSession = getActiveSession();
  if (selectedSession) {
    markSessionSeen(selectedSession);
  }
  renderSessionList();
  renderWorkspace();
  const session = getActiveSession();
  if (session && !session.detail_loaded) {
    try {
      await loadSessionDetail(id);
      const loadedSession = getActiveSession();
      if (loadedSession) {
        markSessionSeen(loadedSession);
      }
    } catch (error) {
      appendMessageNode("error", error.message || "会话详情加载失败。", "system");
      return;
    }
    renderSessionList();
    if (activeWorkspace === "contacts") {
      renderContactDetail();
    } else {
      renderActiveSession();
    }
  }
}

function renderEmptyNote() {
  if (messages.children.length > 0) return;
  const note = document.createElement("div");
  note.className = "empty-note";
  note.textContent = "选择联系人查看会话；自动回复开启时销售端只读，转人工后可回复。";
  messages.appendChild(note);
}

function clearEmptyNote() {
  const note = messages.querySelector(".empty-note");
  if (note) note.remove();
}

function appendMessageNode(role, text, senderType = defaultSenderType(role), createdAt = null) {
  clearEmptyNote();
  const row = document.createElement("div");
  row.className = `message-row ${role} ${messageDirectionClass(role, senderType)}`;

  const avatar = document.createElement("div");
  avatar.className = "message-avatar";
  if (role === "assistant") {
    const img = document.createElement("img");
    img.src = "/favicon.ico?v=20260507";
    img.alt = "Sales Agent";
    avatar.appendChild(img);
  } else if (role === "user") {
    applyCustomerAvatar(avatar);
  } else {
    avatar.textContent = "!";
  }

  const content = document.createElement("div");
  content.className = "message-content";

  const time = document.createElement("div");
  time.className = "message-time";
  time.textContent = formatBeijingMessageTime(createdAt);

  const node = document.createElement("div");
  node.className = `message ${role} ${senderType}`;
  node.textContent = text;
  if (time.textContent) {
    content.appendChild(time);
  }
  content.appendChild(node);
  row.append(avatar, content);
  messages.appendChild(row);
  messages.scrollTop = messages.scrollHeight;
}

function messageDirectionClass(role, senderType) {
  if (role === "error") return "inbound";
  return senderType === "human" || senderType === "salesagent"
    ? "outbound"
    : "inbound";
}

function addMessageToActiveSession(role, text, options = {}) {
  const session = ensureActiveSession();
  const senderType = options.sender_type || defaultSenderType(role);
  const message = {
    id: options.id || createClientMessageId(),
    role,
    text,
    sender_type: senderType,
    synced: options.synced !== false,
    created_at: options.created_at || new Date().toISOString(),
  };
  session.messages.push(message);
  session.detail_loaded = true;
  session.preview = truncatePreview(text);
  session.latest_message_id = message.id;
  session.latest_sender_type = senderType;
  session.latest_message_at = new Date().toISOString();
  session.message_count = (session.message_count || 0) + 1;
  session.updated_at = Date.now();
  sessions = [session, ...sessions.filter((item) => item.session_id !== sessionId)];
  saveSessions();
  renderSessionList();
  appendMessageNode(role, text, senderType, message.created_at);
  return message;
}

function userFacingErrorMessage(error, fallback = "操作失败。") {
  if (error?.name === "AbortError") {
    return "请求超过 240 秒仍未完成，请稍后重试。";
  }
  if (error instanceof TypeError || /network/i.test(String(error?.message || ""))) {
    return NETWORK_ERROR_MESSAGE;
  }
  return error?.message || fallback;
}

function setBusy(isBusy) {
  const currentSession = getActiveSession();
  const shouldShowStatus = currentSession ? currentSession.isProcessing : isBusy;
  typingStatus.hidden = !shouldShowStatus;
  typingStatus.textContent = shouldShowStatus
    ? (currentSession?.processingStatus || "正在处理客户消息")
    : "";
  updateComposerMode();
  renderSessionList();
}

function updateSessionLabel() {
  const session = getActiveSession();
  chatTitle.textContent = session ? formatSessionName(session.session_id) : "未开始会话";
}

function updateComposerMode() {
  const session = getActiveSession();
  const manual = Boolean(session?.state?.transfer_flag);
  input.placeholder = manual
    ? "人工接管中，输入人工回复，Enter 发送，Shift+Enter 换行"
    : "自动回复中，转人工后可输入人工回复";
  input.disabled = !manual;
  form.querySelector("button").disabled = !manual;
  form.querySelector("button").textContent = manual ? "人工发送" : "自动中";
}

function translateValue(key, value) {
  if (value === null || value === undefined || value === "") return EMPTY_VALUE;
  if (key === "current_stage") return LEGACY_STAGE_LABELS[value] || value;
  if (key === "intent_category") return INTENT_LABELS[value] || value;
  if (key === "purchase_intent") return PURCHASE_INTENT_LABELS[value] || value;
  if (key === "emotion") return EMOTION_LABELS[value] || value;
  if (key === "action") return ACTION_LABELS[value] || value;
  if (key === "node") return GRAPH_NODE_LABELS[value] || value;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return key === "confidence" ? `${Math.round(value * 100)}%` : String(value);
  return String(value);
}

function translateProviderName(provider) {
  if (provider === "system" || provider === "learning_planner") return "系统转人工";
  return provider || "模型供应商未知";
}

function translateModelName(model) {
  if (model === "langgraph") return "LangGraph";
  return model || "模型未知";
}

function createEmptyNote(text = EMPTY_VALUE) {
  const node = document.createElement("div");
  node.className = "value-empty";
  node.textContent = text;
  return node;
}

function createTagList(values, key) {
  const list = document.createElement("div");
  list.className = "tag-list";
  for (const value of values) {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = translateValue(key, value);
    list.appendChild(tag);
  }
  return list;
}

function createReadableValue(key, value) {
  if (value === null || value === undefined || value === "" || (Array.isArray(value) && value.length === 0)) {
    return createEmptyNote();
  }
  if (Array.isArray(value)) {
    if (value.every((item) => typeof item !== "object" || item === null)) {
      return createTagList(value, key);
    }
    const list = document.createElement("div");
    list.className = "nested-list";
    for (const item of value) {
      list.appendChild(createReadableObject(item, "列表项"));
    }
    return list;
  }
  if (typeof value === "object") {
    return createReadableObject(value, FIELD_LABELS[key] || key);
  }
  const node = document.createElement("span");
  node.textContent = translateValue(key, value);
  return node;
}

function createReadableObject(value, fallbackTitle = "") {
  const card = document.createElement("div");
  card.className = "readable-card";
  if (fallbackTitle && typeof value !== "object") {
    card.textContent = String(value);
    return card;
  }

  const entries = Object.entries(value || {}).filter(([key, item]) => {
    if (HIDDEN_OBJECT_KEYS.has(key)) return false;
    return !(item === null || item === undefined || item === "" || (Array.isArray(item) && item.length === 0));
  });
  if (entries.length === 0) {
    card.appendChild(createEmptyNote());
    return card;
  }

  for (const [key, item] of entries) {
    card.appendChild(createInfoItem(FIELD_LABELS[key] || key, createReadableValue(key, item)));
  }
  return card;
}

function createInfoItem(label, valueNode) {
  const item = document.createElement("div");
  item.className = "profile-item";
  const title = document.createElement("div");
  title.className = "profile-label";
  title.textContent = label;
  const value = document.createElement("div");
  value.className = "profile-value";
  value.appendChild(valueNode);
  item.append(title, value);
  return item;
}

/* ============ Progress Bars ============ */

function normalizeStageOptions(stageOptions = [], currentStage = "") {
  const stages = [];
  const seen = new Set();
  for (const rawStage of stageOptions) {
    const stage = String(rawStage || "").trim();
    if (!stage || seen.has(stage) || HIDDEN_STAGE_NAMES.has(stage)) continue;
    seen.add(stage);
    stages.push(stage);
  }
  const activeStage = String(currentStage || "").trim();
  if (stages.length === 0 && activeStage && !HIDDEN_STAGE_NAMES.has(activeStage)) {
    stages.push(activeStage);
  }
  return stages;
}

function renderStageProgress(currentStage, stageOptions = []) {
  stageProgress.innerHTML = "";
  const stages = normalizeStageOptions(stageOptions, currentStage);
  const currentIndex = stages.indexOf(String(currentStage || "").trim());
  if (stages.length === 0) {
    stageProgress.appendChild(createEmptyNote("暂无阶段配置"));
    return;
  }

  for (let i = 0; i < stages.length; i++) {
    const stage = stages[i];
    const step = document.createElement("div");
    step.className = "progress-step";
    step.dataset.stage = String(i + 1);
    step.textContent = LEGACY_STAGE_LABELS[stage] || stage;
    step.title = LEGACY_STAGE_LABELS[stage] || stage;
    if (currentIndex !== -1 && i < currentIndex) {
      step.classList.add("completed");
    } else if (i === currentIndex) {
      step.classList.add("active");
    }
    stageProgress.appendChild(step);
  }
}

function renderAutoFollowupStatus(sopFollowup = null) {
  if (!autoFollowupStatus) return;
  const status = String(sopFollowup?.status || "").trim();
  const nextFollowupAt = sopFollowup?.next_followup_at || "";
  let label = "未启用";
  if (status === "active" || status === "pending") {
    label = nextFollowupAt
      ? `开启 · ${formatBeijingMessageTime(nextFollowupAt)}`
      : "开启";
  } else if (status === "running") {
    label = "发送中";
  } else if (status === "paused") {
    label = "暂停";
  } else if (status === "handover") {
    label = "转人工";
  } else if (status === "finished") {
    label = "结束";
  } else if (status) {
    label = SOP_FOLLOWUP_STATUS_LABELS[status] || status;
  }
  autoFollowupStatus.textContent = `自动推进：${label}`;
  autoFollowupStatus.dataset.status = status || "disabled";
}

function renderIntentProgress(purchaseIntent) {
  intentProgress.innerHTML = "";
  const currentIndex = PURCHASE_INTENT_ORDER.indexOf(purchaseIntent);

  for (let i = 0; i < PURCHASE_INTENT_ORDER.length; i++) {
    const level = PURCHASE_INTENT_ORDER[i];
    const item = document.createElement("div");
    item.className = "level-item";

    const bar = document.createElement("div");
    bar.className = "level-bar";
    bar.dataset.level = String(i + 1);
    if (i <= currentIndex && currentIndex !== -1) {
      bar.classList.add("filled");
    }

    const label = document.createElement("span");
    label.className = "level-label";
    label.textContent = `${PURCHASE_INTENT_LABELS[level]}意向`;
    label.title = label.textContent;
    item.append(bar, label);
    intentProgress.appendChild(item);
  }
}

function renderEmotionStatus(currentEmotion) {
  emotionStatus.innerHTML = "";
  const selectedEmotion = normalizeEmotion(currentEmotion) || "neutral";
  for (const [key, label] of Object.entries(EMOTION_LABELS)) {
    const chip = document.createElement("span");
    chip.className = "emotion-chip";
    chip.dataset.emotion = key;
    chip.textContent = label;
    chip.title = label;
    if (key === selectedEmotion) {
      chip.classList.add("active");
    }
    emotionStatus.appendChild(chip);
  }
}

function normalizeEmotion(value) {
  const normalized = String(value || "").trim().toLowerCase();
  if (!normalized || normalized === "neutral" || normalized === "平稳" || normalized === "中性") return "neutral";
  if (normalized === "positive" || normalized === "积极") return "positive";
  if (normalized === "anxious" || normalized === "焦虑") return "anxious";
  if (normalized === "skeptical" || normalized === "怀疑") return "skeptical";
  if (normalized === "impatient" || normalized === "急切") return "impatient";
  return normalized;
}

function extractLatestIntent(runs = []) {
  for (let i = runs.length - 1; i >= 0; i -= 1) {
    const run = runs[i];
    if ((run?.agent_name || run?.node_name) === "intent_agent") {
      const output = run?.output || {};
      if (typeof output === "string") {
        try {
          return JSON.parse(output);
        } catch {
          return { raw_output: output };
        }
      }
      return output;
    }
  }
  return null;
}

function renderTransferStatus(transferFlag, transferReason) {
  transferStatus.innerHTML = "";

  const status = document.createElement("div");
  status.className = "handover-status";

  const dot = document.createElement("div");
  dot.className = `transfer-dot ${transferFlag ? "on" : ""}`;

  const text = document.createElement("span");
  text.className = "transfer-text";
  text.textContent = transferFlag ? "人工接管中" : "自动回复中";
  text.style.color = transferFlag ? "var(--danger)" : "var(--muted)";
  status.append(dot, text);

  const button = document.createElement("button");
  button.type = "button";
  button.className = `handover-button ${transferFlag ? "" : "manual"}`;
  button.textContent = transferFlag ? "转自动" : "转人工";
  button.addEventListener("click", () => requestHandoverToggle(!transferFlag));

  const reason = document.createElement("span");
  reason.className = "transfer-reason";
  reason.textContent = transferFlag
    ? (transferReason || "当前由人工接管，系统不自动回复。")
    : "当前由 Sales Agent 自动回复。";
  reason.hidden = !transferFlag;

  transferStatus.append(status, button, reason);
}

function openConfirmModal({ title, message, okText, onConfirm }) {
  confirmModalTitle.textContent = title;
  confirmModalMessage.textContent = message;
  confirmModalOk.textContent = okText || "确认";
  pendingConfirmAction = onConfirm;
  confirmModal.hidden = false;
  confirmModalOk.focus();
}

function closeConfirmModal() {
  confirmModal.hidden = true;
  pendingConfirmAction = null;
}

function requestHandoverToggle(enabled) {
  if (!sessionId) return;
  openConfirmModal({
    title: enabled ? "确认转人工" : "确认转自动",
    message: enabled
      ? "确认后系统会停止自动回复，后续输入会作为人工回复写入聊天记录和数据库。"
      : "确认后系统会重新介入自动回复，并先同步本地尚未入库的聊天记录。",
    okText: enabled ? "转人工" : "转自动",
    onConfirm: () => setHandoverMode(enabled),
  });
}

async function createWelcomeSession() {
  const result = await sendRealtime({
    type: "create_session",
  }, { timeoutMs: 10000 });
  const nextSessionId = result.session_id;
  if (!nextSessionId) throw new Error("新建客户失败：后端未返回 session id。");
  sessionId = nextSessionId;
  window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  await loadSessionDetail(sessionId);
  saveSessions();
  renderWorkspace();
  return getActiveSession();
}

async function setHandoverMode(enabled) {
  const session = getActiveSession() || ensureActiveSession();
  if (!enabled) {
    await syncPendingMessages(session);
  }

  const result = await sendRealtime({
    type: "set_handover",
    session_id: session.session_id,
    enabled,
    reason: enabled ? "人工手动接管" : "",
  });
  sessionId = result.session_id || session.session_id;
  window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  await loadSessionDetail(sessionId);
  saveSessions();
  renderSessionList();
  renderActiveSession();
}

async function persistLocalMessages(messagesToPersist) {
  if (!messagesToPersist.length) return null;
  const active = getActiveSession() || ensureActiveSession();
  let payload = null;
  for (const message of messagesToPersist) {
    payload = await sendRealtime({
      type: "human_message",
      session_id: active.session_id,
      message: message.text,
      client_message_id: message.id,
    });
    sessionId = payload.session_id || active.session_id;
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
    const session = ensureSession(sessionId);
    session.persisted = true;
    session.detail_loaded = true;
    message.synced = true;
    session.updated_at = Date.now();
  }
  saveSessions();
  return payload;
}

async function syncPendingMessages(session) {
  const pending = (session?.messages || []).filter((message) => message.synced === false);
  if (pending.length === 0) return null;
  return persistLocalMessages(pending);
}

function shouldDeferRefreshForComposer() {
  return isComposing || (document.activeElement === input && input.value.length > 0);
}

async function refreshSalesWorkspace() {
  if (refreshInFlight || document.hidden || shouldDeferRefreshForComposer()) return;
  refreshInFlight = true;
  const previousSessionId = sessionId;
  const draft = input.value;
  try {
    await loadSessionsFromDatabase({ loadActiveDetail: false });
    if (previousSessionId && sessions.some((session) => session.session_id === previousSessionId)) {
      sessionId = previousSessionId;
      window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
      await loadSessionDetail(sessionId);
    }
    renderSessionList();
    renderActiveSession();
    input.value = draft;
    resizeComposer();
  } catch {
    // 轮询只用于同步数据库视图，失败时保持当前页面可用。
  } finally {
    refreshInFlight = false;
  }
}

/* ============ Profile & Agent Runs ============ */

function renderProfile(profile = {}) {
  profileView.innerHTML = "";
  const fields = [
    "name",
    "age",
    "education",
    "work_status",
    "learning_goal",
    "budget",
    "urgency",
    "concerns",
  ];
  for (const key of fields) {
    profileView.appendChild(createInfoItem(FIELD_LABELS[key], createReadableValue(key, profile[key])));
  }
}

function renderContactDetail() {
  const session = getActiveSession();
  contactDetailView.innerHTML = "";
  contactDetailTitle.textContent = session ? formatSessionName(session.session_id) : "联系人详情";
  if (!session) {
    contactDetailView.appendChild(createEmptyNote("请选择一个联系人。"));
    return;
  }
  const intent = extractLatestIntent(session.agent_runs || []) || session.state?.intent || {};
  const emotion = intent.emotion || session.state?.customer_profile?.emotion;
  contactDetailView.appendChild(createContactSection("阶段进度", createStageProgressNode(session.state?.current_stage, session.stage_options || [])));
  contactDetailView.appendChild(createContactSection("意向等级", createIntentProgressNode(intent.purchase_intent || session.state?.customer_profile?.purchase_intent)));
  contactDetailView.appendChild(createContactSection("情绪状态", createEmotionStatusNode(emotion)));
  contactDetailView.appendChild(createContactSection("客户画像", createProfileGridNode(session.state?.customer_profile || {})));
}

function createContactSection(title, body) {
  const section = document.createElement("section");
  section.className = "contact-detail-section";
  const heading = document.createElement("h2");
  heading.textContent = title;
  section.append(heading, body);
  return section;
}

function createStageProgressNode(currentStage, stageOptions = []) {
  const node = document.createElement("div");
  node.className = "progress-track";
  const stages = normalizeStageOptions(stageOptions, currentStage);
  const currentIndex = stages.indexOf(String(currentStage || "").trim());
  if (stages.length === 0) return createEmptyNote("暂无阶段配置");
  stages.forEach((stage, index) => {
    const step = document.createElement("div");
    step.className = "progress-step";
    step.dataset.stage = String(index + 1);
    step.textContent = LEGACY_STAGE_LABELS[stage] || stage;
    step.title = step.textContent;
    if (currentIndex !== -1 && index < currentIndex) step.classList.add("completed");
    if (index === currentIndex) step.classList.add("active");
    node.appendChild(step);
  });
  return node;
}

function createIntentProgressNode(purchaseIntent) {
  const node = document.createElement("div");
  node.className = "level-track";
  const currentIndex = PURCHASE_INTENT_ORDER.indexOf(purchaseIntent);
  PURCHASE_INTENT_ORDER.forEach((level, index) => {
    const item = document.createElement("div");
    item.className = "level-item";
    const bar = document.createElement("div");
    bar.className = "level-bar";
    bar.dataset.level = String(index + 1);
    if (index <= currentIndex && currentIndex !== -1) bar.classList.add("filled");
    const label = document.createElement("span");
    label.className = "level-label";
    label.textContent = `${PURCHASE_INTENT_LABELS[level]}意向`;
    item.append(bar, label);
    node.appendChild(item);
  });
  return node;
}

function createEmotionStatusNode(currentEmotion) {
  const node = document.createElement("div");
  node.className = "emotion-track";
  const selectedEmotion = normalizeEmotion(currentEmotion) || "neutral";
  for (const [key, label] of Object.entries(EMOTION_LABELS)) {
    const chip = document.createElement("span");
    chip.className = `emotion-chip ${key === selectedEmotion ? "active" : ""}`;
    chip.dataset.emotion = key;
    chip.textContent = label;
    node.appendChild(chip);
  }
  return node;
}

function createProfileGridNode(profile = {}) {
  const grid = document.createElement("div");
  grid.className = "profile-grid";
  const fields = ["name", "age", "education", "work_status", "learning_goal", "budget", "urgency", "concerns"];
  for (const key of fields) {
    grid.appendChild(createInfoItem(FIELD_LABELS[key], createReadableValue(key, profile[key])));
  }
  return grid;
}

function createDraftScheduledTask() {
  if (scheduleDraftTask) return scheduleDraftTask;
  const now = new Date();
  now.setSeconds(0, 0);
  scheduleDraftTask = {
    task_id: "__draft__",
    name: "定时发送",
    status: "pending",
    enabled: true,
    scheduled_at: now.toISOString(),
    target_mode: "all",
    target_stage: "",
    selected_session_ids: [],
    message_text: "",
  };
  return scheduleDraftTask;
}

function getActiveScheduledTask() {
  if (activeScheduledTaskId === "__draft__") return createDraftScheduledTask();
  return scheduledTasks.find((task) => task.task_id === activeScheduledTaskId) || null;
}

function persistScheduleDraft(task) {
  if (!task) return;
  if (task.task_id === "__draft__") {
    scheduleDraftTask = task;
    return;
  }
  scheduledTasks = scheduledTasks.map((item) => (
    item.task_id === task.task_id ? { ...item, ...task } : item
  ));
}

function formatScheduledTarget(task) {
  if (task.target_mode === "manual") return `手动选择 ${task.selected_session_ids?.length || 0} 人`;
  if (task.target_mode === "stage") return `阶段：${task.target_stage || "未选择"}`;
  return "全部客户";
}

function padTime(value) {
  return String(value).padStart(2, "0");
}

function localDateParts(value) {
  const date = value ? new Date(value) : new Date();
  if (Number.isNaN(date.getTime())) return localDateParts(new Date().toISOString());
  return {
    date: `${date.getFullYear()}-${padTime(date.getMonth() + 1)}-${padTime(date.getDate())}`,
    hour: padTime(date.getHours()),
    minute: padTime(date.getMinutes()),
  };
}

function buildScheduledAt(dateValue, hourValue, minuteValue) {
  const [year, month, day] = String(dateValue || "").split("-").map((item) => Number.parseInt(item, 10));
  const hour = Number.parseInt(hourValue, 10);
  const minute = Number.parseInt(minuteValue, 10);
  return new Date(year, month - 1, day, hour, minute, 0, 0).toISOString();
}

function createTimeSelect(name, selectedValue, maxValue) {
  const select = document.createElement("select");
  select.name = name;
  select.className = "schedule-time-select";
  for (let index = 0; index <= maxValue; index += 1) {
    const value = padTime(index);
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    option.selected = value === selectedValue;
    select.appendChild(option);
  }
  return select;
}

function createScheduleField(labelText, child) {
  const label = document.createElement("div");
  label.className = "schedule-form-field";
  const labelNode = document.createElement("span");
  labelNode.textContent = labelText;
  label.append(labelNode, child);
  return label;
}

function createScheduleTargetSelector(task) {
  const wrap = document.createElement("div");
  wrap.className = "schedule-target-selector";

  const modeList = document.createElement("div");
  modeList.className = "schedule-target-modes";
  const modes = [
    { mode: "all", label: "全部" },
    { mode: "manual", label: "手动选择" },
    ...scheduleTargets.stages.map((stage) => ({ mode: "stage", stage, label: stage })),
  ];
  modes.forEach((item) => {
    const label = document.createElement("label");
    label.className = "schedule-target-mode";
    const inputNode = document.createElement("input");
    inputNode.type = "radio";
    inputNode.name = "scheduleTargetMode";
    inputNode.value = item.mode;
    inputNode.dataset.stage = item.stage || "";
    inputNode.checked = task.target_mode === item.mode && (item.mode !== "stage" || task.target_stage === item.stage);
    inputNode.addEventListener("change", async () => {
      if (!inputNode.checked) return;
      task.target_mode = item.mode;
      task.target_stage = item.stage || "";
      if (item.mode !== "manual") task.selected_session_ids = [];
      persistScheduleDraft(task);
      await loadScheduleTargets(task.target_mode, task.target_stage);
      renderScheduleDetail();
    });
    const text = document.createElement("span");
    text.textContent = item.label;
    label.append(inputNode, text);
    modeList.appendChild(label);
  });

  const userList = document.createElement("div");
  userList.className = "schedule-target-users";
  const allCustomerIds = scheduleTargets.customers.map((item) => item.session_id);
  const selectedIds = task.selected_session_ids || [];
  const selected = new Set(selectedIds.length > 0 ? selectedIds : allCustomerIds);
  if (scheduleTargets.customers.length === 0) {
    userList.appendChild(createEmptyNote("当前条件下没有客户。"));
  }
  scheduleTargets.customers.forEach((customer) => {
    const label = document.createElement("label");
    label.className = "schedule-target-user";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = customer.session_id;
    checkbox.checked = selected.has(customer.session_id);
    checkbox.addEventListener("change", () => {
      const current = new Set((task.selected_session_ids || []).length > 0 ? task.selected_session_ids : allCustomerIds);
      if (checkbox.checked) current.add(customer.session_id);
      else current.delete(customer.session_id);
      task.selected_session_ids = [...current];
      persistScheduleDraft(task);
    });
    const text = document.createElement("span");
    text.textContent = `${customer.display_name || customer.session_id} · ${customer.current_stage || "未分阶段"}`;
    label.append(checkbox, text);
    userList.appendChild(label);
  });

  wrap.append(modeList, userList);
  return wrap;
}

function renderScheduleDetail() {
  scheduleTaskEditor.innerHTML = "";
  scheduleTaskEditor.hidden = false;
  const task = getActiveScheduledTask();
  scheduleTaskEmpty.hidden = Boolean(task);
  if (!task) return;

  const mutableTask = { ...task, selected_session_ids: [...(task.selected_session_ids || [])] };
  const timeParts = localDateParts(mutableTask.scheduled_at);
  const formNode = document.createElement("form");
  formNode.className = "schedule-task-form";

  const nameInput = document.createElement("input");
  nameInput.type = "text";
  nameInput.value = mutableTask.name || "定时发送";
  nameInput.maxLength = 128;

  const dateInput = document.createElement("input");
  dateInput.type = "date";
  dateInput.value = timeParts.date;

  const timeWrap = document.createElement("div");
  timeWrap.className = "schedule-time-row";
  const hourSelect = createTimeSelect("hour", timeParts.hour, 23);
  const minuteSelect = createTimeSelect("minute", timeParts.minute, 59);
  timeWrap.append(dateInput, hourSelect, minuteSelect);

  const enabledLabel = document.createElement("label");
  enabledLabel.className = "schedule-checkbox";
  const enabledInput = document.createElement("input");
  enabledInput.type = "checkbox";
  enabledInput.checked = mutableTask.enabled !== false;
  enabledLabel.append(enabledInput, document.createTextNode("启用任务"));

  const messageInput = document.createElement("textarea");
  messageInput.rows = 8;
  messageInput.value = mutableTask.message_text || "";
  messageInput.placeholder = "输入到时间后要发送给客户的消息";

  const actions = document.createElement("div");
  actions.className = "schedule-form-actions";
  const saveButton = document.createElement("button");
  saveButton.type = "submit";
  saveButton.className = "primary-button";
  saveButton.textContent = "保存";
  const deleteButton = document.createElement("button");
  deleteButton.type = "button";
  deleteButton.className = "secondary-button danger-button";
  deleteButton.textContent = "删除";
  deleteButton.hidden = mutableTask.task_id === "__draft__";
  actions.append(saveButton, deleteButton);

  formNode.append(
    createScheduleField("任务名", nameInput),
    createScheduleField("发送时间", timeWrap),
    createScheduleField("发送对象", createScheduleTargetSelector(mutableTask)),
    enabledLabel,
    createScheduleField("发送内容", messageInput),
    actions,
  );

  formNode.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = {
      name: nameInput.value.trim() || "定时发送",
      scheduled_at: buildScheduledAt(dateInput.value, hourSelect.value, minuteSelect.value),
      target_mode: mutableTask.target_mode || "all",
      target_stage: mutableTask.target_stage || "",
      selected_session_ids: mutableTask.selected_session_ids || [],
      message_text: messageInput.value.trim(),
      enabled: enabledInput.checked,
    };
    if (!payload.message_text) {
      window.alert("请填写发送内容。");
      return;
    }
    if (payload.target_mode === "manual" && payload.selected_session_ids.length === 0) {
      window.alert("请至少选择一个发送对象。");
      return;
    }
    const isDraft = mutableTask.task_id === "__draft__";
    const url = isDraft
      ? "/api/chat/sales/scheduled-tasks"
      : `/api/chat/sales/scheduled-tasks/${encodeURIComponent(mutableTask.task_id)}`;
    const response = await fetchSales(url, {
      method: isDraft ? "POST" : "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      throw new Error(`保存定时任务失败（HTTP ${response.status}）`);
    }
    const result = await response.json();
    activeScheduledTaskId = result.task?.task_id || activeScheduledTaskId;
    if (isDraft) scheduleDraftTask = null;
    await loadScheduledTasks();
    renderWorkspace();
  });

  deleteButton.addEventListener("click", async () => {
    const response = await fetchSales(`/api/chat/sales/scheduled-tasks/${encodeURIComponent(mutableTask.task_id)}`, {
      method: "DELETE",
    });
    if (!response.ok) {
      throw new Error(`删除定时任务失败（HTTP ${response.status}）`);
    }
    activeScheduledTaskId = null;
    await loadScheduledTasks();
    renderWorkspace();
  });

  scheduleTaskEditor.appendChild(formNode);
}

function renderAgentRuns(runs = []) {
  agentRuns.innerHTML = "";
  if (!runs || runs.length === 0) {
    agentRuns.appendChild(createEmptyNote("暂无调用记录"));
    return;
  }

  const groups = groupAgentRunsByTurn(runs);
  groups.forEach((group, index) => {
    const turn = document.createElement("details");
    turn.className = "agent-turn";
    turn.dataset.foldKey = group.key;
    turn.open = getStoredOpenState(agentTurnOpenState, group.key);
    turn.addEventListener("toggle", () => {
      agentTurnOpenState.set(group.key, turn.open);
    });

    const summary = document.createElement("summary");
    summary.className = "agent-turn-summary";
    summary.title = group.preview || "无客户消息";

    const meta = document.createElement("span");
    meta.className = "agent-turn-meta";
    meta.textContent = `第 ${index + 1} 轮 · ${group.runs.length} 个 Agent · `;

    const preview = document.createElement("span");
    preview.className = "agent-turn-preview";
    preview.textContent = group.preview || "无客户消息";

    summary.append(meta, preview);

    const body = document.createElement("div");
    body.className = "agent-turn-body";
    for (const [runIndex, run] of group.runs.entries()) {
      body.appendChild(createAgentRunNode(run, runIndex));
    }

    turn.append(summary, body);
    agentRuns.appendChild(turn);
  });
}

function groupAgentRunsByTurn(runs) {
  const groups = [];
  let currentMessage = "";
  for (const run of runs) {
    const payloadMessage = run?.input_payload?.message || "";
    if (payloadMessage) {
      currentMessage = payloadMessage;
    }
    const message = payloadMessage || currentMessage;
    const last = groups[groups.length - 1];
    if (!last || last.message !== message) {
      groups.push({
        key: createAgentTurnKey(message, run),
        message,
        preview: message ? truncatePreview(message) : "系统处理",
        runs: [run],
      });
    } else {
      last.runs.push(run);
    }
  }
  return groups;
}

function createAgentTurnKey(message, firstRun) {
  return `turn:${message || "system"}:${createAgentRunKey(firstRun, 0)}`;
}

function createAgentRunKey(run, index) {
  return run?.id
    || `${run?.agent_name || "agent"}:${run?.created_at || ""}:${run?.input_payload?.message || ""}:${index}`;
}

function getStoredOpenState(store, key) {
  return store.has(key) ? store.get(key) : false;
}

function createAgentRunNode(run, index = 0) {
  const key = createAgentRunKey(run, index);
  const card = document.createElement("details");
  card.className = "agent-run";
  card.dataset.foldKey = key;
  card.open = getStoredOpenState(agentRunOpenState, key);
  card.addEventListener("toggle", () => {
    agentRunOpenState.set(key, card.open);
  });

  const header = document.createElement("summary");
  header.className = "agent-run-header";
  const title = document.createElement("div");
  title.className = "agent-run-title";
  title.textContent = AGENT_LABELS[run.agent_name] || run.agent_name || "Agent";

  const statusBadge = document.createElement("span");
  if (!run.success) {
    statusBadge.textContent = " 失败";
    statusBadge.style.color = "var(--danger)";
    statusBadge.style.fontSize = "12px";
  }
  title.appendChild(statusBadge);

  const meta = document.createElement("div");
  meta.className = "agent-meta";
  meta.textContent = `${run.elapsed_ms || 0}ms · ${translateProviderName(run.provider)} / ${translateModelName(run.model)}`;
  header.append(title, meta);

  const body = document.createElement("div");
  body.className = "agent-output";

  if (!run.success && run.error_message) {
    const error = document.createElement("div");
    error.className = "agent-error";
    error.textContent = run.error_message;
    body.appendChild(error);
  }

  let displayOutput = run.output;
  if (run.agent_name === "conversation_agent" && typeof run.output === "object" && run.output !== null) {
    displayOutput = run.output.final_reply || run.output.value || run.output;
  }

  body.appendChild(createReadableValue("value", displayOutput));
  card.append(header, body);
  return card;
}

function renderGraphRuntime(status = {}, sopFollowup = null) {
  graphRuntime.innerHTML = "";
  const card = document.createElement("div");
  card.className = "runtime-card";

  const currentNode = status.node_label
    || GRAPH_NODE_LABELS[status.node]
    || status.node
    || "待处理";
  const currentStatus = status.status || "等待客户消息";
  const completedRuns = status.completed_runs ?? (Array.isArray(status.runs) ? status.runs.length : 0);
  const nextStatus = status.next_status || "";

  card.appendChild(createRuntimeLine("当前节点", currentNode));
  card.appendChild(createRuntimeLine("运行状态", currentStatus));
  if (nextStatus) {
    card.appendChild(createRuntimeLine("下一步", nextStatus));
  }
  card.appendChild(createRuntimeLine("已完成", `${completedRuns} 个 Agent`));
  if (sopFollowup) {
    const statusLabel = SOP_FOLLOWUP_STATUS_LABELS[sopFollowup.status] || sopFollowup.status || "未启用";
    card.appendChild(createRuntimeLine("主动推进", statusLabel));
    if (sopFollowup.next_followup_at) {
      card.appendChild(createRuntimeLine("下次触达", formatBeijingMessageTime(sopFollowup.next_followup_at)));
    }
  }
  graphRuntime.appendChild(card);
}

function createRuntimeLine(label, value) {
  const row = document.createElement("div");
  row.className = "runtime-line";
  const name = document.createElement("span");
  name.className = "runtime-label";
  name.textContent = label;
  const text = document.createElement("span");
  text.className = "runtime-value";
  text.textContent = value;
  row.append(name, text);
  return row;
}

function updateDebugFromState(state, runs = [], graphStatus = null) {
  const intent = extractLatestIntent(runs) || graphStatus?.intent || state?.intent || {};
  const activeSession = getActiveSession();
  const stageOptions = activeSession?.stage_options || [];
  renderGraphRuntime(graphStatus || {}, activeSession?.sop_followup || null);
  renderAutoFollowupStatus(activeSession?.sop_followup || null);
  renderStageProgress(state?.current_stage, stageOptions);
  renderIntentProgress(intent.purchase_intent || state?.customer_profile?.purchase_intent);
  renderEmotionStatus(intent.emotion);
  renderTransferStatus(state?.transfer_flag, state?.transfer_reason);
  renderProfile(state?.customer_profile || {});
  renderAgentRuns(runs);
}

function updateFromResponse(response) {
  sessionId = response.session_id;
  window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);

  const session = ensureSession(sessionId);
  session.persisted = true;
  session.state = response.state || null;
  session.agent_runs = response.agent_runs || [];
  session.detail_loaded = true;
  session.isProcessing = false;
  setSessionProcessingStatus(session, "");
  session.graph_status = {
    node: "finalize",
    node_label: GRAPH_NODE_LABELS.finalize,
    status: "处理完成",
    completed_runs: session.agent_runs.length,
    updated_at: Date.now(),
  };
  session.updated_at = Date.now();
  saveSessions();

  updateSessionLabel();
  renderSessionList();
  updateDebugFromState(session.state, session.agent_runs, session.graph_status);
}

function renderActiveSession() {
  updateSessionLabel();
  updateComposerMode();
  messages.innerHTML = "";

  const session = getActiveSession();
  if (session) {
    markSessionSeen(session);
  }
  if (session && !session.detail_loaded) {
    renderEmptyNote();
    const note = messages.querySelector(".empty-note");
    if (note) {
      note.textContent = "正在从数据库加载会话详情...";
    }
    updateDebugFromState(session.state || null, [], null);
    return;
  }
  if (!session || session.messages.length === 0) {
    renderEmptyNote();
    updateDebugFromState(session?.state || null, session?.agent_runs || [], session?.graph_status || null);
    return;
  }

  for (const message of session.messages) {
    appendMessageNode(message.role, message.text, message.sender_type, message.created_at);
  }
  updateDebugFromState(session.state, session.agent_runs, session.graph_status);

  typingStatus.hidden = !session.isProcessing;
  typingStatus.textContent = session.isProcessing
    ? (session.processingStatus || "正在处理客户消息")
    : "";
  updateComposerMode();
}

function renameSession(oldId, newId) {
  if (!oldId || !newId || oldId === newId) return;
  const existing = sessions.find((item) => item.session_id === newId);
  const localSession = sessions.find((item) => item.session_id === oldId);
  if (existing && localSession) {
    existing.messages = localSession.messages;
    existing.preview = localSession.preview;
    sessions = sessions.filter((item) => item.session_id !== oldId);
  } else if (localSession) {
    localSession.session_id = newId;
  }
  if (sessionId === oldId) {
    sessionId = newId;
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }
}

function applyStreamEvent(event, previousLocalId) {
  if (!event || typeof event !== "object") return null;

  if (event.session_id && previousLocalId?.startsWith("local-")) {
    renameSession(previousLocalId, event.session_id);
  }
  if (event.session_id) {
    sessionId = event.session_id;
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }

  const session = ensureSession(sessionId || previousLocalId || createLocalSession());
  if (event.session_id) {
    session.persisted = true;
  }
  session.detail_loaded = true;
  session.isProcessing = event.type !== "final";

  if (event.type === "session") {
    session.state = event.state || session.state;
    setSessionProcessingStatus(session, "正在加载商品、FAQ、SOP 与风控规则");
  } else if (event.type === "status") {
    setSessionProcessingStatus(session, event.status || "正在处理客户消息");
    session.graph_status = {
      ...(session.graph_status || {}),
      node: event.node,
      node_label: event.node_label,
      status: event.status,
      updated_at: Date.now(),
    };
  } else if (event.type === "node_complete") {
    session.state = event.state || session.state;
    session.agent_runs = [
      ...(session.agent_runs || []),
      ...(Array.isArray(event.runs) ? event.runs : []),
    ];
    setSessionProcessingStatus(session, event.next_status || event.status || "正在处理客户消息");
    session.graph_status = {
      ...(session.graph_status || {}),
      node: event.node,
      node_label: event.node_label,
      status: event.status,
      next_status: event.next_status,
      completed_runs: event.completed_runs ?? session.agent_runs.length,
      graph: event.graph || {},
      updated_at: Date.now(),
    };
  } else if (event.type === "final") {
    session.state = event.state || session.state;
    session.agent_runs = event.agent_runs || session.agent_runs || [];
    session.isProcessing = false;
    setSessionProcessingStatus(session, "");
    session.graph_status = {
      node: "finalize",
      node_label: GRAPH_NODE_LABELS.finalize,
      status: event.status || "处理完成",
      completed_runs: session.agent_runs.length,
      updated_at: Date.now(),
    };
  }

  session.updated_at = Date.now();
  saveSessions();
  renderSessionList();
  if (session.session_id === sessionId) {
    updateSessionLabel();
    typingStatus.hidden = !session.isProcessing;
    typingStatus.textContent = session.isProcessing ? session.processingStatus : "";
    updateComposerMode();
    updateDebugFromState(session.state, session.agent_runs, session.graph_status);
  }
  return event.type === "final" ? event : null;
}

async function sendMessageStream(message, previousLocalId, clientMessageId) {
  const controller = new AbortController();
  const timeoutId = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);
  const active = getActiveSession();
  const response = await fetchSales("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    signal: controller.signal,
    body: JSON.stringify({
      message,
      session_id: active?.persisted ? sessionId : null,
      client_message_id: clientMessageId || null,
    }),
  });

  if (!response.ok) {
    window.clearTimeout(timeoutId);
    let payload = {};
    try {
      payload = await response.json();
    } catch {
      payload = {};
    }
    if (response.status >= 500) {
      throw new Error(GENERIC_SERVICE_ERROR);
    }
    throw new Error(payload.detail || `请求失败（HTTP ${response.status}）`);
  }
  if (!response.body) {
    window.clearTimeout(timeoutId);
    throw new Error("浏览器不支持流式读取。");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";
  let finalEvent = null;

  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        if (!line.trim()) continue;
        const event = JSON.parse(line);
        finalEvent = applyStreamEvent(event, previousLocalId) || finalEvent;
      }
    }
    buffer += decoder.decode();
    if (buffer.trim()) {
      const event = JSON.parse(buffer);
      finalEvent = applyStreamEvent(event, previousLocalId) || finalEvent;
    }
  } finally {
    window.clearTimeout(timeoutId);
  }

  if (!finalEvent) {
    throw new Error(GENERIC_SERVICE_ERROR);
  }
  return finalEvent;
}

function readSalesAuth() {
  try {
    const raw = window.localStorage.getItem(SALES_AUTH_KEY);
    const auth = raw ? JSON.parse(raw) : null;
    if (!auth?.access_token || Number(auth.expires_at || 0) * 1000 <= Date.now()) {
      window.localStorage.removeItem(SALES_AUTH_KEY);
      return null;
    }
    return auth;
  } catch {
    window.localStorage.removeItem(SALES_AUTH_KEY);
    return null;
  }
}

function salesAuthToken() {
  return readSalesAuth()?.access_token || "";
}

function salesAuthHeaders(extraHeaders = {}) {
  const token = salesAuthToken();
  return {
    Accept: "application/json",
    ...extraHeaders,
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
  };
}

async function fetchSales(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: salesAuthHeaders(options.headers || {}),
  });
  if (response.status === 401 || response.status === 403) {
    logoutSales("登录已失效，请重新登录。");
  }
  return response;
}

function showSalesLogin(message = "") {
  salesLoggedIn = false;
  salesLoginView.hidden = false;
  brandBar.hidden = true;
  appShell.hidden = true;
  salesLoginError.textContent = message;
  salesLoginError.hidden = !message;
  salesLoginPassword.value = "";
  salesLoginEmail.focus();
}

function showSalesWorkspace(salesUser) {
  salesLoggedIn = true;
  salesLoginView.hidden = true;
  brandBar.hidden = false;
  appShell.hidden = false;
  salesLoginName.textContent = salesUser?.name
    ? `${salesUser.name} · ${salesUser.email || ""}`.trim()
    : salesUser?.email || "";
}

async function handleSalesLogin(event) {
  event.preventDefault();
  const email = salesLoginEmail.value.trim();
  const password = salesLoginPassword.value;
  if (!email || !password) {
    showSalesLogin("请输入销售邮箱和密码。");
    return;
  }

  salesLoginSubmit.disabled = true;
  salesLoginError.hidden = true;
  try {
    const response = await fetch("/api/chat/sales/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!response.ok) {
      let payload = {};
      try {
        payload = await response.json();
      } catch {
        payload = {};
      }
      throw new Error(payload.detail || "邮箱或密码错误。");
    }
    const salesUser = await response.json();
    window.localStorage.setItem(SALES_AUTH_KEY, JSON.stringify(salesUser));
    showSalesWorkspace(salesUser);
    await initializeApp();
  } catch (error) {
    showSalesLogin(userFacingErrorMessage(error, "登录失败，请稍后重试。"));
  } finally {
    salesLoginSubmit.disabled = false;
  }
}

function logoutSales(message = "") {
  window.localStorage.removeItem(SALES_AUTH_KEY);
  if (realtimeSocket) {
    realtimeSocket.close();
    realtimeSocket = null;
  }
  if (realtimeReconnectTimer) {
    window.clearTimeout(realtimeReconnectTimer);
    realtimeReconnectTimer = null;
  }
  appInitialized = false;
  showSalesLogin(message);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  const activeSession = getActiveSession() || ensureActiveSession();
  const manualMode = Boolean(activeSession.state?.transfer_flag);
  if (!manualMode) {
    updateComposerMode();
    return;
  }

  const pendingMessage = addMessageToActiveSession("assistant", text, {
    sender_type: "human",
    synced: false,
  });
  input.value = "";
  resizeComposer();

  try {
    await persistLocalMessages([pendingMessage]);
    renderActiveSession();
  } catch (error) {
    pendingMessage.synced = false;
    addMessageToActiveSession("error", userFacingErrorMessage(error, "人工消息入库失败。"));
  } finally {
    resizeComposer();
    input.focus();
  }
});

input.addEventListener("input", resizeComposer);

input.addEventListener("compositionstart", () => {
  isComposing = true;
});

input.addEventListener("compositionend", () => {
  isComposing = false;
  resizeComposer();
});

input.addEventListener("keydown", (event) => {
  if (event.isComposing || isComposing || event.keyCode === 229) return;
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    form.requestSubmit();
  }
});

newSessionButton.addEventListener("click", async () => {
  if (activeWorkspace === "schedule") {
    scheduleDraftTask = null;
    activeScheduledTaskId = "__draft__";
    scheduledTasksLoaded = true;
    await loadScheduleTargets("all", "");
    renderWorkspace();
    return;
  }
  newSessionButton.disabled = true;
  try {
    await createWelcomeSession();
  } catch (error) {
    if (!getActiveSession()) ensureActiveSession();
    renderActiveWorkspaceContent();
    appendMessageNode("error", userFacingErrorMessage(error, "新建客户失败。"), "system");
  } finally {
    newSessionButton.disabled = false;
    input.focus();
  }
});

toggleContactsButton.addEventListener("click", () => {
  setContactsVisible(!contactsVisible);
});

toggleConsoleButton.addEventListener("click", () => {
  setConsoleVisible(!consoleVisible);
});

hideContactsButton.addEventListener("click", () => {
  setContactsVisible(false);
});

hideConsoleButton.addEventListener("click", () => {
  setConsoleVisible(false);
});

confirmModalCancel.addEventListener("click", closeConfirmModal);

confirmModalOk.addEventListener("click", async () => {
  const action = pendingConfirmAction;
  closeConfirmModal();
  if (!action) return;
  try {
    await action();
  } catch (error) {
    addMessageToActiveSession("error", userFacingErrorMessage(error, "操作失败。"));
  }
});

confirmModal.addEventListener("click", (event) => {
  if (event.target === confirmModal) {
    closeConfirmModal();
  }
});

workspaceTabs.forEach((button) => {
  button.addEventListener("click", () => {
    setWorkspace(button.dataset.workspaceTab || "home");
  });
});

contactSearchInput.addEventListener("input", () => {
  if (activeWorkspace === "contacts") {
    renderSessionList();
    renderContactDetail();
  }
});

salesLoginForm.addEventListener("submit", handleSalesLogin);
salesLogoutButton.addEventListener("click", logoutSales);

narrowLayoutQuery.addEventListener("change", (event) => {
  contactsVisible = !event.matches;
  consoleVisible = !event.matches;
  applyPanelState();
});

async function initializeApp() {
  if (appInitialized) return;
  appInitialized = true;
  applyPanelState();
  resizeComposer();
  connectRealtime();
  renderSessionList();
  renderActiveSession();

  let loadFailed = false;
  try {
    await loadSessionsFromDatabase();
  } catch (error) {
    loadFailed = true;
    sessions = [];
    sessionId = null;
    window.localStorage.removeItem(ACTIVE_SESSION_KEY);
    window.localStorage.removeItem(SESSIONS_KEY);
    messages.innerHTML = "";
    appendMessageNode("error", userFacingErrorMessage(error, "数据库会话加载失败。"), "system");
  }

  renderWorkspace();
  if (loadFailed) {
    renderActiveWorkspaceContent();
  }
}

const storedSalesAuth = readSalesAuth();
if (storedSalesAuth) {
  showSalesWorkspace(storedSalesAuth);
  initializeApp();
} else {
  showSalesLogin();
}
