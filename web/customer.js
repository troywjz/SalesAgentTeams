const form = document.querySelector("#chatForm");
const input = document.querySelector("#messageInput");
const messages = document.querySelector("#messages");
const chatTitle = document.querySelector("#chatTitle");
const typingStatus = document.querySelector("#typingStatus");
const newSessionButton = document.querySelector("#newSessionButton");
const sessionList = document.querySelector("#sessionList");

const ACTIVE_SESSION_KEY = "sales-agent-customer-session-id";
const PREVIEW_LIMIT = 34;
const COMPOSER_MAX_ROWS = 3;
// 需高于后端 CHAT_REQUEST_TIMEOUT_SECONDS，避免前端先取消导致无回复落库。
const REQUEST_TIMEOUT_MS = 240000;
const NETWORK_ERROR_MESSAGE = "无法连接后端服务，请确认 Sales Agent 服务正在运行，并打开 8000/sales 或 8000/customer。";

let sessionId = window.localStorage.getItem(ACTIVE_SESSION_KEY) || null;
let sessions = [];
let refreshInFlight = false;
let markReadInFlight = new Set();
let isComposing = false;
let realtimeSocket = null;
let realtimeReconnectTimer = null;
let realtimeReconnectAttempts = 0;
const realtimeOpenWaiters = [];
const pendingRealtimeOperations = new Map();

function realtimeUrl(viewer) {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws?viewer=${encodeURIComponent(viewer)}`;
}

function connectRealtime() {
  if (
    realtimeSocket
    && [WebSocket.OPEN, WebSocket.CONNECTING].includes(realtimeSocket.readyState)
  ) {
    return realtimeSocket;
  }

  realtimeSocket = new WebSocket(realtimeUrl("customer"));
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
  if (document.hidden || realtimeReconnectTimer) return;
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

  if (["session", "status", "node_complete", "final"].includes(event.type)) {
    applyRealtimeGraphEvent(event);
  }
}

function upsertSessionSnapshot(rawSession) {
  const detail = sanitizeSession(rawSession || {});
  if (!detail.session_id) return;
  const previousLocalId = sessionId?.startsWith("local-") ? sessionId : "";
  if (previousLocalId && !sessions.some((session) => session.session_id === detail.session_id)) {
    renameSession(previousLocalId, detail.session_id);
  }
  const previous = sessions.find((session) => session.session_id === detail.session_id);
  const merged = {
    ...(previous || {}),
    ...detail,
    isProcessing: Boolean(detail.isProcessing),
  };
  sessions = [
    merged,
    ...sessions.filter((session) => session.session_id !== detail.session_id),
  ];
  if (!sessionId || sessionId === previousLocalId) {
    sessionId = detail.session_id;
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }
  renderSessionList();
  if (detail.session_id === sessionId) {
    renderActiveSession();
  }
}

function applyRealtimeGraphEvent(event) {
  if (event.session_id && sessionId?.startsWith("local-")) {
    renameSession(sessionId, event.session_id);
  }
  if (event.session_id && !sessionId) {
    sessionId = event.session_id;
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }
  const session = getActiveSession();
  if (!session) return;
  if (event.type === "final") {
    setProcessing(session, false);
  } else {
    setProcessing(session, true);
  }
}

async function loadSessionsFromDatabase() {
  const response = await fetch("/api/chat/customer/sessions", {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`加载会话失败（HTTP ${response.status}）`);
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
  if (sessionId && !sessions.some((session) => session.session_id === sessionId)) {
    sessionId = null;
    window.localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
  if (!sessionId && sessions.length > 0) {
    sessionId = sessions[0].session_id;
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }
  if (sessionId) {
    await loadSessionDetail(sessionId);
  }
}

async function loadSessionDetail(id) {
  const existing = sessions.find((session) => session.session_id === id);
  if (!id || (!existing?.persisted && id.startsWith("local-"))) return null;
  const response = await fetch(`/api/chat/customer/sessions/${encodeURIComponent(id)}`, {
    headers: { Accept: "application/json" },
  });
  if (!response.ok) {
    throw new Error(`加载会话详情失败（HTTP ${response.status}）`);
  }
  const payload = await response.json();
  const detail = sanitizeSession(payload.session || {});
  const previous = sessions.find((session) => session.session_id === id);
  const merged = { ...(previous || {}), ...detail };
  if (previous) {
    sessions = sessions.map((session) => (
      session.session_id === id ? merged : session
    ));
  } else {
    sessions = [merged, ...sessions.filter((session) => session.session_id !== id)];
  }
  return merged;
}

function sanitizeSession(session) {
  const sessionMessages = Array.isArray(session.messages)
    ? session.messages.map(normalizeMessage)
    : [];
  return {
    ...session,
    customer_id: session.customer_id || session.state?.customer_id || "",
    sales_id: session.sales_id || "",
    sales_name: session.sales_name || "",
    messages: sessionMessages,
    preview: session.preview || truncatePreview(sessionMessages.at(-1)?.text || ""),
    persisted: Boolean(session.persisted),
    state: session.state || null,
    detail_loaded: Boolean(session.detail_loaded),
    isProcessing: Boolean(session.isProcessing),
    latest_message_id: session.latest_message_id || sessionMessages.at(-1)?.id || "",
    latest_sender_type: session.latest_sender_type || sessionMessages.at(-1)?.sender_type || "",
    latest_message_at: session.latest_message_at || sessionMessages.at(-1)?.created_at || null,
    message_count: Number(session.message_count || sessionMessages.length || 0),
    has_unread: Boolean(session.has_unread),
    unread_count: Number(session.unread_count || 0),
    read_cursor_message_id: session.read_cursor_message_id || "",
    read_cursor_at: session.read_cursor_at || null,
    reply_mode: session.reply_mode || "ai",
    updated_at: session.updated_at || Date.now(),
  };
}

function normalizeMessage(message) {
  const role = message?.role || "user";
  return {
    id: message?.id || message?.client_message_id || createClientMessageId(),
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

function defaultSenderType(role) {
  if (role === "user") return "customer";
  if (role === "assistant") return "salesagent";
  return "system";
}

function createLocalSession() {
  return `local-${crypto.randomUUID()}`;
}

function createClientMessageId() {
  return `msg-${crypto.randomUUID()}`;
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

function getActiveSession() {
  return sessions.find((session) => session.session_id === sessionId) || null;
}

function ensureActiveSession() {
  if (!sessionId) {
    sessionId = createLocalSession();
    window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  }
  let session = getActiveSession();
  if (!session) {
    session = {
      session_id: sessionId,
      preview: "",
      persisted: false,
      messages: [],
      state: null,
      detail_loaded: true,
      isProcessing: false,
      updated_at: Date.now(),
    };
    sessions.unshift(session);
  }
  return session;
}

function resizeComposer() {
  input.style.height = "auto";
  const styles = window.getComputedStyle(input);
  const lineHeight = Number.parseFloat(styles.lineHeight) || 21;
  const paddingTop = Number.parseFloat(styles.paddingTop) || 0;
  const paddingBottom = Number.parseFloat(styles.paddingBottom) || 0;
  const maxHeight = Math.ceil(lineHeight * COMPOSER_MAX_ROWS + paddingTop + paddingBottom + 2);
  const nextHeight = Math.min(input.scrollHeight, maxHeight);
  input.style.height = `${nextHeight}px`;
  input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
}

function applyCustomerAvatar(node) {
  node.textContent = "#";
}

function renderSessionList() {
  sessionList.innerHTML = "";
  if (sessions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-session-list";
    empty.textContent = "暂无聊天记录。发送第一条消息后会自动创建会话。";
    sessionList.appendChild(empty);
    return;
  }

  for (const session of sessions) {
    const item = document.createElement("button");
    item.type = "button";
    item.className = `session-item ${session.session_id === sessionId ? "active" : ""}`;
    item.addEventListener("click", () => selectSession(session.session_id));

    const avatar = document.createElement("div");
    avatar.className = "session-avatar";
    if (hasUnreadMessage(session)) {
      avatar.classList.add("unread");
      item.setAttribute("aria-label", `${session.session_id || "未命名"}，有未查看消息`);
    }
    applyCustomerAvatar(avatar);

    const meta = document.createElement("div");
    meta.className = "session-meta";

    const name = document.createElement("div");
    name.className = "session-name";
    name.textContent = session.session_id || "未命名";

    const preview = document.createElement("div");
    preview.className = "session-preview";
    preview.textContent = session.isProcessing ? "对方输入中..." : (session.preview || "暂无消息");

    meta.append(name, preview);
    item.append(avatar, meta);
    sessionList.appendChild(item);
  }
}

async function selectSession(id) {
  sessionId = id;
  window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  const selectedSession = getActiveSession();
  if (selectedSession) {
    markSessionSeen(selectedSession);
  }
  renderSessionList();
  renderActiveSession();
  const session = getActiveSession();
  if (session && !session.detail_loaded) {
    await loadSessionDetail(id);
    const loadedSession = getActiveSession();
    if (loadedSession) {
      markSessionSeen(loadedSession);
    }
    renderSessionList();
    renderActiveSession();
  }
}

function renderActiveSession() {
  const session = getActiveSession();
  if (session) {
    markSessionSeen(session);
  }
  chatTitle.textContent = session?.session_id || "未开始会话";
  typingStatus.hidden = !session?.isProcessing;
  typingStatus.textContent = session?.isProcessing ? "对方输入中..." : "";
  messages.innerHTML = "";

  if (!session || session.messages.length === 0) {
    const note = document.createElement("div");
    note.className = "empty-note";
    note.textContent = "发送第一条消息开始对话。";
    messages.appendChild(note);
    return;
  }

  for (const message of session.messages) {
    appendMessageNode(message.role, message.text, message.sender_type, message.created_at);
  }
}

function appendMessageNode(role, text, senderType = defaultSenderType(role), createdAt = null) {
  const note = messages.querySelector(".empty-note");
  if (note) note.remove();

  const row = document.createElement("div");
  row.className = `message-row ${role}`;

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

function addMessageToActiveSession(role, text, options = {}) {
  const session = ensureActiveSession();
  const message = {
    id: options.id || createClientMessageId(),
    role,
    text,
    sender_type: options.sender_type || defaultSenderType(role),
    synced: options.synced !== false,
    created_at: options.created_at || new Date().toISOString(),
  };
  session.messages.push(message);
  session.preview = truncatePreview(text);
  session.detail_loaded = true;
  session.latest_message_id = message.id;
  session.latest_sender_type = message.sender_type;
  session.latest_message_at = new Date().toISOString();
  session.message_count = (session.message_count || 0) + 1;
  session.updated_at = Date.now();
  sessions = [session, ...sessions.filter((item) => item.session_id !== session.session_id)];
  renderSessionList();
  appendMessageNode(role, text, message.sender_type, message.created_at);
  return message;
}

function userFacingErrorMessage(error) {
  if (error?.name === "AbortError") {
    return "请求超过 240 秒仍未完成，请稍后重试。";
  }
  if (error instanceof TypeError || /network/i.test(String(error?.message || ""))) {
    return NETWORK_ERROR_MESSAGE;
  }
  return error?.message || "发送失败。";
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
  renderSessionList();
  renderActiveSession();
  return getActiveSession();
}

function renameSession(oldId, newId) {
  if (!oldId || !newId || oldId === newId) return;
  const localSession = sessions.find((item) => item.session_id === oldId);
  const existing = sessions.find((item) => item.session_id === newId);
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

function setProcessing(session, isProcessing) {
  session.isProcessing = isProcessing;
  input.disabled = false;
  form.querySelector("button").disabled = false;
  typingStatus.hidden = !isProcessing;
  typingStatus.textContent = isProcessing ? "对方输入中..." : "";
  renderSessionList();
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
  const session = ensureActiveSession();
  session.persisted = Boolean(event.session_id || session.persisted);
  if (event.state) {
    session.state = event.state;
  }
  if (event.type === "final") {
    setProcessing(session, false);
    return event;
  }
  setProcessing(session, true);
  return null;
}

async function sendMessageStream(message, previousLocalId, clientMessageId) {
  const active = getActiveSession();
  const result = await sendRealtime({
    type: "customer_message",
    message,
    session_id: active?.persisted ? active.session_id : null,
    client_message_id: clientMessageId || null,
  });
  if (result.session_id && previousLocalId?.startsWith("local-")) {
    renameSession(previousLocalId, result.session_id);
  }
  return result;
}

async function refreshCustomerWorkspace() {
  if (
    refreshInFlight
    || document.hidden
    || getActiveSession()?.isProcessing
    || shouldDeferRefreshForComposer()
  ) return;
  refreshInFlight = true;
  const previousSessionId = sessionId;
  const draft = input.value;
  try {
    await loadSessionsFromDatabase();
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
    // 轮询失败时保持当前页面，不打断客户输入。
  } finally {
    refreshInFlight = false;
  }
}

function shouldDeferRefreshForComposer() {
  return isComposing || (document.activeElement === input && input.value.length > 0);
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;

  const session = ensureActiveSession();
  const previousLocalId = session.session_id;
  const pendingMessage = addMessageToActiveSession("user", text, {
    sender_type: "customer",
    synced: false,
  });
  input.value = "";
  resizeComposer();
  setProcessing(session, true);

  try {
    const result = await sendMessageStream(text, previousLocalId, pendingMessage.id);
    pendingMessage.synced = true;
    if (result.session_id) {
      sessionId = result.session_id;
      window.localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
    }
    await loadSessionDetail(sessionId);
    renderSessionList();
    renderActiveSession();
  } catch (error) {
    setProcessing(getActiveSession() || session, false);
    appendMessageNode("error", userFacingErrorMessage(error), "system");
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
  newSessionButton.disabled = true;
  try {
    await createWelcomeSession();
  } catch (error) {
    if (!getActiveSession()) ensureActiveSession();
    renderActiveSession();
    appendMessageNode("error", userFacingErrorMessage(error), "system");
  } finally {
    newSessionButton.disabled = false;
    input.focus();
  }
});

async function initializeApp() {
  resizeComposer();
  connectRealtime();
  try {
    await loadSessionsFromDatabase();
  } catch {
    sessions = [];
    sessionId = null;
    window.localStorage.removeItem(ACTIVE_SESSION_KEY);
  }
  renderSessionList();
  renderActiveSession();
}

initializeApp();
