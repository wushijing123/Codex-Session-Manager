(() => {
  "use strict";
  const themeKey = "codex-session-manager-theme";
  function applyTheme(value) {
    const theme = ["warm", "light", "dark"].includes(value) ? value : "warm";
    document.documentElement.dataset.theme = theme;
    document.querySelectorAll('input[name="theme"]').forEach(input => { input.checked = input.value === theme; });
    return theme;
  }
  let savedTheme;
  try { savedTheme = localStorage.getItem(themeKey); } catch {}
  applyTheme(savedTheme);
  const i18n = window.SessionManagerI18n;
  const t = (source, variables) => i18n.t(source, variables);
  const $ = selector => document.querySelector(selector);
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text != null) element.textContent = text;
    return element;
  };
  if (location.protocol === "file:") {
    document.body.className = "file-open-guide";
    document.body.textContent = t("请通过本地服务打开：python3 scripts/session_manager.py dashboard");
    return;
  }
  const state = {csrf: "", catalog: {sessions: []}, capabilities: {}, filter: "all", query: "", selected: null,
    backups: [], detail: null, page: 1, suggestionState: "all", busy: false, detailRequest: 0, searchRequest: 0, search: null, hits: new Map(),
    checked: new Set(), batch: null, trash: [], trashChecked: new Set(), undoFilename: null, backup_location: null};
  let pendingBackup = null;
  const pageSize = 50;
  const pageRecords = records => records.slice((state.page - 1) * pageSize, state.page * pageSize);
  const escapeHTML = text => String(text).replace(/[&<>"']/g, character => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[character]));
  const markdown = new marked.Marked({gfm: true, breaks: true, renderer: {
    html: ({text}) => escapeHTML(text),
    // Keep image descriptions readable without fetching remote history assets.
    image: ({text}) => escapeHTML(text)
  }});
  const staticText = [...document.querySelectorAll("[data-i18n]")].map(element => ({element, source: element.textContent}));
  const attributes = [...document.querySelectorAll("[placeholder], [aria-label]")].flatMap(element =>
    ["placeholder", "aria-label"].filter(key => element.hasAttribute(key)).map(key => ({element, key, source: element.getAttribute(key)})));
  const labels = {active: "未归档", archived: "已归档", cold: "旧版冷存档", quarantine: "旧版隔离", unindexed: "未索引", missing: "日志缺失"};
  const errors = {
    not_in_trash: "此恢复副本不在回收站中，可能已恢复或清理。",
    invalid_trash_selection: "请选择回收站中的条目。",
    trash_purge_failed: "部分恢复副本无法清除，请检查权限后重试。",
    no_suggestion: "此会话当前没有整理建议，已跳过。",
    suggestion_changed: "整理建议已变化，已跳过；请重新查看后选择。",
    invalid_batch_selection: "请选择要操作的会话。",
    invalid_session_id: "会话 ID 无效，操作未开始。",
    batch_already_running: "已有批量操作正在进行，请等待完成。",
    unknown_session: "会话已不存在，已跳过。",
    unknown_batch: "操作记录已失效，请刷新检查会话状态。",
    already_in_target_state: "已经是目标状态，无需重复操作。",
    invalid_backup: "备份格式无效，无法恢复。",
    invalid_backup_directory: "请选择已存在的文件夹，不能使用 Codex 数据目录或符号链接。",
    backup_directory_unavailable: "备份位置不可用，请连接磁盘或重新选择文件夹。",
    folder_picker_unavailable: "暂时无法打开文件夹选择器，请直接填写完整的文件夹路径。",
    backup_cancelled: "备份已取消，未完成的文件已清理。",
    backup_not_cancellable: "此操作不能通过取消备份停止。",
    backup_hash_mismatch: "备份校验失败，原会话未被覆盖。",
    backup_session_mismatch: "备份的会话 ID 不一致，已停止恢复。",
    restore_session_exists: "会话仍然存在，无需恢复；不会覆盖现有记录。",
    restore_file_saved_index_pending: "聊天文件已取回，但 Codex 尚未完成识别。备份已保留，请刷新后检查。",
    backup_too_large: "备份超过当前恢复大小限制。",

    demo_read_only: "演示模式不执行归档或删除。",
    native_method_unavailable: "当前 Codex CLI 不支持此操作，请更新 CLI 后重启会话库。",
    codex_request_timeout: "Codex 响应超时，请刷新后检查真实状态。",
    codex_connection_closed: "Codex 连接已关闭，请刷新后重试。",
    session_protected_or_linked: "此会话已受保护或含关联任务，请先在 Codex 中处理。",
    session_file_unavailable: "此会话的原始日志不可用。",
    database_selection_required: "未找到唯一的会话数据库，无法生成可靠备份。",
    session_changed_retry: "会话仍在更新，请稍后重新备份。",
    local_operation_failed: "本地操作未完成，请检查目录权限后重试。"
  };
  function errorText(error) { return t(errors[error.message] || error.message); }
  function formatDate(value) {
    if (!value) return "";
    const number = Number(value);
    const date = Number.isFinite(number) ? new Date(number > 1e12 ? number : number * 1000) : new Date(value);
    return Number.isNaN(date.valueOf()) ? "" : date.toLocaleDateString(i18n.locale() === "en" ? "en-US" : "zh-CN", {month: "short", day: "numeric", year: "numeric"});
  }
  function bytes(value) {
    const size = Number(value) || 0;
    if (size < 1024) return `${size} B`;
    if (size < 1024 ** 2) return `${(size / 1024).toFixed(1)} KB`;
    return `${(size / 1024 ** 2).toFixed(1)} MB`;
  }
  async function api(path, payload) {
    const response = await fetch(path, payload === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": state.csrf}, body: JSON.stringify(payload)});
    const result = await response.json();
    if (!response.ok || result.error) throw new Error(result.error || t("请求失败"));
    return result;
  }
  function notice(text, download, error = false, undoFilename = null) {
    $("#noticeText").textContent = text;
    $("#notice").classList.toggle("error", error);
    $("#notice").hidden = false;
    $("#backupDownload").hidden = !download;
    if (download) $("#backupDownload").href = download;
    state.undoFilename = undoFilename;
    $("#undoDelete").hidden = !undoFilename;
  }
  const selectedRecord = () => state.catalog.sessions.find(record => record.id === state.selected);
  function suggestionText(record) {
    const suggestion = record.suggestion || {};
    return suggestion.action === "delete"
      ? t("已闲置 {days} 天，现有记录显示为临时或低复用会话。建议删除前阅读记录；点击删除会自动保留备份。", {days: suggestion.days})
      : t("已闲置 {days} 天。归档后仍可搜索、查看和重新打开。", {days: suggestion.days});
  }
  function translate() {
    document.documentElement.lang = i18n.locale();
    document.title = "Codex-Session-Manager";
    staticText.forEach(({element, source}) => { element.textContent = t(source); });
    attributes.forEach(({element, key, source}) => element.setAttribute(key, t(source)));
    $("#languageBtn").textContent = i18n.locale() === "en" ? "中文" : "EN";
    $("#languageBtn").setAttribute("aria-label", t(i18n.locale() === "en" ? "切换为中文" : "切换为英文"));
    renderProjects();
    renderList();
    renderReader();
    if ($("#backupsDialog").open) renderBackups();
    if ($("#trashDialog").open) renderTrash();
    renderBackupLocation();
    renderBatch();
  }
  function filteredRecords() {
    const query = state.query.toLocaleLowerCase();
    let records = state.catalog.sessions.filter(record => {
      const matchesText = !query || [record.title, record.cwd, record.id, record.first_user_message].some(value => String(value || "").toLocaleLowerCase().includes(query)) || state.hits.has(record.id);
      const matchesFilter = state.filter === "all" || (state.filter === "suggested"
        ? record.suggestion?.action && (state.suggestionState === "all" || record.actual_state === state.suggestionState)
        : record.actual_state === state.filter);
      const matchesProject = !$("#projectSelect").value || (record.cwd || "") === $("#projectSelect").value;
      const days = Number($("#ageSelect").value);
      return matchesText && matchesFilter && matchesProject && (!days || record.age_days >= days);
    });
    const sort = $("#sortSelect").value;
    records.sort((a, b) => sort === "size" ? b.size_bytes - a.size_bytes : sort === "oldest" ? a.updated_at - b.updated_at : b.updated_at - a.updated_at);
    return records;
  }
  function renderList() {
    $("#settingsBtn").disabled = state.busy || !state.backup_location;
    const records = filteredRecords();
    const pages = Math.max(1, Math.ceil(records.length / pageSize));
    state.page = Math.min(state.page, pages);
    const existing = new Set(state.catalog.sessions.map(record => record.id));
    state.checked.forEach(id => {if (!existing.has(id)) state.checked.delete(id);});
    $("#totalCount").textContent = state.catalog.sessions.length;
    $("#resultCount").textContent = t("第 {start}–{end} 条，共 {total} 条", {start: records.length ? (state.page - 1) * pageSize + 1 : 0, end: Math.min(state.page * pageSize, records.length), total: records.length});
    $("#suggestionState").hidden = state.filter !== "suggested";
    $("#dataSource").textContent = t(state.capabilities.demo ? "虚构演示" : "本机会话");
    $("#storageTotal").textContent = bytes(state.catalog.summary?.total_bytes);
    $("#filters").querySelectorAll("button").forEach(button => button.setAttribute("aria-pressed", String(button.dataset.filter === state.filter)));
    const list = $("#sessionList");
    const scrollTop = $("#libraryScroll").scrollTop;
    list.replaceChildren();
    pageRecords(records).forEach(record => {
      const item = node("div", "session-item");
      item.classList.toggle("checked", state.checked.has(record.id));
      const label = node("label", "session-check");
      const checkbox = node("input");
      checkbox.type = "checkbox"; checkbox.checked = state.checked.has(record.id); checkbox.disabled = state.busy;
      checkbox.setAttribute("aria-label", t("选择会话：{title}", {title: record.title || t("无标题会话")}));
      checkbox.addEventListener("change", () => {
        checkbox.checked ? state.checked.add(record.id) : state.checked.delete(record.id);
        item.classList.toggle("checked", checkbox.checked); renderSelection();
      });
      label.append(checkbox);
      const row = node("button", "session-row");
      row.setAttribute("aria-current", String(record.id === state.selected));
      row.dataset.sessionId = record.id;
      const top = node("div", "row-top");
      top.append(node("span", "row-title", record.title || t("无标题会话")), node("time", "row-date", formatDate(record.updated_at)));
      const project = String(record.cwd || "").replace(/\/$/, "").split("/").pop();
      const projectLine = node("div", "row-project");
      projectLine.append(node("span", "project-badge", project || t("无项目")), node("span", "row-size", bytes(record.size_bytes)));
      row.append(top, projectLine);
      const bottom = node("div", "row-bottom");
      const flags = node("span", "row-flags");
      flags.append(node("span", `row-state ${record.actual_state}`, t(labels[record.actual_state] || record.actual_state)));
      if (record.suggestion?.action) flags.append(node("span", `recommendation-tag ${record.suggestion.action}`, t(record.suggestion.action === "archive" ? "建议归档" : "建议删除")));
      bottom.append(flags);
      row.append(bottom);
      const excerpts = state.hits.get(record.id);
      if (excerpts?.length) row.append(node("p", "excerpt", typeof excerpts[0] === "string" ? excerpts[0] : excerpts[0].text || excerpts[0].excerpt || ""));
      row.addEventListener("click", () => selectSession(record.id));
      item.append(label, row); list.append(item);
    });
    if (!records.length) list.append(node("p", "empty-copy", t(state.filter === "suggested" ? "暂时没有需要整理的会话。" : "没有找到会话，试试其他关键词。")));
    $("#libraryScroll").scrollTop = scrollTop;
    $("#pagination").hidden = !records.length;
    $("#prevPage").disabled = state.page <= 1;
    $("#nextPage").disabled = state.page >= pages;
    $("#pageSelect").replaceChildren(...Array.from({length: pages}, (_, index) => {
      const option = node("option", "", t("第 {page} / {pages} 页", {page: index + 1, pages}));
      option.value = index + 1; return option;
    }));
    $("#pageSelect").value = state.page;
    renderSelection();
  }
  function renderSelection() {
    const records = filteredRecords(), visible = pageRecords(records);
    const count = visible.filter(record => state.checked.has(record.id)).length;
    $("#selectVisible").checked = !!visible.length && count === visible.length;
    $("#selectVisible").indeterminate = count > 0 && count < visible.length;
    $("#selectVisible").disabled = state.busy || !visible.length;
    $("#selectFiltered").disabled = state.busy || !records.length;
    $("#clearSelection").disabled = state.busy;
    $("#batchBar").hidden = !state.checked.size;
    const hidden = [...state.checked].filter(id => !records.some(record => record.id === id)).length;
    $("#selectionCount").textContent = t("已选 {count} 条", {count: state.checked.size});
    const other = state.checked.size - count - hidden;
    $("#selectionScope").hidden = !other && !hidden;
    $("#selectionScope").textContent = t("本页 {current} 条 · 其他页 {other} 条 · 筛选外 {hidden} 条", {current: count, other, hidden});
    const recommended = state.catalog.sessions.filter(record => state.checked.has(record.id) && record.suggestion?.action);
    const archives = recommended.filter(record => record.suggestion.action === "archive").length;
    const deletes = recommended.filter(record => record.suggestion.action === "delete").length;
    $("#applySuggestions").hidden = !recommended.length;
    $("#suggestedSummary").hidden = !recommended.length;
    $("#suggestedSummary").textContent = t("按建议归档 {archive} 条、删除 {delete} 条；删除自动备份，无建议的会话跳过。", {archive: archives, delete: deletes});
    $("#selectFiltered").textContent = t("全选筛选结果（{count}）", {count: records.length});
    document.querySelectorAll("[data-batch]").forEach(button => {
      const capability = button.dataset.batch === "unarchive" ? "archive" : button.dataset.batch;
      button.disabled = state.busy || (capability === "suggested"
        ? !(archives && state.capabilities.archive || deletes && state.capabilities.delete) : !state.capabilities[capability]);
    });
  }
  function renderMessages() {
    const container = $("#messages");
    container.replaceChildren();
    for (const message of state.detail?.messages || []) {
      if (!["user", "assistant"].includes(message.role)) continue;
      const article = node("article", `message ${message.role}`);
      const heading = node("div", "message-heading");
      heading.append(node("span", "avatar", message.role === "user" ? "U" : "C"), node("span", "", message.role === "user" ? t("你") : "Codex"));
      if (message.timestamp) heading.append(node("time", "", formatDate(message.timestamp)));
      const body = node("div", "message-body");
      // Only sanitized Markdown enters the document; raw historical HTML stays text.
      const fragment = DOMPurify.sanitize(markdown.parse(message.text || ""), {
        RETURN_DOM_FRAGMENT: true,
        ALLOWED_TAGS: ["p", "br", "strong", "em", "del", "blockquote", "ul", "ol", "li", "h1", "h2", "h3", "h4", "h5", "h6", "pre", "code", "hr", "table", "thead", "tbody", "tr", "th", "td", "a"],
        ALLOWED_ATTR: ["href", "title", "start", "align"]
      });
      body.append(fragment);
      body.querySelectorAll("a").forEach(link => {
        if (!/^https?:\/\/|^mailto:/i.test(link.getAttribute("href") || "")) link.removeAttribute("href");
        else { link.target = "_blank"; link.rel = "noopener noreferrer"; }
      });
      body.querySelectorAll("table").forEach(table => {
        const wrapper = node("div", "table-scroll");
        wrapper.tabIndex = 0; wrapper.setAttribute("role", "region"); wrapper.setAttribute("aria-label", t("表格，可横向滚动"));
        table.replaceWith(wrapper); wrapper.append(table);
      });
      const query = state.query;
      if (query.length >= 2) {
        const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT), texts = [];
        while (walker.nextNode()) texts.push(walker.currentNode);
        for (const textNode of texts) {
          const text = textNode.textContent, lower = text.toLocaleLowerCase(), needle = query.toLocaleLowerCase();
          let start = 0, index; const highlighted = document.createDocumentFragment();
          while ((index = lower.indexOf(needle, start)) !== -1) {
            highlighted.append(document.createTextNode(text.slice(start, index)), node("mark", "", text.slice(index, index + query.length)));
            start = index + query.length;
          }
          if (start) { highlighted.append(document.createTextNode(text.slice(start))); textNode.replaceWith(highlighted); }
        }
      }
      const card = node("div", "message-card");
      card.append(body);
      article.append(heading, card);
      if (message.images?.length) {
        const gallery = node("div", "chat-images");
        for (const attachment of message.images) {
          const figure = node("figure", "chat-image");
          const caption = node("figcaption", "", attachment.name);
          if (attachment.status === "available") {
            const link = node("a"); link.href = attachment.url; link.target = "_blank"; link.rel = "noopener noreferrer";
            const img = node("img"); img.src = attachment.url; img.alt = attachment.name; img.loading = "lazy"; img.decoding = "async";
            img.addEventListener("error", () => {link.hidden = true; caption.textContent = t("图片无法加载：{name}", {name: attachment.name});});
            link.append(img); figure.append(link);
          } else {
            const reasons = {missing: "原图已不在本机，日志也没有可用图片数据。", remote: "远程图片未自动加载。", unsupported: "此图片格式暂不支持预览。", too_large: "图片过大，暂不预览。"};
            figure.append(node("p", "image-unavailable", t(reasons[attachment.status] || reasons.missing)));
          }
          figure.append(caption); gallery.append(figure);
        }
        card.append(gallery);
      }
      container.append(article);
    }
    $("#loadMoreMessages").hidden = state.detail?.next_offset == null;
    $("#loadMoreMessages").disabled = state.busy;
  }
  function renderReader() {
    const record = selectedRecord();
    $("#readerEmpty").hidden = !!record;
    $("#readerContent").hidden = !record;
    if (!record) return;
    $("#sessionTitle").textContent = record.title || t("无标题会话");
    $("#sessionProject").textContent = record.cwd || "";
    $("#sessionDate").textContent = `${formatDate(record.updated_at)} · ${bytes(record.size_bytes)}`;
    $("#sessionState").textContent = t(labels[record.actual_state] || record.actual_state);
    const regular = ["active", "archived"].includes(record.actual_state) && !record.state_conflict;
    $("#openCodex").href = record.codex_url;
    $("#openCodex").hidden = !regular && record.actual_state !== "unindexed";
    $("#archiveBtn").textContent = t(record.actual_state === "archived" ? "取消归档" : "归档");
    $("#archiveBtn").disabled = state.busy || !regular || !state.capabilities.archive || record.pinned || record.permanent_protection || record.relation_count > 0;
    $("#backupBtn").disabled = state.busy || ["cold", "quarantine", "missing"].includes(record.actual_state);
    $("#deleteBtn").disabled = state.busy || !regular || !state.capabilities.delete || record.pinned || record.permanent_protection || record.relation_count > 0;
    $("#capabilityNote").hidden = !!state.capabilities.delete;
    $("#capabilityNote").textContent = t(state.capabilities.demo ? "当前为虚构数据演示，可搜索、阅读和下载备份。归档与删除请在真实会话库使用。" : "当前 Codex CLI 尚不支持官方删除。更新 CLI 后重启会话库即可使用。归档和备份不受影响。");
    const suggestion = $("#suggestion");
    suggestion.replaceChildren();
    suggestion.hidden = !record.suggestion?.action;
    if (!suggestion.hidden) {
      suggestion.className = `suggestion ${record.suggestion.action}`;
      const copy = node("div", "");
      copy.append(node("strong", "", t(record.suggestion.action === "archive" ? "建议归档" : "建议删除")), node("span", "", suggestionText(record)));
      suggestion.append(copy);
    }
    const detail = state.detail;
    $("#chatStatus").textContent = !detail ? t("正在加载聊天记录…") : !detail.available ? t("此会话没有可直接读取的日志；旧版存档需要先用旧工具恢复。")
      : t("已显示 {shown} / {total} 条消息 · 用户消息与 Codex 回复", {shown: detail.messages.length, total: detail.total_messages});
    renderMessages();
  }
  async function selectSession(id, append = false) {
    state.selected = id;
    if (!append) state.detail = null;
    const request = ++state.detailRequest;
    $(".workspace").classList.add("reading");
    if (!append) $("#conversation").scrollTop = 0;
    renderList(); renderReader();
    try {
      const result = await api("/api/session-detail", {session_id: id, max_messages: 20, offset: append ? state.detail.next_offset : 0});
      if (request !== state.detailRequest || id !== state.selected) return;
      state.detail = {...result.detail, messages: [...(append ? state.detail.messages : []), ...result.detail.messages]};
      renderReader();
    } catch (error) {
      if (request === state.detailRequest) $("#chatStatus").textContent = errorText(error);
    }
  }
  async function runAction(action) {
    if (state.busy || !state.selected) return;
    if (action === "backup") return runBatch("backup", [state.selected]);
    const id = state.selected;
    state.busy = true; renderList(); renderReader();
    notice(t(action === "backup" ? "正在生成备份…" : "正在处理…"));
    try {
      const result = await api("/api/session-action", {session_id: id, action});
      state.catalog = result.catalog;
      renderProjects();
      const messages = {archive: "已归档", unarchive: "已取消归档", backup: "备份已保存", delete: "已移入回收站，30 天内可恢复"};
      notice(result.verified === false ? t("Codex 已接收操作，重新扫描尚未确认，请刷新查看。") : t(messages[action]), result.backup?.download_url, false, result.trash?.filename);
      if (!selectedRecord()) { state.selected = null; state.detail = null; $(".workspace").classList.remove("reading"); }
      renderList(); renderReader();
    } catch (error) { notice(errorText(error), null, true); }
    finally { state.busy = false; renderList(); renderReader(); }
  }
  function renderBatch() {
    const batch = state.batch;
    const backingUp = batch?.running && batch.action === "backup";
    $("#backupCancelControls").hidden = !backingUp;
    $("#cancelBackupInline").hidden = !backingUp;
    ["#cancelBackup", "#cancelBackupInline"].forEach(selector => {
      $(selector).disabled = !!batch?.cancel_requested;
      $(selector).textContent = t(batch?.cancel_requested ? "正在取消…" : "取消备份");
    });
    $("#batchBackupDirectory").hidden = batch?.action !== "backup";
    $("#batchBackupDirectory").textContent = batch?.directory ? t("保存位置：{directory}", {directory: batch.directory}) : "";
    $("#closeBatch").setAttribute("aria-label", t(batch?.running ? "关闭进度，任务在后台继续" : "关闭批量操作结果"));
    $("#batchTracker").hidden = !batch?.job;
    $("#batchStatus").hidden = !batch?.job;
    if (!batch?.job) return;
    const results = batch.results || [];
    $("#batchTitle").textContent = t(batch.running ? "正在批量处理" : "批量操作结果");
    const completed = results.filter(row => row.status !== "cancelled").length;
    const summary = batch.running ? t(batch.cancel_requested ? "正在取消备份，请稍候…" : "正在处理 {done} / {total} 条", {done: completed, total: batch.total})
      : t("完成 {success} · 跳过 {skipped} · 失败 {failed} · 待核实 {pending}", {
        success: results.filter(row => row.status === "success").length,
        skipped: results.filter(row => row.status === "skipped").length,
        failed: results.filter(row => row.status === "failed").length,
        pending: results.filter(row => row.status === "pending").length}) +
        (batch.cancelled ? " · " + t("已取消 {count} 条", {count: results.filter(row => row.status === "cancelled").length}) : "");
    const total = Math.max(1, batch.total), done = Math.min(completed, total);
    const fraction = backingUp && batch.current?.bytes_total ? Math.min(.99, batch.current.bytes_done / batch.current.bytes_total) : 0;
    const percent = Math.floor((done + fraction) / total * 100);
    const processed = t("已处理 {done} / {total} 条", {done, total: batch.total});
    $("#batchStatus").textContent = (batch.running ? `${processed} · ${percent}%` : summary + ` · ${percent}%`) + " ↗";
    $("#batchProcessed").textContent = processed;
    $("#batchPercent").textContent = `${percent}%`;
    ["#batchMeter", "#batchInlineMeter"].forEach(selector => {
      $(selector).max = total; $(selector).value = done + fraction;
      $(selector).setAttribute("aria-valuetext", `${processed} · ${percent}%`);
    });
    const actions = {archive: "归档", unarchive: "取消归档", backup: "备份", delete: "删除", suggested: "按建议处理"};
    $("#batchCurrent").textContent = batch.running ? batch.current
      ? t("当前：{action} · {title}", {action: t(actions[batch.current.action] || actions[batch.action]), title: batch.current.title})
      : t("正在准备下一条…") : t("处理已结束，逐条结果如下。");
    if (backingUp && batch.current?.bytes_total) $("#batchCurrent").textContent += " · " +
      t("当前文件：{done} / {total}", {done: bytes(batch.current.bytes_done), total: bytes(batch.current.bytes_total)});
    $("#batchProgress").textContent = `${t(actions[batch.action])} · ${summary}`;
    const list = $("#batchResults"); list.replaceChildren();
    const statuses = {success: "已完成", skipped: "已跳过", failed: "失败", pending: "待核实", cancelled: "已取消"};
    for (const result of results) {
      const row = node("div", "backup-row batch-result");
      const copy = node("div", "backup-copy");
      copy.append(node("strong", "", result.title));
      copy.append(node("p", `batch-result-state ${result.status}`, `${result.action ? t(actions[result.action]) + " · " : ""}${t(statuses[result.status])}`));
      if (result.error) copy.append(node("p", "", errorText(new Error(result.error))));
      if (result.status === "pending") copy.append(node("p", "", t("Codex 已接收操作，重新扫描尚未确认，请刷新查看。")));
      row.append(copy);
      if (result.backup?.download_url) {
        const link = node("a", "button", t("下载备份")); link.href = result.backup.download_url; row.append(link);
      }
      list.append(row);
    }
  }
  async function followBatch() {
    while (state.batch?.running) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      try {
        state.batch = await api(`/api/batch-status?job=${encodeURIComponent(state.batch.job)}`);
        renderBatch();
      } catch (error) {
        if (error.message === "unknown_batch") {
          state.batch.running = false; state.busy = false;
          renderBatch(); renderList(); renderReader(); notice(errorText(error), null, true); return;
        }
        notice(t("暂时无法读取进度，正在重试；操作可能仍在进行。"), null, true);
      }
    }
    try {
      const result = await api("/api/library"); state.catalog = result.catalog;
      for (const row of state.batch.results) if (row.status === "success") state.checked.delete(row.session_id);
      if (!selectedRecord()) { state.selected = null; state.detail = null; $(".workspace").classList.remove("reading"); }
      renderProjects();
      notice(t(state.batch.cancelled ? "备份已取消，已完成的备份保留，未完成的文件已清理。" : "批量操作已结束，点击列表上方的结果查看详情。"));
    } catch (error) { notice(errorText(error), null, true); }
    finally { state.busy = false; renderList(); renderReader(); }
  }
  async function runBatch(action, ids = [...state.checked]) {
    if (state.busy || !ids.length) return;
    if (action === "backup" && !state.backup_location?.configured) return openBackupLocation(ids);
    $("#notice").hidden = true;
    state.busy = true; renderList(); renderReader();
    try {
      state.batch = await api("/api/batch-action", {session_ids: ids, action});
      renderBatch(); $("#batchDialog").showModal();
      await followBatch();
    } catch (error) { state.busy = false; renderList(); renderReader(); notice(errorText(error), null, true); }
  }
  async function cancelBackup() {
    if (!state.batch?.running || state.batch.action !== "backup" || state.batch.cancel_requested) return;
    try {
      state.batch = await api("/api/backup-cancel", {job: state.batch.job});
      renderBatch();
    } catch (error) { notice(errorText(error), null, true); }
  }
  function renderBackupLocation() {
    $("#backupLocationText").textContent = state.backup_location?.directory || "";
    $("#changeBackupLocation").disabled = state.busy;
  }
  function openBackupLocation(ids = null) {
    pendingBackup = ids;
    $("#themeSettings").hidden = !!ids;
    $("#cancelBackupLocation").textContent = t(ids ? "取消" : "关闭");
    $("#backupLocationTitle").textContent = t(ids ? "选择备份保存位置" : "设置");
    $("#backupLocationDescription").textContent = t(ids ? "首次手动备份前，请选择保存文件夹。之后可在首页的“设置”中更改。" : "设置手动备份的保存文件夹。更改后，已有备份仍保留在原处。");
    $("#backupDirectory").value = state.backup_location?.directory || "";
    $("#backupLocationError").textContent = "";
    $("#saveBackupLocation").textContent = t(ids ? "使用此位置并开始备份" : "保存备份位置");
    $("#backupLocationDialog").showModal();
  }
  async function searchContent(event) {
    event.preventDefault();
    const query = $("#searchInput").value.trim();
    if (query.length < 2) { $("#searchStatus").textContent = t("正文搜索至少输入两个字或字符"); return; }
    const request = ++state.searchRequest;
    state.query = query; state.hits.clear(); state.search = "running";
    $("#searchStatus").textContent = t("正在搜索聊天正文…");
    renderList();
    try {
      const {job_id: job} = await api("/api/search", {query});
      while (request === state.searchRequest) {
        const status = await api(`/api/search-archived-content/status?job=${encodeURIComponent(job)}`);
        if (request !== state.searchRequest) return;
        if (status.status === "error") throw new Error(status.error);
        if (status.status === "complete") {
          state.hits = new Map(status.result.matches.map(match => [match.session_id, match.excerpts]));
          state.search = "complete";
          $("#searchStatus").textContent = t(status.result.limited ? "正文匹配至少 {count} 条，请缩小关键词范围" : "正文匹配 {count} 条会话", {count: state.hits.size});
          renderList(); renderMessages(); return;
        }
        $("#searchStatus").textContent = t("已搜索 {scanned} / {total} 条", status);
        await new Promise(resolve => setTimeout(resolve, 350));
      }
    } catch (error) { if (request === state.searchRequest) $("#searchStatus").textContent = errorText(error); }
  }
  function renderProjects() {
    const select = $("#projectSelect"), previous = select.value;
    const projects = [...new Set(state.catalog.sessions.map(record => record.cwd || ""))].filter(Boolean).sort();
    select.replaceChildren(node("option", "", t("全部项目")));
    select.firstElementChild.value = "";
    for (const project of projects) { const option = node("option", "", project); option.value = project; select.append(option); }
    select.value = projects.includes(previous) ? previous : "";
  }
  function renderBackups() {
    const list = $("#backupsList"); list.replaceChildren();
    if (!state.backups.length) list.append(node("p", "empty-copy", t("还没有备份。打开会话后点击“备份”，即可保存在这里。")));
    for (const backup of state.backups) {
      const row = node("article", "backup-row");
      const copy = node("div", "backup-copy");
      copy.append(node("strong", "", backup.title), node("p", "", `${formatDate(backup.created_at)} · ${bytes(backup.size_bytes)}`), node("p", "backup-path", backup.directory || ""));
      const actions = node("div", "backup-actions");
      const download = node("a", "button", t("下载")); download.href = backup.download_url;
      const restore = node("button", "", t(backup.can_restore ? "恢复会话" : "会话仍存在"));
      restore.disabled = state.busy || !backup.can_restore || state.capabilities.demo;
      restore.addEventListener("click", () => restoreBackup(backup.filename));
      actions.append(download, restore); row.append(copy, actions); list.append(row);
    }
  }
  function renderTrashSelection() {
    const total = state.trash.length, count = state.trashChecked.size;
    $("#trashSelectAll").checked = total > 0 && count === total;
    $("#trashSelectAll").indeterminate = count > 0 && count < total;
    $("#trashSelectAll").disabled = state.busy || !total || state.capabilities.demo;
    $("#trashSelectedCount").textContent = t("已选 {count} 条", {count});
    $("#purgeTrashSelected").disabled = state.busy || !count || state.capabilities.demo;
  }
  function renderTrash() {
    const existing = new Set(state.trash.map(row => row.filename));
    state.trashChecked.forEach(name => {if (!existing.has(name)) state.trashChecked.delete(name);});
    const list = $("#trashList"); list.replaceChildren();
    if (!state.trash.length) list.append(node("p", "empty-copy", t("回收站为空。之后删除的会话会在这里保留 30 天，旧副本仍在备份记录中。")));
    for (const item of state.trash) {
      const row = node("article", "backup-row trash-item");
      const checkbox = node("input"); checkbox.type = "checkbox"; checkbox.checked = state.trashChecked.has(item.filename);
      checkbox.disabled = state.busy || state.capabilities.demo;
      checkbox.setAttribute("aria-label", t("选择会话：{title}", {title: item.title}));
      checkbox.addEventListener("change", () => {
        checkbox.checked ? state.trashChecked.add(item.filename) : state.trashChecked.delete(item.filename); renderTrashSelection();
      });
      const copy = node("div", "backup-copy");
      copy.append(node("strong", "", item.title), node("p", "", `${t("删除于 {date}", {date: formatDate(item.deleted_at)})} · ${t("剩余 {days} 天", {days: item.remaining_days})} · ${bytes(item.size_bytes)}`));
      const actions = node("div", "backup-actions");
      const restore = node("button", "", t(item.can_restore ? "恢复会话" : "会话仍存在"));
      restore.disabled = state.busy || !item.can_restore || state.capabilities.demo;
      restore.addEventListener("click", () => restoreTrash(item.filename));
      const purge = node("button", "danger", t("永久删除")); purge.disabled = state.busy || state.capabilities.demo;
      purge.addEventListener("click", () => purgeTrash([item.filename]));
      actions.append(restore, purge); row.append(checkbox, copy, actions); list.append(row);
    }
    renderTrashSelection();
  }
  async function restoreTrash(filename) {
    if (state.busy || !filename) return;
    state.busy = true; renderTrash(); renderList(); renderReader();
    $("#trashStatus").textContent = t("正在恢复会话…");
    $("#trashMeter").hidden = false; $("#trashMeter").max = 1; $("#trashMeter").removeAttribute("value");
    try {
      const result = await api("/api/trash-restore", {filename});
      state.trash = result.trash; state.catalog = result.catalog; renderProjects(); $("#trashMeter").value = 1;
      $("#trashDialog").close();
      notice(t(result.verified ? "会话已恢复" : "聊天文件已取回，但 Codex 尚未完成识别。备份已保留，请刷新后检查。"));
      await selectSession(result.session_id);
    } catch (error) { $("#trashMeter").hidden = true; $("#trashStatus").textContent = errorText(error); notice(errorText(error), null, true); }
    finally { state.busy = false; renderTrash(); renderList(); renderReader(); }
  }
  async function purgeTrash(filenames) {
    if (state.busy || !filenames.length) return;
    state.busy = true; renderTrash(); renderList(); renderReader();
    $("#trashStatus").textContent = t("正在永久删除所选恢复副本…");
    $("#trashMeter").hidden = false; $("#trashMeter").max = filenames.length; $("#trashMeter").removeAttribute("value");
    try {
      const result = await api("/api/trash-purge", {filenames}); state.trash = result.trash;
      $("#trashMeter").value = result.results.length;
      const success = result.results.filter(row => row.status === "success").length;
      if (result.results.some(row => row.filename === state.undoFilename && row.status === "success")) { state.undoFilename = null; $("#notice").hidden = true; }
      $("#trashStatus").textContent = t("永久删除 {success} 条，失败 {failed} 条。", {success, failed: result.results.length - success});
    } catch (error) { $("#trashMeter").hidden = true; $("#trashStatus").textContent = errorText(error); }
    finally { state.busy = false; renderTrash(); renderList(); renderReader(); }
  }
  async function restoreBackup(filename) {
    if (state.busy) return;
    state.busy = true; renderBackups();
    notice(t("正在恢复会话…"));
    try {
      const result = await api("/api/restore-backup", {filename});
      state.catalog = result.catalog; renderProjects(); renderList();
      $("#backupsDialog").close();
      notice(t(result.verified ? "会话已恢复" : "聊天文件已取回，但 Codex 尚未完成识别。备份已保留，请刷新后检查。"));
      await selectSession(result.session_id);
    } catch (error) { notice(errorText(error), null, true); }
    finally { state.busy = false; renderBackups(); renderReader(); }
  }
  $("#searchForm").addEventListener("submit", searchContent);
  $("#selectVisible").addEventListener("change", event => {
    pageRecords(filteredRecords()).forEach(record => event.target.checked ? state.checked.add(record.id) : state.checked.delete(record.id));
    renderList();
  });
  $("#selectFiltered").addEventListener("click", () => {filteredRecords().forEach(record => state.checked.add(record.id)); renderList();});
  $("#clearSelection").addEventListener("click", () => {state.checked.clear(); renderList();});
  $("#batchBar").addEventListener("click", event => {const button = event.target.closest("[data-batch]"); if (button) runBatch(button.dataset.batch);});
  $("#batchStatus").addEventListener("click", () => $("#batchDialog").showModal());
  $("#closeBatch").addEventListener("click", () => $("#batchDialog").close());
  $("#cancelBackup").addEventListener("click", cancelBackup);
  $("#cancelBackupInline").addEventListener("click", cancelBackup);
  $("#batchDialog").addEventListener("cancel", event => {
    if (state.batch?.running && state.batch.action === "backup") { event.preventDefault(); cancelBackup(); }
  });
  $("#changeBackupLocation").addEventListener("click", () => openBackupLocation());
  $("#settingsBtn").addEventListener("click", () => openBackupLocation());
  $("#themeSettings").addEventListener("change", event => {
    if (!event.target.matches('input[name="theme"]')) return;
    const theme = applyTheme(event.target.value);
    try { localStorage.setItem(themeKey, theme); } catch {}
  });
  $("#cancelBackupLocation").addEventListener("click", () => $("#backupLocationDialog").close());
  $("#backupLocationDialog").addEventListener("close", () => { pendingBackup = null; });
  $("#chooseBackupDirectory").addEventListener("click", async () => {
    const button = $("#chooseBackupDirectory"); button.disabled = true;
    try {
      const result = await api("/api/backup-choose-directory", {});
      if (!result.cancelled) $("#backupDirectory").value = result.directory;
    } catch (error) { $("#backupLocationError").textContent = errorText(error); }
    finally { button.disabled = false; }
  });
  $("#backupLocationForm").addEventListener("submit", async event => {
    event.preventDefault();
    const button = $("#saveBackupLocation"); button.disabled = true;
    try {
      const result = await api("/api/backup-location", {directory: $("#backupDirectory").value});
      state.backup_location = result.backup_location;
      renderBackupLocation();
      const ids = pendingBackup;
      pendingBackup = null;
      $("#backupLocationDialog").close();
      if (ids) await runBatch("backup", ids);
    } catch (error) { $("#backupLocationError").textContent = errorText(error); }
    finally { button.disabled = false; }
  });
  $("#searchInput").addEventListener("input", () => {
    state.searchRequest++; state.query = $("#searchInput").value.trim(); state.hits.clear(); state.page = 1; $("#libraryScroll").scrollTop = 0;
    $("#searchStatus").textContent = t("按 Enter 搜索聊天正文"); renderList(); renderMessages();
  });
  $("#filters").addEventListener("click", event => {
    const button = event.target.closest("[data-filter]");
    if (button) { state.filter = button.dataset.filter; state.page = 1; $("#libraryScroll").scrollTop = 0; renderList(); }
  });
  $("#sortSelect").addEventListener("change", () => {state.page = 1; $("#libraryScroll").scrollTop = 0; renderList();});
  $("#suggestionState").addEventListener("change", event => {state.suggestionState = event.target.value; state.page = 1; $("#libraryScroll").scrollTop = 0; renderList();});
  ["#projectSelect", "#ageSelect"].forEach(selector => $(selector).addEventListener("change", () => {state.page = 1; $("#libraryScroll").scrollTop = 0; renderList();}));
  $("#backupsBtn").addEventListener("click", async () => {
    $("#backupsDialog").showModal();
    $("#backupsList").replaceChildren(node("p", "empty-copy", t("正在读取备份…")));
    try {
      const result = await api("/api/backups");
      state.backups = result.backups; state.backup_location = result.backup_location;
      renderBackupLocation(); renderBackups();
    }
    catch (error) { $("#backupsList").replaceChildren(node("p", "empty-copy", errorText(error))); }
  });
  $("#trashBtn").addEventListener("click", async () => {
    state.trash = []; state.trashChecked.clear(); $("#trashMeter").hidden = true; renderTrash(); $("#trashDialog").showModal();
    $("#trashStatus").textContent = t("正在读取回收站…");
    try { state.trash = (await api("/api/trash")).trash; $("#trashStatus").textContent = ""; renderTrash(); }
    catch (error) { $("#trashStatus").textContent = errorText(error); }
  });
  $("#trashSelectAll").addEventListener("change", event => {
    state.trashChecked = new Set(event.target.checked ? state.trash.map(item => item.filename) : []); renderTrash();
  });
  $("#purgeTrashSelected").addEventListener("click", () => purgeTrash([...state.trashChecked]));
  $("#closeTrash").addEventListener("click", () => $("#trashDialog").close());
  $("#undoDelete").addEventListener("click", () => restoreTrash(state.undoFilename));
  $("#closeBackups").addEventListener("click", () => $("#backupsDialog").close());
  function changePage(page) { state.page = page; $("#libraryScroll").scrollTop = 0; renderList(); }
  $("#prevPage").addEventListener("click", () => changePage(state.page - 1));
  $("#nextPage").addEventListener("click", () => changePage(state.page + 1));
  $("#pageSelect").addEventListener("change", event => changePage(Number(event.target.value)));
  $("#loadMoreMessages").addEventListener("click", () => selectSession(state.selected, true));
  $("#archiveBtn").addEventListener("click", () => runAction(selectedRecord()?.actual_state === "archived" ? "unarchive" : "archive"));
  $("#backupBtn").addEventListener("click", () => runAction("backup"));
  $("#deleteBtn").addEventListener("click", () => runAction("delete"));
  $("#dismissNotice").addEventListener("click", () => { $("#notice").hidden = true; });
  $("#backBtn").addEventListener("click", () => { $(".workspace").classList.remove("reading"); $("#searchInput").focus(); });
  $("#languageBtn").addEventListener("click", () => { i18n.setLocale(i18n.locale() === "en" ? "zh-CN" : "en"); translate(); });
  $("#refreshBtn").addEventListener("click", async () => {
    const button = $("#refreshBtn"); button.disabled = true;
    try {
      const result = await api("/api/library-refresh", {}); state.catalog = result.catalog; state.capabilities = result.capabilities; renderProjects();
      state.hits.clear(); state.searchRequest++; $("#searchStatus").textContent = t("按 Enter 搜索聊天正文");
      if (!selectedRecord()) {state.selected = null; state.detail = null; $(".workspace").classList.remove("reading");}
      renderList(); renderReader();
      if (state.selected) await selectSession(state.selected);
    } catch (error) { notice(errorText(error), null, true); }
    finally { button.disabled = false; }
  });
  document.addEventListener("keydown", event => {
    if ((event.metaKey || event.ctrlKey) && event.key === "k") { event.preventDefault(); $("#searchInput").focus(); }
    if (event.key === "Escape" && !$("#backupsDialog").open && !$("#batchDialog").open && !$("#trashDialog").open && !$("#backupLocationDialog").open) $("#backBtn").click();
  });
  translate();
  api("/api/library").then(result => {
    Object.assign(state, result); state.busy = !!state.batch?.running; translate();
    if (state.batch?.running) followBatch();
  })
    .catch(error => { $("#sessionList").replaceChildren(node("p", "empty-copy", errorText(error))); notice(errorText(error), null, true); });
})();
