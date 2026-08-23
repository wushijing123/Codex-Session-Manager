(() => {
  "use strict";

  const i18n = window.SessionManagerI18n;
  const t = (source, variables) => i18n.t(source, variables);

  if (window.location.protocol === "file:") {
    window.addEventListener("DOMContentLoaded", () => {
      document.documentElement.lang = i18n.locale();
      document.title = t("请从本地服务打开看板");
      document.body.className = "file-open-guide";
      document.body.textContent = "";
      const main = document.createElement("main");
      const card = document.createElement("article");
      card.className = "file-open-card";
      const title = document.createElement("h1");
      title.textContent = t("请从本地服务打开看板");
      const copy = document.createElement("p");
      copy.textContent = t("这个文件只是界面源码。回到 Codex，输入“打开会话生命周期看板”。");
      card.append(title, copy);
      main.append(card);
      document.body.append(main);
    }, {once: true});
    return;
  }

  const state = {
    csrf: "",
    catalog: null,
    settings: {},
    capabilities: {},
    selected: null,
    lastFocused: null,
    confirmationSheet: null,
    manifests: [],
    purgeRequests: [],
    contentSearch: null,
    explorerVisibleLimit: 50,
    auto: {preview: null, selected: new Set(), visibleLimit: 25}
  };

  function applyExecutionState(executionState) {
    if (!executionState) {
      state.confirmationSheet = null;
      state.manifests = [];
      state.purgeRequests = [];
      return;
    }
    state.confirmationSheet = executionState.confirmation_sheet || null;
    state.manifests = executionState.manifests || [];
    state.purgeRequests = executionState.purge_requests || [];
  }

  const labels = {
    active: "使用中", archived: "已归档", cold: "冷存档", quarantine: "14 天隔离", unindexed: "未索引", missing: "文件缺失",
    protected: "必须保留", high_value: "建议保留", cold_archive: "建议冷存档", review_required: "需要确认",
    delete_candidate: "建议先隔离", permanent_delete_candidate: "可手动删除", unknown: "未知",
    cold_archive_action: "冷存档", keep: "保留", archive: "旧版归档标记", unarchive: "旧版取消归档标记", restore: "恢复到 Codex", protect: "锁定此会话，不参与整理",
    permanent_delete: "永久删除", purge_after_quarantine: "隔离到期后删除", current_session: "当前正在使用", pinned: "已置顶",
    permanent_protection: "永久保护", state_conflict_or_missing: "状态冲突或文件缺失", has_parent_or_child: "存在父子依赖",
    group_action_required: "需整组处理", unindexed_log: "未索引日志", automation: "自动化任务", verified_write_work: "检测到实际写入",
    title_value_hint_needs_review: "标题有价值信号，需确认", recent_automation_run: "自动化最近运行", old_automation_history: "较早的自动化历史",
    inactive_with_value_signal: "长期闲置，但有价值信号", inactive_without_unique_value: "长期闲置，未发现独有价值",
    old_short_temporary: "旧的短临时对话", old_large_session: "旧的大体积会话", insufficient_evidence: "证据不足",
    pin_snapshot_unavailable_or_stale: "置顶状态执行前待刷新", hard_protected: "真正锁定", not_plain_archive: "不是普通归档",
    manual_plan_conflict: "与人工计划冲突", planning_gate_closed: "数据库识别未通过", fresh_pin_snapshot_required: "置顶状态需要通过 Skill 同步；“刷新会话”只重新扫描本机会话。",
    codex_one_off_review: "Codex 判断为一次性对话", recent_one_off_review: "近期一次性对话", codex_value_review: "Codex 判断有复用价值",
    codex_review_uncertain: "Codex 判断仍需复核", inactive_60d_permanent_delete_candidate: "超过 60 天且符合低风险条件",
    incinerator_requires_archive_or_quarantine: "只接受隔离中的会话", incinerator_requires_plain_archive: "永久删除只接受普通归档会话",
    confirmation_sheet_missing_or_expired: "确认单已过期，请重新生成", second_confirmation_required: "请完成二次确认",
    planned_actions_changed_after_review: "确认后状态已变化，请重新生成确认单", confirmation_sheet_has_blockers: "确认单仍有执行阻塞",
    helper_already_running: "执行助手已在等待", important_warnings_not_acknowledged: "请先勾选知情确认",
    cold_storage_target_required: "请先在设置中选择冷存档目录", database_selection_required: "数据库识别未通过",
    directory_picker_unavailable: "当前系统不支持目录选择器", directory_picker_timeout: "目录选择超时，请重试",
    directory_picker_failed: "无法打开目录选择器", directory_picker_invalid_selection: "选择的目录不可用",
    unsafe_storage_target: "该目录不能作为冷存档位置", directory_not_writable: "该目录不可写，请选择其他目录",
    manifest_not_confirmed: "这个执行单未经过当前确认流程，请重新生成",
    ready: "待执行", running: "执行中", completed: "已完成", failed: "执行失败", stopped: "执行中断",
    helper_running: "执行助手仍在运行", helper_stopped_without_completion: "执行助手已停止，请检查日志",
    cold_archive_applied: "冷存档已完成", quarantine_applied: "隔离已完成", permanent_delete_applied: "永久删除已完成",
    restore_applied: "恢复已完成", purge_applied: "隔离包已永久删除", manifest_ready: "执行单有效",
    restore_not_verified: "当前机器还没有通过真实恢复闭环验证，恢复按钮保持禁用",
    restore_requires_cold_or_quarantine: "只有冷存档或 14 天隔离的会话才能恢复",
    restore_package_missing: "没有找到可恢复的数据包",
    restore_package_not_unique: "找到多个同名恢复包，请先人工核对",
    same_volume_no_system_disk_reclaim: "目标目录和 Codex 在同一磁盘，只能整理，不会释放这块磁盘的空间",
    cross_volume: "目标目录位于另一块磁盘，可释放当前 Codex 磁盘空间",
    no_destructive_plans: "没有可执行计划", unarchive_requires_plain_archive: "只有普通归档会话才能取消归档",
    codex_cli_unavailable: "未找到支持取消归档的 Codex CLI", official_unarchive_failed: "Codex 官方取消归档失败",
    official_unarchive_timeout: "Codex 官方取消归档超时", official_unarchive_not_verified: "取消归档后未通过重新扫描验证"
  };

  const labelFor = key => t(labels[key] || key || "无");

  const stateColors = {
    active: "var(--blue)", archived: "var(--green)", cold: "var(--violet)", quarantine: "var(--amber)",
    unindexed: "var(--red)", missing: "var(--red)"
  };
  const destructiveActions = new Set(["cold_archive", "quarantine", "permanent_delete", "purge_after_quarantine"]);
  const $ = selector => document.querySelector(selector);
  const $$ = selector => [...document.querySelectorAll(selector)];
  const el = (tag, className = "", text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== "") node.textContent = text;
    return node;
  };

  const staticTextNodes = [];
  const staticAttributes = [];

  function registerStaticTranslations() {
    const walker = document.createTreeWalker(document.documentElement, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      const source = node.nodeValue.trim();
      if (!source || !i18n.has(source)) continue;
      node.__i18nSource = source;
      staticTextNodes.push(node);
    }
    document.querySelectorAll("[placeholder], [aria-label]").forEach(element => {
      ["placeholder", "aria-label"].forEach(attribute => {
        const source = element.getAttribute(attribute);
        if (source && i18n.has(source)) staticAttributes.push({element, attribute, source});
      });
    });
  }

  function translateStatic() {
    document.documentElement.lang = i18n.locale();
    staticTextNodes.forEach(node => {
      const leading = node.nodeValue.match(/^\s*/)?.[0] || "";
      const trailing = node.nodeValue.match(/\s*$/)?.[0] || "";
      node.nodeValue = `${leading}${t(node.__i18nSource)}${trailing}`;
    });
    staticAttributes.forEach(({element, attribute, source}) => element.setAttribute(attribute, t(source)));
    const button = $("#languageBtn");
    button.textContent = i18n.locale() === "en" ? "中文" : "EN";
    button.setAttribute("aria-label", t(i18n.locale() === "en" ? "切换为中文" : "切换为英文"));
    document.title = t("Codex 会话生命周期");
  }

  function toggleLanguage() {
    i18n.setLocale(i18n.locale() === "en" ? "zh-CN" : "en");
    closeDrawer();
    translateStatic();
    if (state.catalog) renderAll();
  }
  const humanBytes = value => {
    let size = Math.max(0, Number(value) || 0);
    const units = ["B", "KiB", "MiB", "GiB", "TiB"];
    let index = 0;
    while (size >= 1024 && index < units.length - 1) { size /= 1024; index += 1; }
    return index ? `${size.toFixed(1)} ${units[index]}` : `${Math.round(size)} B`;
  };
  const shortDate = value => {
    const number = Number(value || 0);
    const date = new Date(number > 10_000_000_000 ? number : number * 1000);
    return Number.isNaN(date.valueOf()) ? "—" : date.toLocaleDateString(i18n.locale() === "en" ? "en-US" : "zh-CN");
  };
  const compactTitle = (value, maxLength = 80) => {
    const normalized = String(value || t("(无标题)")).replace(/\s+/g, " ").trim();
    return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 1)}…` : normalized;
  };
  const countdown = seconds => {
    const total = Math.max(0, Number(seconds) || 0);
    const days = Math.floor(total / 86400);
    const hours = Math.floor((total % 86400) / 3600);
    return days ? t("{days} 天 {hours} 小时", {days, hours}) : t("{hours} 小时", {hours});
  };
  const actionLabel = action => labelFor(action === "cold_archive" ? "cold_archive_action" : action);
  const planBlocked = session => session.actual_state === "active" || session.pinned || session.permanent_protection ||
    session.state_conflict || session.actual_state === "missing" || session.actual_state === "unindexed";
  const toast = message => {
    const node = $("#toast");
    node.textContent = message;
    node.classList.add("show");
    clearTimeout(toast.timer);
    toast.timer = setTimeout(() => node.classList.remove("show"), 3400);
  };

  async function api(path, options = {}) {
    const headers = {"Content-Type": "application/json", ...(options.headers || {})};
    if (options.method === "POST") headers["X-CSRF-Token"] = state.csrf;
    const response = await fetch(path, {...options, headers});
    let data;
    try { data = await response.json(); } catch { throw new Error(t("本地服务已断开")); }
    if (!response.ok) throw new Error(data.error || "request_failed");
    return data;
  }

  function switchView(id) {
    $$(".tab").forEach(node => {
      const active = node.dataset.view === id;
      node.classList.toggle("active", active);
      if (active) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current");
    });
    $$(".view").forEach(node => node.classList.toggle("active", node.id === `view-${id}`));
    if (id === "sessions") { renderExplorer(); loadAutoPreview(); }
    if (id === "queue") renderQueue();
    const heading = $(`#view-${id} h1`);
    if (heading) { heading.tabIndex = -1; heading.focus({preventScroll: true}); }
    window.scrollTo({top: 0, behavior: "auto"});
  }

  function metric(label, value, note, tone = "") {
    const card = el("article", `metric ${tone}`.trim());
    card.append(el("span", "label", label), el("strong", "", value), el("small", "", note));
    return card;
  }

  function lifecycleEntries() {
    const byState = state.catalog.summary.by_state || {};
    return ["active", "archived", "cold", "quarantine", "unindexed", "missing"]
      .map(key => ({key, label: labelFor(key), value: Number(byState[key] || 0), color: stateColors[key]}))
      .filter(item => item.value > 0);
  }

  function renderDonut(entries, total) {
    const donut = $("#lifecycleDonut");
    let cursor = 0;
    const segments = entries.map(item => {
      const start = cursor;
      cursor += 100 * item.value / Math.max(total, 1);
      return `${item.color} ${start.toFixed(2)}% ${cursor.toFixed(2)}%`;
    });
    donut.style.background = `conic-gradient(${segments.join(",") || "var(--line) 0 100%"})`;
    $("#donutTotal").textContent = String(total);
    const legend = $("#lifecycleLegend");
    legend.replaceChildren();
    entries.forEach(item => {
      const row = el("div", "legend-row");
      const dot = el("span", "legend-dot"); dot.style.background = item.color;
      row.append(dot, el("span", "", item.label), el("strong", "", String(item.value)));
      legend.append(row);
    });
  }

  function renderRecommendationChart() {
    const summary = state.catalog.summary;
    const chart = $("#recommendationChart");
    chart.replaceChildren();
    const order = ["protected", "high_value", "cold_archive", "delete_candidate", "permanent_delete_candidate", "review_required", "unknown"];
    const entries = order.map(key => [key, Number(summary.by_recommendation[key] || 0)]).filter(([, value]) => value > 0);
    const max = Math.max(1, ...entries.map(([, value]) => value));
    entries.forEach(([key, value]) => {
      const row = el("div", "bar-row");
      const track = el("div", "bar-track");
      const fill = el("div", `bar-fill rec-${key}`);
      fill.style.width = `${100 * value / max}%`;
      track.append(fill);
      row.append(el("span", "", labelFor(key)), track, el("strong", "", String(value)));
      chart.append(row);
    });
  }

  function renderStorage(entries) {
    const bytes = state.catalog.summary.bytes_by_state || {};
    const total = Number(state.catalog.summary.total_bytes || 0);
    $("#storageTotal").textContent = humanBytes(total);
    const stack = $("#storageStack"); stack.replaceChildren();
    const legend = $("#storageLegend"); legend.replaceChildren();
    entries.forEach(item => {
      const value = Number(bytes[item.key] || 0);
      if (!value) return;
      const segment = el("span", "storage-segment");
      segment.style.width = `${Math.max(0.6, 100 * value / Math.max(total, 1))}%`;
      segment.style.background = item.color;
      segment.title = `${item.label} ${humanBytes(value)}`;
      stack.append(segment);
      const row = el("div", "legend-row");
      const dot = el("span", "legend-dot"); dot.style.background = item.color;
      row.append(dot, el("span", "", item.label), el("strong", "", humanBytes(value)));
      legend.append(row);
    });
  }

  function renderAgeChart() {
    const bands = state.catalog.summary.archived_age_bands || {};
    const entries = [
      [t("7 天内"), Number(bands.under_7 || 0)],
      [t("7–29 天"), Number(bands.days_7_29 || 0)],
      [t("30–89 天"), Number(bands.days_30_89 || 0)],
      [t("90 天+"), Number(bands.days_90_plus || 0)]
    ];
    const max = Math.max(1, ...entries.map(([, value]) => value));
    const chart = $("#ageChart"); chart.replaceChildren();
    entries.forEach(([label, value]) => {
      const item = el("div", "column-item");
      const barWrap = el("div", "column-track");
      const bar = el("div", "column-fill");
      bar.style.height = `${Math.max(value ? 8 : 0, 100 * value / max)}%`;
      barWrap.append(bar);
      item.append(el("strong", "", String(value)), barWrap, el("span", "", label));
      chart.append(item);
    });
  }

  function renderHome() {
    const catalog = state.catalog;
    const summary = catalog.summary;
    const sessions = catalog.sessions;
    const plans = sessions.filter(item => destructiveActions.has(item.planned_action));
    const autoEligible = state.auto.preview
      ? state.auto.preview.proposals.filter(item => !item.blocked_reason)
      : sessions.filter(item => item.actual_state === "archived" && ["cold_archive", "delete_candidate"].includes(item.recommendation) && !item.relation_count && !planBlocked(item));
    const issueCount = Number(summary.unindexed || 0) + Number(summary.state_conflicts || 0);

    $("#homeTotal").textContent = String(summary.total);
    $("#homeStorage").textContent = humanBytes(summary.total_bytes);
    $("#homeCandidates").textContent = t("{count} 条", {count: autoEligible.length});
    $("#homePlans").textContent = t("{count} 条", {count: plans.length});
    $("#homeHeroSummary").textContent = t("{active} 条正在使用，{archived} 条已归档。系统发现 {eligible} 条可安全加入整理计划。", {active: summary.by_state.active || 0, archived: summary.by_state.archived || 0, eligible: autoEligible.length});
    $("#scanMeta").textContent = t("更新于 {time}", {time: new Date(catalog.generated_at).toLocaleString(i18n.locale() === "en" ? "en-US" : "zh-CN")});

    $("#metricGrid").replaceChildren(
      metric(t("正在使用"), String(summary.by_state.active || 0), t("不会进入破坏性计划"), "blue"),
      metric(t("普通归档"), String(summary.by_state.archived || 0), t("{percent}% 的会话", {percent: Math.round(100 * (summary.by_state.archived || 0) / Math.max(summary.total, 1))}), "green"),
      metric(t("需要检查"), String(issueCount), t("未索引或状态冲突"), issueCount ? "amber" : "green"),
      metric(t("可整理空间"), humanBytes(autoEligible.reduce((sum, item) => sum + Number(item.size_bytes || 0), 0)), t("冷存档或先隔离"), "violet")
    );

    const warning = $("#warningPanel");
    const issues = [];
    if (catalog.database_ambiguous) issues.push(t("检测到多个同样可信的数据库，执行功能已关闭。"));
    if (catalog.pin_snapshot_status !== "snapshot") issues.push(t("置顶状态需要在真正执行前刷新；现在可以安全浏览和制定计划。"));
    warning.classList.toggle("hidden", !issues.length);
    warning.textContent = issues.join(" ");

    const planningAllowed = Boolean(catalog.selected_database && !catalog.database_ambiguous);
    const gate = $("#gateBadge");
    gate.textContent = catalog.mutation_allowed ? t("可执行") : planningAllowed ? t("可规划") : t("只读");
    gate.classList.toggle("ok", catalog.mutation_allowed);

    const entries = lifecycleEntries();
    renderDonut(entries, summary.total);
    renderRecommendationChart();
    renderStorage(entries);
    renderAgeChart();

    const facts = $("#integrityList"); facts.replaceChildren();
    [
      [t("数据库"), catalog.database_ambiguous ? t("存在歧义") : t("识别正常"), catalog.database_ambiguous ? "danger" : "safe"],
      [t("置顶保护"), catalog.pin_snapshot_status === "snapshot" ? t("已同步") : t("执行前待同步"), catalog.pin_snapshot_status === "snapshot" ? "safe" : "warn"],
      [t("未索引日志"), String(summary.unindexed || 0), summary.unindexed ? "warn" : "safe"],
      [t("状态冲突"), String(summary.state_conflicts || 0), summary.state_conflicts ? "warn" : "safe"],
      [t("父子任务组"), String(summary.group_action_required || 0), summary.group_action_required ? "warn" : "safe"]
    ].forEach(([key, value, tone]) => {
      const row = el("div");
      row.append(el("dt", "", key), el("dd", `fact-${tone}`, value));
      facts.append(row);
    });

    const nextTitle = $("#nextActionTitle");
    const nextText = $("#nextActionText");
    const nextButton = $("#nextActionBtn");
    if (plans.length) {
      nextTitle.textContent = t("核对 {count} 条执行计划", {count: plans.length});
      nextText.textContent = t("计划还没有执行。进入下一页确认目标、空间和阻塞项。");
      nextButton.textContent = t("查看执行计划");
      nextButton.onclick = () => switchView("queue");
    } else if (autoEligible.length) {
      nextTitle.textContent = t("先整理 {count} 条旧会话", {count: autoEligible.length});
      nextText.textContent = t("系统已经分好冷存档和 14 天隔离，你只需检查后加入计划。");
      nextButton.textContent = t("查看整理建议");
      nextButton.onclick = () => switchView("sessions");
    } else {
      nextTitle.textContent = t("暂时不用处理");
      nextText.textContent = t("当前没有达到整理条件的普通归档。");
      nextButton.textContent = t("浏览全部会话");
      nextButton.onclick = () => switchView("sessions");
    }
    $("#autoCount").textContent = String(autoEligible.length);
    $("#planCount").textContent = String(plans.length);
  }

  function fillSelect(node, values) {
    const current = node.value;
    const first = node.options[0];
    node.replaceChildren(first);
    [...new Set(values)].sort().forEach(value => node.append(new Option(labelFor(value), value)));
    node.value = [...node.options].some(option => option.value === current) ? current : "";
  }

  function filteredSessions() {
    const query = $("#searchInput").value.trim().toLowerCase();
    const selectedState = $("#stateFilter").value;
    const recommendation = $("#recommendationFilter").value;
    const risk = $("#riskFilter").value;
    const turn = $("#turnFilter").value;
    const contentSearch = state.contentSearch?.query === query ? state.contentSearch : null;
    const candidates = contentSearch ? state.catalog.sessions.filter(session => contentSearch.byId.has(session.id)) : state.catalog.sessions;
    return candidates.filter(session => {
      const haystack = `${session.title} ${session.id} ${session.cwd}`.toLowerCase();
      return (contentSearch || !query || haystack.includes(query)) &&
        (!selectedState || session.actual_state === selectedState) &&
        (!recommendation || session.recommendation === recommendation) &&
        (!turn || (turn === "one" && session.business_turns === 1) ||
          (turn === "short" && session.business_turns >= 1 && session.business_turns <= 3) ||
          (turn === "reviewed" && session.semantic_review) ||
          (turn === "disposable" && session.semantic_review?.label === "one_off_disposable")) &&
        (!risk || (risk === "hard" && planBlocked(session)) ||
          (risk === "group" && session.execution_blocker === "group_action_required") ||
          (risk === "conflict" && session.state_conflict) ||
          (risk === "planned" && session.planned_action));
    });
  }

  function renderExplorer() {
    const rows = $("#sessionRows"); rows.replaceChildren();
    const filtered = filteredSessions();
    const visible = filtered.slice(0, state.explorerVisibleLimit);
    $("#resultCount").textContent = t("匹配 {count} 条", {count: filtered.length});
    visible.forEach(session => {
      const row = el("tr");
      const titleCell = el("td", "title-cell");
      const open = el("button", "session-link");
      open.setAttribute("aria-label", t("查看会话：{title}", {title: session.title || t("(无标题)")}));
      const title = el("strong", "", compactTitle(session.title)); title.title = session.title || t("(无标题)");
      open.append(title, el("small", "", session.id));
      const hit = state.contentSearch?.byId.get(session.id);
      const first = hit?.excerpts?.[0];
      if (first) {
        const role = first.role === "user" ? t("用户") : first.role === "assistant" ? "Codex" : t("工具产出");
        open.append(el("small", "content-hit", t("正文命中（{role}）：{excerpt}", {role, excerpt: first.excerpt})));
      }
      open.addEventListener("click", () => showDetail(session));
      titleCell.append(open); row.append(titleCell);
      const actual = el("td"); actual.append(el("span", `state-pill${session.state_conflict ? " danger" : ""}`, labelFor(session.actual_state))); row.append(actual);
      const recommendationClass = planBlocked(session) ? " danger" : session.execution_blocker ? " warn" : session.recommendation === "high_value" ? " safe" : "";
      const rec = el("td"); rec.append(el("span", `state-pill${recommendationClass}`, labelFor(session.recommendation))); row.append(rec);
      row.append(el("td", "", shortDate(session.updated_at)), el("td", "", humanBytes(session.size_bytes)), el("td", "", actionLabel(session.planned_action)));
      rows.append(row);
    });
    $("#explorerTableStatus").textContent = filtered.length ? t("已显示 {shown} / {total} 条", {shown: visible.length, total: filtered.length}) : t("没有符合条件的会话");
    $("#loadMoreExplorerBtn").classList.toggle("hidden", visible.length >= filtered.length);
  }

  async function searchArchivedContent() {
    const query = $("#searchInput").value.trim();
    if (query.length < 2) { toast(t("至少输入两个字")); return; }
    const button = $("#searchContentBtn");
    const status = $("#contentSearchStatus");
    button.disabled = true; button.textContent = t("搜索中…");
    status.classList.remove("hidden"); status.textContent = t("正在本地搜索归档正文，不会更改会话。");
    try {
      const started = await api("/api/search-archived-content", {method: "POST", body: JSON.stringify({query, limit: 100})});
      const deadline = Date.now() + 5 * 60 * 1000;
      let data;
      while (Date.now() < deadline) {
        const progress = await api(`/api/search-archived-content/status?job=${encodeURIComponent(started.job_id)}`);
        const total = Math.max(0, Number(progress.total) || 0);
        const scanned = Math.min(total, Number(progress.scanned) || 0);
        status.textContent = t("已搜索 {scanned} / {total} 条，找到 {matches} 条。", {scanned, total, matches: Number(progress.matches) || 0});
        if (progress.status === "complete") { data = progress.result; break; }
        if (progress.status === "error") throw new Error(progress.error || "content_search_failed");
        await new Promise(resolve => setTimeout(resolve, 350));
      }
      if (!data) throw new Error(t("正文搜索超时，请缩小关键词范围"));
      state.contentSearch = {query: query.toLowerCase(), byId: new Map(data.matches.map(item => [item.session_id, item]))};
      state.explorerVisibleLimit = 50;
      renderExplorer();
      status.textContent = data.matches.length ? t("正文搜索完成：{count} 条归档会话命中。", {count: data.matches.length}) : t("没有找到“{query}”。", {query});
    } catch (error) {
      state.contentSearch = null; renderExplorer(); status.textContent = t("正文搜索失败：{error}", {error: labelFor(error.message)});
    } finally {
      button.disabled = false; button.textContent = t("搜索归档正文");
    }
  }

  function detailMetadata(session) {
    const details = el("details", "technical-details");
    const list = el("dl", "detail-grid");
    details.append(el("summary", "", t("技术详情")));
    [
      ["Session ID", session.id], [t("现状"), labelFor(session.actual_state)], [t("建议"), labelFor(session.recommendation)],
      [t("计划"), actionLabel(session.planned_action)], [t("闲置"), t("{count} 天", {count: Number(session.age_days || 0)})], [t("占用"), humanBytes(session.size_bytes)],
      [t("置顶"), session.pinned ? t("是") : labelFor(session.pin_status)], [t("永久保护"), session.permanent_protection ? t("是") : t("否")],
      [t("父子依赖"), session.execution_blocker ? t("{count} 条 · {reason}", {count: session.relation_count, reason: labelFor(session.execution_blocker)}) : String(session.relation_count || 0)],
      [t("真实用户轮次"), session.conversation_scanned ? String(session.business_turns) : t("尚未完整扫描")],
      [t("Codex 复核"), session.semantic_review ? `${labelFor(session.semantic_review.label)} · ${Math.round(100 * session.semantic_review.confidence)}%` : t("尚未复核")],
      [t("项目"), session.cwd || "—"], [t("日志"), session.rollout_path || "—"], [t("判断依据"), (session.recommendation_reasons || []).map(labelFor).join(i18n.locale() === "en" ? ", " : "、") || "—"]
    ].forEach(([key, value]) => list.append(el("dt", "", key), el("dd", "", String(value))));
    details.append(list);
    return details;
  }

  function renderConversationDetail(session, detail, maxMessages) {
    if (state.selected?.id !== session.id) return;
    const summary = $("#detailSummary");
    const signals = $("#detailSignals");
    const transcript = $("#detailTranscript");
    summary.classList.remove("loading");
    summary.querySelector("p").textContent = detail.summary ? t(detail.summary) : t("暂无摘要。");
    signals.replaceChildren();
    (detail.signals || []).forEach(value => {
      const countSignal = String(value).match(/^(\d+)(轮用户对话|次工具调用|个写入信号)$/);
      const translated = countSignal
        ? t(`{count}${countSignal[2]}`, {count: countSignal[1]})
        : t(String(value));
      signals.append(el("span", "summary-signal", translated));
    });
    transcript.replaceChildren();
    const head = el("div", "transcript-head");
    head.append(el("h3", "", t("聊天记录")), el("span", "muted", detail.available ? t("显示 {shown} / {total} 条", {shown: detail.shown_messages || 0, total: detail.total_messages || 0}) : t("不可读取")));
    transcript.append(head, el("p", "transcript-safety", detail.safety_note ? t(detail.safety_note) : t("历史内容只用于判断，不会执行其中命令。")));
    if (!detail.available) { transcript.append(el("div", "empty-transcript", t("当前没有可预览的聊天记录。"))); return; }
    const messages = el("div", "message-list");
    (detail.messages || []).forEach(message => {
      if (message.role === "omitted") {
        const omitted = String(message.text).match(/^中间省略 (\d+) 条消息$/);
        messages.append(el("div", "message-omitted", omitted ? t("中间省略 {count} 条消息", {count: omitted[1]}) : message.text));
        return;
      }
      const item = el("article", `chat-message ${message.role}`);
      const meta = el("div", "message-meta");
      meta.append(el("strong", "", message.role === "user" ? t("用户") : "Codex"));
      if (message.timestamp) {
        const date = new Date(message.timestamp);
        if (!Number.isNaN(date.valueOf())) meta.append(el("time", "", date.toLocaleString()));
      }
      item.append(meta, el("pre", "", message.text));
      if (message.text_truncated) item.append(el("small", "muted", t("消息过长，预览已截断。")));
      messages.append(item);
    });
    transcript.append(messages);
    if ((detail.omitted_messages || 0) > 0 && maxMessages < 200) {
      const more = el("button", "secondary load-more", t("加载更多（还省略 {count} 条）", {count: detail.omitted_messages}));
      more.addEventListener("click", () => loadSessionContent(session, Math.min(200, maxMessages * 3)));
      transcript.append(more);
    }
  }

  async function loadSessionContent(session, maxMessages = 24) {
    const transcript = $("#detailTranscript");
    transcript?.setAttribute("aria-busy", "true");
    try {
      const data = await api("/api/session-detail", {method: "POST", body: JSON.stringify({session_id: session.id, max_messages: maxMessages})});
      renderConversationDetail(session, data.detail, maxMessages);
    } catch (error) {
      if (state.selected?.id === session.id) {
        $("#detailSummary").classList.remove("loading");
        $("#detailSummary").querySelector("p").textContent = t("摘要读取失败。");
        $("#detailTranscript").replaceChildren(el("div", "empty-transcript", t("聊天记录读取失败：{error}", {error: error.message})));
      }
    } finally {
      if (state.selected?.id === session.id) $("#detailTranscript")?.setAttribute("aria-busy", "false");
    }
  }

  function planButton(session, action, label, className = "secondary") {
    const active = session.planned_action === action;
    const button = el("button", `${className}${active ? " selected-action" : ""}`, active ? t("取消{label}", {label}) : label);
    button.addEventListener("click", () => plan(session.id, active ? null : action));
    return button;
  }

  function showDetail(session) {
    state.lastFocused = document.activeElement;
    state.selected = session;
    const detailTitle = $("#detailTitle");
    detailTitle.textContent = compactTitle(session.title, 96);
    detailTitle.title = session.title || t("(无标题)");
    const body = $("#detailBody");
    const summary = el("section", "detail-summary loading"); summary.id = "detailSummary";
    const summaryHead = el("div", "summary-head");
    summaryHead.append(el("h3", "", t("快速摘要")), el("span", "summary-source", t("本地规则")));
    summary.append(summaryHead, el("p", "", t("正在读取对应聊天日志…")));
    const signals = el("div", "summary-signals"); signals.id = "detailSignals"; summary.append(signals);
    const transcript = el("section", "transcript"); transcript.id = "detailTranscript"; transcript.setAttribute("aria-live", "polite");
    transcript.append(el("div", "empty-transcript", t("正在加载聊天记录…")));
    const actions = el("section", "drawer-actions");
    const executionLocked = state.manifests.some(manifest => ["ready", "running"].includes(manifest.status));
    if (executionLocked) {
      actions.append(
        el("h3", "drawer-action-title", t("执行单已锁定")),
        el("p", "field-status", t("执行单已经生成；为避免确认后状态变化，这里暂时只读。"))
      );
      const reviewPlan = el("button", "primary", t("返回执行计划"));
      reviewPlan.addEventListener("click", () => { closeDrawer(); switchView("queue"); });
      actions.append(reviewPlan);
      body.replaceChildren(summary, actions, transcript, detailMetadata(session));
      const drawer = $("#drawer");
      drawer.inert = false; drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
      $("#drawerScrim").classList.add("open"); $("#drawerScrim").setAttribute("aria-hidden", "false");
      document.body.classList.add("modal-open");
      $("#closeDrawer").focus();
      loadSessionContent(session);
      return;
    }
    actions.append(el("h3", "drawer-action-title", t("选择下一步")));
    if (session.actual_state === "archived") {
      const unarchive = el("button", "secondary", t("取消归档"));
      unarchive.disabled = !state.capabilities.official_unarchive || Boolean(session.state_conflict);
      if (unarchive.disabled) unarchive.title = t(session.state_conflict ? "状态冲突时不能取消归档" : "当前 Codex CLI 不支持取消归档");
      unarchive.addEventListener("click", () => unarchiveSession(session, unarchive));
      actions.append(unarchive);
    }
    const protect = el("button", "secondary", session.permanent_protection ? t("解除锁定") : t("锁定此会话，不参与整理"));
    protect.addEventListener("click", () => toggleProtect(session.id, !session.permanent_protection));
    actions.append(protect);
    if (["cold", "quarantine"].includes(session.actual_state)) {
      const restore = el("button", "secondary", t("退出 Codex 并恢复"));
      restore.disabled = !state.capabilities.indexed_restore_to_codex;
      const restoreReason = state.capabilities.reason_code ? labelFor(state.capabilities.reason_code) : t(state.capabilities.reason || "当前机器还没有通过真实恢复闭环验证，恢复按钮保持禁用");
      if (restore.disabled) restore.title = restoreReason;
      restore.addEventListener("click", () => launchRestore(session.id));
      actions.append(restore);
      if (restore.disabled) {
        actions.append(el("small", "field-status restore-gate-help", `${restoreReason} ${t("请按 docs/VERIFICATION.md 完成一次“运行中 → 退出 → 恢复”的真实验证。")}`));
      }
    }
    if (session.actual_state === "quarantine" && session.purge_eligible) {
      const purge = el("button", "danger-button", t("永久删除"));
      purge.addEventListener("click", () => openFinalConfirm({
        title: t("确认永久删除隔离包？"),
        body: t("只保留脱敏审计记录。"),
        warning: t("删除后无法恢复。"),
        confirmLabel: t("确认永久删除"),
        trigger: purge,
        onConfirm: () => launchPurge({session_id: session.id})
      }));
      actions.append(purge);
    }
    const actionButtonsShown = session.actual_state === "archived" && !planBlocked(session) && !session.relation_count;
    if (actionButtonsShown) {
      actions.append(
        planButton(session, "cold_archive", t("冷存档")),
        planButton(session, "quarantine", t("隔离 14 天")),
        planButton(session, "permanent_delete", t("永久删除"), "danger-button")
      );
    }
    const currentPlanAlreadyShown = actionButtonsShown && ["cold_archive", "quarantine", "permanent_delete"].includes(session.planned_action);
    if (session.planned_action && !currentPlanAlreadyShown) {
      const clearPlan = el("button", "secondary", t("清除旧计划"));
      clearPlan.addEventListener("click", () => plan(session.id, null));
      actions.append(clearPlan);
    }
    body.replaceChildren(summary, actions, transcript, detailMetadata(session));
    const drawer = $("#drawer");
    drawer.inert = false; drawer.classList.add("open"); drawer.setAttribute("aria-hidden", "false");
    $("#drawerScrim").classList.add("open"); $("#drawerScrim").setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    $("#closeDrawer").focus();
    loadSessionContent(session);
  }

  function closeDrawer() {
    const drawer = $("#drawer");
    drawer.classList.remove("open"); drawer.setAttribute("aria-hidden", "true"); drawer.inert = true;
    $("#drawerScrim").classList.remove("open"); $("#drawerScrim").setAttribute("aria-hidden", "true");
    document.body.classList.remove("modal-open");
    if (state.lastFocused?.isConnected) state.lastFocused.focus();
  }

  async function plan(id, action) {
    try {
      const data = await api("/api/plan", {method: "POST", body: JSON.stringify({session_id: id, action})});
      state.catalog = data.catalog; applyExecutionState(data.execution_state);
      renderAll(); closeDrawer(); await loadAutoPreview();
      toast(action ? t("已加入计划：{action}", {action: actionLabel(action)}) : t("已取消计划"));
    } catch (error) { toast(labels[error.message] ? labelFor(error.message) : t("计划失败：{error}", {error: error.message})); }
  }

  async function toggleProtect(id, enabled) {
    try {
      const data = await api("/api/protect", {method: "POST", body: JSON.stringify({session_id: id, enabled})});
      state.catalog = data.catalog; applyExecutionState(data.execution_state);
      renderAll(); closeDrawer(); await loadAutoPreview();
      toast(enabled ? t("已锁定，不会再进入整理建议") : t("已解除锁定"));
    } catch (error) { toast(t("操作失败：{error}", {error: error.message})); }
  }

  async function unarchiveSession(session, button) {
    button.disabled = true;
    button.textContent = t("正在取消归档…");
    try {
      const data = await api("/api/unarchive", {method: "POST", body: JSON.stringify({session_id: session.id})});
      state.catalog = data.catalog; applyExecutionState(data.execution_state);
      renderAll(); closeDrawer(); await loadAutoPreview();
      toast(t("已取消归档，Session 已回到 Codex"));
    } catch (error) {
      button.disabled = false;
      button.textContent = t("取消归档");
      toast(t("取消归档失败：{error}", {error: labelFor(error.message)}));
    }
  }

  function closeFinalConfirm() {
    const dialog = $("#finalConfirmDialog");
    dialog.classList.remove("open"); dialog.setAttribute("aria-hidden", "true"); dialog.inert = true;
    $("#finalConfirmScrim").classList.remove("open"); $("#finalConfirmScrim").setAttribute("aria-hidden", "true");
    const target = state.confirmDialog?.trigger?.isConnected ? state.confirmDialog.trigger : null;
    state.confirmDialog = null;
    if (!$("#drawer").classList.contains("open")) document.body.classList.remove("modal-open");
    target?.focus();
  }

  function openFinalConfirm({title, body, warning, acknowledgement, confirmLabel, onConfirm, trigger}) {
    const dialog = $("#finalConfirmDialog");
    $("#finalConfirmTitle").textContent = title;
    $("#finalConfirmBody").textContent = body;
    const warningNode = $("#finalConfirmWarning");
    warningNode.className = warning ? "danger-callout" : "hidden"; warningNode.textContent = warning || "";
    const ackWrap = $("#finalConfirmAcknowledgement");
    const ack = $("#finalConfirmAck");
    ack.checked = !acknowledgement; ackWrap.classList.toggle("hidden", !acknowledgement); $("#finalConfirmAckText").textContent = acknowledgement || "";
    const commit = $("#commitFinalConfirm");
    commit.textContent = confirmLabel; commit.disabled = Boolean(acknowledgement);
    const update = () => { commit.disabled = Boolean(acknowledgement) && !ack.checked; };
    ack.onchange = update;
    state.confirmDialog = {trigger, onConfirm};
    commit.onclick = async () => {
      if (commit.disabled || !state.confirmDialog) return;
      commit.disabled = true;
      const completed = await state.confirmDialog.onConfirm(ack.checked);
      if (completed) closeFinalConfirm(); else update();
    };
    dialog.inert = false; dialog.classList.add("open"); dialog.setAttribute("aria-hidden", "false");
    $("#finalConfirmScrim").classList.add("open"); $("#finalConfirmScrim").setAttribute("aria-hidden", "false");
    document.body.classList.add("modal-open");
    setTimeout(() => $("#cancelFinalConfirm").focus(), 0);
  }

  function permanentDeleteStatus(session) {
    if (session.planned_action === "permanent_delete" || (session.planned_action === "purge_after_quarantine" && session.actual_state === "archived")) return t("等待永久删除确认");
    if (session.actual_state !== "quarantine") return t("等待进入 14 天隔离");
    if (session.purge_eligible) return t("隔离已到期");
    if (session.quarantine_remaining_seconds != null) return t("还剩 {time}", {time: countdown(session.quarantine_remaining_seconds)});
    return t("隔离时间待校验");
  }

  function renderQueue() {
    const list = $("#queueList"); list.replaceChildren();
    const plans = state.catalog.sessions.filter(session => session.planned_action);
    const currentPlans = plans.filter(session => destructiveActions.has(session.planned_action));
    const legacyPlans = plans.filter(session => !destructiveActions.has(session.planned_action));
    const actionable = currentPlans.filter(session => !session.execution_blocker);
    const executionActive = state.manifests.some(manifest => ["ready", "running"].includes(manifest.status));
    const appendPlan = (container, session, legacy = false) => {
      const item = el("article", `queue-item${session.execution_blocker ? " blocked" : ""}${legacy ? " legacy" : ""}`);
      const status = legacy ? t("旧版标记，仅记录，不会在这里执行") : session.execution_blocker ? labelFor(session.execution_blocker) :
        ["permanent_delete", "purge_after_quarantine"].includes(session.planned_action) ? permanentDeleteStatus(session) : actionLabel(session.planned_action);
      const title = el("strong", "", compactTitle(session.title || session.id)); title.title = session.title || session.id;
      item.append(title, el("span", "", status), el("span", "", humanBytes(session.size_bytes)));
      if (session.actual_state === "quarantine" && session.purge_eligible) {
        const purge = el("button", "danger-button", t("永久删除")); purge.addEventListener("click", () => requestPurge(session.id)); item.append(purge);
      }
      const cancel = el("button", "secondary", t("取消计划")); cancel.addEventListener("click", () => plan(session.id, null)); item.append(cancel);
      container.append(item);
    };
    if (!executionActive) currentPlans.forEach(session => appendPlan(list, session));
    if (!currentPlans.length && !state.manifests.length) {
      const empty = el("section", "empty-state");
      empty.append(el("h2", "", t("还没有可执行计划")), el("p", "muted", t("先去“会话”查看系统建议，加入计划后再回来确认。")));
      const button = el("button", "", t("查看整理建议")); button.addEventListener("click", () => switchView("sessions")); empty.append(button); list.append(empty);
    }
    if (legacyPlans.length && !executionActive) {
      const legacy = el("details", "panel legacy-plans");
      legacy.append(el("summary", "", t("{count} 条旧版标记（不会执行）", {count: legacyPlans.length})));
      const legacyList = el("div", "queue-list");
      legacyPlans.forEach(session => appendPlan(legacyList, session, true));
      legacy.append(legacyList); list.append(legacy);
    }
    $("#plannedBytes").textContent = humanBytes(actionable.reduce((sum, session) => sum + Number(session.size_bytes || 0), 0));
    $("#planCount").textContent = String(currentPlans.length);
    $("#prepareBtn").disabled = executionActive || !actionable.length;
    $("#queueFooter").classList.toggle("hidden", executionActive || !currentPlans.length);
    $("#capabilityNotice").textContent = executionActive
      ? t("执行单已生成。原计划已锁定，不再重复显示；点击下方按钮后，助手会等待 Codex 完全退出再执行。")
      : state.manifests.length && !currentPlans.length
        ? t("操作已有结果。这里保留完成或失败凭证，不再显示已经收口的旧计划。")
        : t("计划不会自动执行。确认单只会再核对一次置顶、父子关系、数据库和 Codex 进程；确认后直接生成执行单，不再弹第三层窗口。");
    renderConfirmationSheet(); renderManifests();
  }

  function renderConfirmationSheet() {
    const host = $("#confirmationSheet"); host.replaceChildren();
    const sheet = state.confirmationSheet;
    if (!sheet || (sheet.confirmed && state.manifests.length)) { host.classList.add("hidden"); return; }
    host.classList.remove("hidden");
    const panel = el("section", "confirmation-panel");
    const head = el("div", "confirmation-head");
    const title = el("div"); title.append(el("p", "eyebrow", "LOCAL OPERATION RECEIPT"), el("h2", "", t("本次操作确认单")));
    head.append(title, el("span", "state-pill", sheet.confirmed ? t("待执行") : sheet.can_execute ? t("待确认") : t("存在阻塞"))); panel.append(head);
    const metrics = el("div", "confirmation-metrics");
    [[t("冷存档"), sheet.counts.cold_archive], [t("14 天隔离"), sheet.counts.quarantine], [t("永久删除"), sheet.counts.permanent_delete], [t("影响空间"), humanBytes(sheet.total_bytes)]]
      .forEach(([label, value]) => { const item = el("div"); item.append(el("span", "", label), el("strong", "", String(value))); metrics.append(item); });
    panel.append(metrics);
    if (sheet.counts.permanent_delete) panel.append(el("div", "danger-callout", t("{count} 条会话会直接永久删除，不经过隔离期。", {count: sheet.counts.permanent_delete})));
    if (sheet.warnings.length) {
      const warning = el("section", "receipt-section warning-section");
      warning.append(el("h3", "", t("{count} 条永久删除项可能重要", {count: sheet.warnings.length})), el("p", "muted", t("请逐条看完，再决定是否继续。")));
      const rows = el("div", "receipt-rows");
      sheet.warnings.forEach(entry => {
        const row = el("article", "receipt-row"); row.append(el("strong", "", entry.title), el("span", "", entry.reasons.join("；")), el("small", "", humanBytes(entry.size_bytes))); rows.append(row);
      });
      warning.append(rows); panel.append(warning);
    }
    if (sheet.blockers.length) {
      const blocked = el("section", "receipt-section blocker-section");
      blocked.append(el("h3", "", t("{count} 个阻塞需要先解决", {count: sheet.blockers.length})));
      const list = el("ul"); sheet.blockers.forEach(entry => list.append(el("li", "", labels[entry.code] ? labelFor(entry.code) : (entry.message || entry.code)))); blocked.append(list); panel.append(blocked);
    }
    const confirm = el("section", "local-confirm");
    confirm.append(el("p", "", sheet.confirmed ? t("已生成执行单。接下来只需在执行计划里点击启动。") : t("确认后会直接生成执行单，不再弹出额外窗口。")));
    if (sheet.warnings.length) {
      const ack = el("label", "acknowledge inline");
      const checkbox = el("input");
      checkbox.type = "checkbox";
      checkbox.id = `receipt-ack-${sheet.sheet_id}`;
      const text = el("span", "", t("我已逐条检查可能重要的会话，仍确认继续"));
      ack.append(checkbox, text);
      confirm.append(ack);
    }
    const button = el("button", "", sheet.confirmed ? t("已生成执行单") : t("生成执行单"));
    const acknowledgeBox = sheet.warnings.length ? null : true;
    const updateDisabled = () => {
      const checked = sheet.warnings.length ? Boolean($("#confirmationSheet")?.querySelector(`#receipt-ack-${CSS.escape(sheet.sheet_id)}`)?.checked) : true;
      button.disabled = sheet.confirmed || !sheet.can_execute || !checked;
    };
    updateDisabled();
    if (sheet.warnings.length) {
      const checkbox = confirm.querySelector(`#receipt-ack-${CSS.escape(sheet.sheet_id)}`);
      checkbox.addEventListener("change", updateDisabled);
    }
    button.addEventListener("click", () => confirmOperationSheet(sheet, sheet.warnings.length ? Boolean(confirm.querySelector(`#receipt-ack-${CSS.escape(sheet.sheet_id)}`)?.checked) : false));
    confirm.append(button);
    panel.append(confirm); host.append(panel);
  }

  function renderManifests() {
    const list = $("#manifestList"); list.replaceChildren();
    state.manifests.forEach(manifest => {
      const item = el("article", "manifest-item");
      const actionText = manifest.action === "restore" ? t("恢复到 Codex") : actionLabel(manifest.action);
      const isDirectManifest = manifest.kind === "manifest";
      const isRestore = manifest.action === "restore";
      const isLaunchable = (isDirectManifest || isRestore) && manifest.status === "ready";
      item.append(el("strong", "", t("{action} · {count} 条 · {bytes}", {action: actionText, count: manifest.session_ids.length, bytes: humanBytes(manifest.bytes)})));
      item.append(el("span", "", labelFor(manifest.status)));
      if (manifest.detail) item.append(el("small", "muted", labelFor(manifest.detail)));
      if (Array.isArray(manifest.volume_notes) && manifest.volume_notes.length) {
        item.append(el("small", "muted", manifest.volume_notes.map(note => labelFor(note)).join("；")));
      }
      if (isDirectManifest || isRestore) {
        const launch = el("button", "", isRestore ? t("退出 Codex 并恢复") : t("退出 Codex 并执行"));
        launch.disabled = !isLaunchable;
        launch.addEventListener("click", () => isRestore ? launchRestore(manifest.session_ids[0]) : launchAndQuitHelper(manifest));
        item.append(launch);
      }
      item.append(el("small", "muted", manifest.action === "permanent_delete" ? t("没有恢复期。失败时使用临时副本回滚。") : manifest.action === "restore" ? t("只有通过真实闭环验证的机器，才会启用恢复按钮。") : manifest.kind === "purge" ? t("删除后只保留脱敏审计记录。") : t("执行助手会等待 Codex 完全退出。")));
      list.append(item);
    });
    state.purgeRequests.forEach(request => {
      const item = el("article", "manifest-item purge-confirm");
      item.append(el("strong", "", t("隔离到期 · {id}", {id: request.session_id})));
      const launch = el("button", "danger-button", t("永久删除"));
      launch.addEventListener("click", () => openFinalConfirm({title: t("确认永久删除隔离包？"), body: t("只保留脱敏审计记录。"), warning: t("删除后无法恢复。"), confirmLabel: t("确认永久删除"), trigger: launch, onConfirm: () => launchPurge(request)}));
      item.append(launch); list.append(item);
    });
  }

  async function requestPurge(sessionId) {
    try {
      const data = await api("/api/purge-request", {method: "POST", body: JSON.stringify({session_id: sessionId})});
      state.purgeRequests = [...state.purgeRequests.filter(item => item.session_id !== sessionId), data.request];
      renderManifests(); toast(t("已准备最终确认"));
    } catch (error) { toast(t("无法准备永久删除：{error}", {error: labelFor(error.message)})); }
  }

  async function launchPurge(request) {
    try {
      const data = await api("/api/launch-purge", {method: "POST", body: JSON.stringify({session_id: request.session_id, second_confirmation: true})});
      applyExecutionState(data.execution_state);
      const refreshed = await api("/api/refresh", {method: "POST", body: "{}"});
      state.catalog = refreshed.catalog; applyExecutionState(refreshed.execution_state); renderAll();
      toast(t("永久删除助手已启动，PID {pid}", {pid: data.helper.pid})); return true;
    } catch (error) { toast(t("永久删除未启动：{error}", {error: labelFor(error.message)})); return false; }
  }

  async function prepareConfirmationSheet() {
    try {
      const data = await api("/api/confirmation-sheet", {method: "POST", body: "{}"});
      state.confirmationSheet = data.sheet; applyExecutionState(data.execution_state); renderQueue();
      $("#confirmationSheet").scrollIntoView({behavior: "smooth", block: "start"});
    } catch (error) { toast(t("确认单生成失败：{error}", {error: labelFor(error.message)})); }
  }

  async function confirmOperationSheet(sheet, warningsAcknowledged) {
    try {
      const data = await api("/api/confirm-sheet", {method: "POST", body: JSON.stringify({sheet_id: sheet.sheet_id, warnings_acknowledged: warningsAcknowledged, second_confirmation: true})});
      sheet.confirmed = true; state.manifests = data.manifests; applyExecutionState(data.execution_state); renderQueue();
      $("#manifestList").scrollIntoView({behavior: "smooth", block: "start"});
      toast(t("已生成 {count} 个执行单", {count: state.manifests.length})); return true;
    } catch (error) { toast(t("二次确认未通过：{error}", {error: labelFor(error.message)})); return false; }
  }

  async function launchAndQuitHelper(manifest) {
    try {
      const data = await api("/api/launch-and-quit", {method: "POST", body: JSON.stringify({manifest: manifest.path})});
      applyExecutionState(data.execution_state);
      const refreshed = await api("/api/refresh", {method: "POST", body: "{}"});
      state.catalog = refreshed.catalog; applyExecutionState(refreshed.execution_state); renderAll();
      if (data.manual_exit_required) toast(t("执行助手已启动（PID {pid}），请手动完全退出 Codex", {pid: data.helper.pid}));
      else toast(t("执行助手已启动（PID {pid}），正在退出 Codex", {pid: data.helper.pid}));
    } catch (error) { toast(t("执行助手未启动：{error}", {error: labelFor(error.message)})); }
  }

  async function launchRestore(sessionId) {
    try {
      const data = await api("/api/launch-restore", {method: "POST", body: JSON.stringify({session_id: sessionId})});
      applyExecutionState(data.execution_state);
      const refreshed = await api("/api/refresh", {method: "POST", body: "{}"});
      state.catalog = refreshed.catalog; applyExecutionState(refreshed.execution_state); renderAll();
      if (data.manual_exit_required) toast(t("恢复助手已启动（PID {pid}），请手动完全退出 Codex", {pid: data.helper.pid}));
      else toast(t("恢复助手已启动（PID {pid}），正在退出 Codex", {pid: data.helper.pid}));
    } catch (error) { toast(t("恢复未启动：{error}", {error: labelFor(error.message)})); }
  }

  function renderReviewMetrics() {
    const summary = state.catalog.summary;
    const node = $("#reviewMetrics"); node.replaceChildren();
    [[t("已扫描"), summary.conversation_scanned || 0], [t("3 轮以内"), summary.short_conversations || 0], [t("Codex 已复核"), summary.codex_reviewed || 0], [t("一次性"), summary.codex_one_off || 0]]
      .forEach(([label, value]) => node.append(el("span", "", `${label} ${value}`)));
  }

  async function prepareReviewBundle() {
    const button = $("#prepareReviewBtn"); button.disabled = true; button.textContent = t("正在扫描…");
    try {
      const data = await api("/api/review-bundle", {method: "POST", body: JSON.stringify({max_turns: Number($("#reviewMaxTurns").value)})});
      state.catalog = data.catalog; applyExecutionState(data.execution_state); renderAll();
      const notice = $("#reviewBundleNotice"); notice.classList.remove("hidden");
      notice.replaceChildren(el("strong", "", t("发现 {short} 条短对话，其中 {clean} 条没有写入或附件。", {short: data.summary.short_conversations, clean: data.summary.clean_one_off_candidates})), el("code", "", data.bundle_path), el("span", "", t("回到 Codex 输入“复核一次性对话”。")));
    } catch (error) { toast(t("短对话扫描失败：{error}", {error: error.message})); }
    finally { button.disabled = false; button.textContent = t("准备复核包"); }
  }

  function renderAuto() {
    const preview = state.auto.preview;
    if (!preview) return;
    const summary = preview.summary;
    const eligible = preview.proposals.filter(item => !item.blocked_reason);
    const cold = eligible.filter(item => item.action === "cold_archive").length;
    const quarantine = eligible.filter(item => item.action === "quarantine").length;
    $("#autoHeadline").textContent = eligible.length ? t("建议整理 {count} 条旧会话", {count: eligible.length}) : t("当前没有需要自动整理的会话");
    $("#autoSummary").textContent = eligible.length ? t("{cold} 条冷存档，{quarantine} 条先隔离 14 天。加入计划后仍需你确认才会执行。", {cold, quarantine}) : t("可以继续浏览全部会话，或调整闲置时间设置。");
    $("#autoMetricGrid").replaceChildren(
      metric(t("冷存档"), String(cold), t("保留内容，移出当前索引"), "violet"),
      metric(t("先隔离"), String(quarantine), t("14 天内可恢复"), "amber"),
      metric(t("涉及空间"), humanBytes(eligible.reduce((sum, item) => sum + Number(item.size_bytes || 0), 0)), t("按真实日志大小"), "blue")
    );
    const gate = $("#autoGateNotice");
    gate.classList.toggle("hidden", preview.planning_allowed && preview.execution_ready);
    gate.textContent = !preview.planning_allowed ? t("数据库识别存在歧义，现在只能浏览。") : !preview.execution_ready ? t("可以先加入计划；真正执行前需要刷新置顶状态。") : "";
    const rows = $("#autoProposalRows"); rows.replaceChildren();
    const visible = preview.proposals.slice(0, state.auto.visibleLimit);
    visible.forEach(item => {
      const row = el("tr", item.blocked_reason ? "blocked" : "");
      row.classList.toggle("selected", state.auto.selected.has(item.session_id));
      const checkCell = el("td");
      const check = el("input"); check.type = "checkbox"; check.checked = state.auto.selected.has(item.session_id); check.disabled = Boolean(item.blocked_reason); check.setAttribute("aria-label", t("选择 {title}", {title: item.title}));
      check.addEventListener("change", () => { if (check.checked) state.auto.selected.add(item.session_id); else state.auto.selected.delete(item.session_id); renderAuto(); });
      const hit = el("label", "check-hit"); hit.append(check); checkCell.append(hit); row.append(checkCell);
      const session = state.catalog.sessions.find(value => value.id === item.session_id);
      const titleCell = el("td", "proposal-title"); const title = el("strong", "", compactTitle(item.title)); title.title = item.title;
      titleCell.append(title, el("small", "", t("{id} · 闲置 {days} 天", {id: item.session_id, days: Number(session?.age_days || 0)}))); row.append(titleCell);
      const action = el("td"); action.append(el("span", `action-pill ${item.action}`, actionLabel(item.action))); row.append(action);
      const reasons = item.reasons.filter(reason => reason !== "pin_snapshot_unavailable_or_stale").map(labelFor);
      if (item.blocked_reason) reasons.push(t("阻断：{reason}", {reason: labelFor(item.blocked_reason)}));
      row.append(el("td", "proposal-reason", reasons.join(i18n.locale() === "en" ? ", " : "、") || t("规则命中")), el("td", "", humanBytes(item.size_bytes))); rows.append(row);
    });
    if (!preview.proposals.length) { const row = el("tr"); const cell = el("td", "muted", t("没有候选会话。") ); cell.colSpan = 5; row.append(cell); rows.append(row); }
    $("#autoTableStatus").textContent = t("显示 {shown} / {total}（{eligible} 条可处理）", {shown: visible.length, total: preview.proposals.length, eligible: eligible.length});
    $("#loadMoreAutoBtn").classList.toggle("hidden", visible.length >= preview.proposals.length);
    const selected = preview.proposals.filter(item => state.auto.selected.has(item.session_id) && !item.blocked_reason);
    $("#autoSelectedSummary").textContent = t("{count} 条 · {bytes}", {count: selected.length, bytes: humanBytes(selected.reduce((sum, item) => sum + item.size_bytes, 0))});
    $("#applyAutoPlanBtn").disabled = !selected.length || !preview.planning_allowed;
    $("#autoCount").textContent = String(eligible.length);
  }

  async function loadAutoPreview() {
    $("#autoLoading").classList.remove("hidden");
    try {
      const data = await api("/api/auto-preview", {method: "POST", body: JSON.stringify({preset: "space"})});
      state.auto.preview = data.preview;
      state.auto.selected = new Set(data.preview.proposals.filter(item => item.selected).map(item => item.session_id));
      renderAuto(); renderHome();
    } catch (error) { toast(t("整理建议生成失败：{error}", {error: error.message})); }
    finally { $("#autoLoading").classList.add("hidden"); }
  }

  function setAutoSelection(enabled) {
    if (!state.auto.preview) return;
    state.auto.selected = new Set(enabled ? state.auto.preview.proposals.filter(item => !item.blocked_reason).map(item => item.session_id) : []);
    renderAuto();
  }

  async function applyAutoPlan() {
    if (!state.auto.preview) return;
    const items = state.auto.preview.proposals.filter(item => state.auto.selected.has(item.session_id) && !item.blocked_reason).map(item => ({session_id: item.session_id, action: item.action}));
    try {
      const data = await api("/api/auto-apply", {method: "POST", body: JSON.stringify({preset: "space", items})});
      state.catalog = data.catalog; applyExecutionState(data.execution_state);
      renderAll(); await loadAutoPreview(); switchView("queue");
      toast(t("已加入 {count} 条计划，尚未移动或删除任何会话", {count: data.applied}));
    } catch (error) { toast(labels[error.message] ? labelFor(error.message) : t("批量计划失败：{error}", {error: error.message})); }
  }

  async function clearAutoPlans() {
    try {
      const data = await api("/api/auto-clear", {method: "POST", body: "{}"});
      state.catalog = data.catalog; applyExecutionState(data.execution_state);
      renderAll(); await loadAutoPreview(); toast(t("已清除 {count} 条自动计划", {count: data.removed}));
    } catch (error) { toast(t("清除失败：{error}", {error: error.message})); }
  }

  function renderAll() {
    fillSelect($("#stateFilter"), state.catalog.sessions.map(session => session.actual_state));
    fillSelect($("#recommendationFilter"), state.catalog.sessions.map(session => session.recommendation));
    renderHome(); renderExplorer(); renderQueue(); renderReviewMetrics(); renderAuto();
  }

  async function refreshCatalog() {
    const button = $("#refreshBtn"); button.disabled = true; button.textContent = t("刷新会话中…");
    try {
      const data = await api("/api/refresh", {method: "POST", body: "{}"});
      state.catalog = data.catalog; applyExecutionState(data.execution_state);
      renderAll(); await loadAutoPreview(); toast(t("已刷新本机会话"));
    } catch (error) { toast(t("刷新失败：{error}", {error: error.message})); }
    finally { button.disabled = false; button.textContent = t("刷新会话"); }
  }

  async function chooseColdStorageDirectory() {
    const button = $("#chooseColdStorageBtn");
    const status = $("#coldStorageStatus");
    button.disabled = true;
    button.textContent = t("选择中…");
    status.textContent = t("正在打开系统文件夹选择器…");
    try {
      const data = await api("/api/select-directory", {method: "POST", body: "{}"});
      if (!data.selected) {
        status.textContent = t("已取消选择，原目录未更改。");
        return;
      }
      $("#coldStorageDir").value = data.path;
      $("#coldStorageDir").readOnly = true;
      $("#editColdStorageBtn").textContent = t("手动输入（高级）");
      status.textContent = t("已选择，可用空间 {bytes}。点击“保存设置”后生效。", {bytes: humanBytes(data.free_bytes)});
    } catch (error) {
      status.textContent = "";
      toast(labels[error.message] ? labelFor(error.message) : t("目录选择失败：{error}", {error: error.message}));
    } finally {
      button.disabled = !state.capabilities.native_directory_picker;
      button.textContent = t("选择目录");
    }
  }

  function toggleColdStorageManualInput() {
    const input = $("#coldStorageDir");
    const button = $("#editColdStorageBtn");
    input.readOnly = !input.readOnly;
    button.textContent = input.readOnly ? t("手动输入（高级）") : t("完成输入");
    $("#coldStorageStatus").textContent = input.readOnly
      ? t("手动路径会在保存时校验。")
      : t("请输入已存在且可写的完整目录路径，保存时会立即校验。");
    if (!input.readOnly) input.focus();
  }

  function exportPlan() {
    const plans = state.catalog.sessions.filter(session => session.planned_action).map(session => ({session_id: session.id, title: session.title, actual_state: session.actual_state, planned_action: session.planned_action, size_bytes: session.size_bytes, hard_protected: session.hard_protected}));
    const blob = new Blob([JSON.stringify({schema_version: 1, generated_at: new Date().toISOString(), plans}, null, 2)], {type: "application/json"});
    const link = document.createElement("a"); link.href = URL.createObjectURL(blob); link.download = "codex-session-plan.json"; link.click(); URL.revokeObjectURL(link.href);
  }

  async function initialize() {
    const data = await api("/api/bootstrap");
    state.csrf = data.csrf; state.catalog = data.catalog; state.settings = data.settings; state.capabilities = data.capabilities;
    applyExecutionState(data.execution_state);
    Object.entries(state.settings).forEach(([key, value]) => { const node = $(`[name="${key}"]`); if (node) node.value = value; });
    const picker = $("#chooseColdStorageBtn");
    picker.disabled = !state.capabilities.native_directory_picker;
    if (picker.disabled) {
      picker.title = t("当前系统不支持目录选择器");
      $("#coldStorageDir").readOnly = false;
      $("#editColdStorageBtn").classList.add("hidden");
      $("#coldStorageStatus").textContent = t("当前系统不支持目录选择器，请手动输入完整路径。");
    }
    renderAll(); switchView("home"); await loadAutoPreview();
  }

  registerStaticTranslations();
  translateStatic();
  $$(".tab").forEach(node => node.addEventListener("click", () => switchView(node.dataset.view)));
  $("#languageBtn").addEventListener("click", toggleLanguage);
  $("#refreshBtn").addEventListener("click", refreshCatalog);
  $("#chooseColdStorageBtn").addEventListener("click", chooseColdStorageDirectory);
  $("#editColdStorageBtn").addEventListener("click", toggleColdStorageManualInput);
  $("#openSessionsBtn").addEventListener("click", () => switchView("sessions"));
  $("#openQueueBtn").addEventListener("click", () => switchView("queue"));
  $("#selectAllAutoBtn").addEventListener("click", () => setAutoSelection(true));
  $("#clearSelectionAutoBtn").addEventListener("click", () => setAutoSelection(false));
  $("#applyAutoPlanBtn").addEventListener("click", applyAutoPlan);
  $("#clearAutoPlansBtn").addEventListener("click", clearAutoPlans);
  $("#loadMoreAutoBtn").addEventListener("click", () => { state.auto.visibleLimit += 25; renderAuto(); });
  ["searchInput", "stateFilter", "recommendationFilter", "turnFilter", "riskFilter"].forEach(id => $("#" + id).addEventListener(id === "searchInput" ? "input" : "change", () => {
    if (id === "searchInput") { $("#contentSearchStatus").classList.add("hidden"); state.contentSearch = null; }
    state.explorerVisibleLimit = 50; renderExplorer();
  }));
  $("#searchContentBtn").addEventListener("click", searchArchivedContent);
  $("#loadMoreExplorerBtn").addEventListener("click", () => { state.explorerVisibleLimit += 50; renderExplorer(); });
  $("#prepareReviewBtn").addEventListener("click", prepareReviewBundle);
  $("#closeDrawer").addEventListener("click", closeDrawer);
  $("#drawerScrim").addEventListener("click", closeDrawer);
  $("#closeFinalConfirm").addEventListener("click", closeFinalConfirm);
  $("#cancelFinalConfirm").addEventListener("click", closeFinalConfirm);
  $("#finalConfirmScrim").addEventListener("click", closeFinalConfirm);
  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    if ($("#finalConfirmDialog").classList.contains("open")) closeFinalConfirm();
    else if ($("#drawer").classList.contains("open")) closeDrawer();
  });
  $("#exportPlanBtn").addEventListener("click", exportPlan);
  $("#prepareBtn").addEventListener("click", prepareConfirmationSheet);
  $("#settingsForm").addEventListener("submit", async event => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget));
    try {
      const data = await api("/api/settings", {method: "POST", body: JSON.stringify(payload)});
      state.settings = data.settings; state.catalog = data.catalog; applyExecutionState(data.execution_state);
      $("#coldStorageDir").value = data.settings.cold_storage_dir || "";
      if (state.capabilities.native_directory_picker) {
        $("#coldStorageDir").readOnly = true;
        $("#editColdStorageBtn").textContent = t("手动输入（高级）");
      }
      renderAll(); await loadAutoPreview(); toast(t("设置已保存"));
    } catch (error) { toast(labelFor(error.message)); }
  });

  initialize().catch(error => {
    const main = $("#mainContent"); main.replaceChildren(el("section", "empty-state", t("看板初始化失败：{error}", {error: error.message})));
  });
})();
