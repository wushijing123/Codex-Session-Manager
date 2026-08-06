(() => {
  "use strict";
  if (window.location.protocol === "file:") {
    window.addEventListener("DOMContentLoaded", () => {
      document.title = "请从本地服务打开看板";
      document.body.className = "file-open-guide";
      document.body.innerHTML = `<main><article class="file-open-card"><p class="eyebrow">LOCAL SERVICE REQUIRED</p><h1>这是看板源文件，不是可直接打开的页面</h1><p>为了保护你的 Codex 会话，扫描、正文搜索和计划确认只能通过本机服务运行。请关闭此标签，再从 Codex 中说“打开会话生命周期看板”。</p><p class="muted">不要直接打开 <code>assets/dashboard/index.html</code>。</p><details><summary>需要从终端启动？</summary><code>python3 /Users/wushijing/.agents/skills/wushijing-codex-session-manager/scripts/session_manager.py dashboard --pinned-file "/Users/wushijing/Library/Application Support/Codex Session Manager/pinned-snapshot.json"</code></details></article></main>`;
    }, {once:true});
    return;
  }
  const state = {
    csrf: "", catalog: null, settings: {}, capabilities: {}, dragged: null, selected: null,
    scanCompleted:false, filtersReady:false, confirmationSheet:null, manifests: [], purgeRequests: [], confirmDialog:null, contentSearch:null, auto: { preset:"space", preview:null, selected:new Set() }
  };
  state.auto.visibleLimit=25;
  state.explorerVisibleLimit=50;
  state.lastFocused=null;
  const labels = {
    active:"当前", archived:"普通归档", cold:"冷存档", quarantine:"14 天隔离", unindexed:"未索引",
    missing:"文件缺失", protected:"真正锁定", high_value:"近期有产出", cold_archive:"建议冷存档",
    review_required:"待复核", delete_candidate:"建议14天隔离", permanent_delete_candidate:"建议永久删除", unknown:"未知",
    keep:"保留", archive:"归档", unarchive:"取消归档", restore:"恢复", protect:"永久保护",
    quarantine:"14 天隔离", permanent_delete:"垃圾焚烧厂 · 永久删除", purge_after_quarantine:"垃圾焚烧厂（旧隔离计划）", current_session:"当前活跃", pinned:"已置顶",
    permanent_protection:"永久保护", state_conflict_or_missing:"状态冲突或文件缺失",
    has_parent_or_child:"存在父子依赖", group_action_required:"需整组处理", unindexed_log:"未索引日志", automation:"自动化任务",
    verified_write_work:"检测到实际写入", title_value_hint_needs_review:"标题仅含价值关键词，需复核",
    recent_automation_run:"同一自动化最近运行", old_automation_history:"较早的自动化历史运行",
    inactive_with_value_signal:"超过闲置门槛，但有价值信号", inactive_without_unique_value:"超过闲置门槛，未发现独有价值",
    old_short_temporary:"旧的短临时对话", old_large_session:"旧的大体积会话", insufficient_evidence:"证据不足",
    pin_snapshot_unavailable_or_stale:"置顶快照过期，执行前需刷新", hard_protected:"真正锁定",
    not_plain_archive:"不是普通归档", manual_plan_conflict:"与人工计划冲突",
    planning_gate_closed:"数据库选择未通过，暂不能规划",
    fresh_pin_snapshot_required:"执行前必须刷新置顶快照",
    codex_one_off_review:"Codex判断为一次性对话", recent_one_off_review:"近期一次性对话",
    codex_value_review:"Codex判断有复用价值", codex_review_uncertain:"Codex判断仍需复核",
    inactive_60d_permanent_delete_candidate:"超过60天且符合低风险永久删除条件",
    incinerator_requires_archive_or_quarantine:"旧焚烧计划只接受隔离中的会话",
    incinerator_requires_plain_archive:"垃圾焚烧厂只接受普通归档会话",
    confirmation_sheet_missing_or_expired:"确认单已过期，请重新生成",
    second_confirmation_required:"请在二次确认弹窗中确认本次操作",
    planned_actions_changed_after_review:"确认后计划或风险状态发生变化，请重新生成确认单",
    confirmation_sheet_has_blockers:"当前确认单仍有执行阻塞",
    helper_already_running:"该执行单已有等待中的助手",
    important_warnings_not_acknowledged:"请先勾选重要会话知情确认"
  };
  const lanes = [
    {id:"keep", title:"当前保留", accepts:"keep"},
    {id:"archived", title:"普通归档", accepts:"archive"},
    {id:"cold", title:"冷存档", accepts:"cold_archive"},
    {id:"quarantine", title:"14 天隔离", accepts:"quarantine"},
    {id:"incinerator", title:"垃圾焚烧厂", accepts:"permanent_delete"},
    {id:"protected", title:"永久保护", accepts:"protect"}
  ];
  const $ = (selector) => document.querySelector(selector);
  const $$ = (selector) => [...document.querySelectorAll(selector)];
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const humanBytes = (n) => {
    const units=["B","KiB","MiB","GiB","TiB"]; let i=0,v=Math.max(0,Number(n)||0);
    while(v>=1024&&i<units.length-1){v/=1024;i++}
    return `${i? v.toFixed(1):Math.round(v)} ${units[i]}`;
  };
  const shortDate = (v) => {
    let n=Number(v)||0; if(n<1e12)n*=1000;
    return n ? new Intl.DateTimeFormat("zh-CN",{year:"2-digit",month:"2-digit",day:"2-digit"}).format(new Date(n)) : "—";
  };
  const compactTitle = (value,maxLength=140) => {
    const text=String(value||"(无标题)").replace(/\s+/g," ").trim();
    return text.length>maxLength?`${text.slice(0,maxLength-1)}…`:text;
  };
  const countdown = (seconds) => {
    const value=Math.max(0,Number(seconds)||0);
    const days=Math.floor(value/86400),hours=Math.floor((value%86400)/3600);
    return days?`${days}天 ${hours}小时`:hours?`${hours}小时`:`${Math.max(1,Math.ceil(value/60))}分钟`;
  };
  const incineratorStatus = (session) => {
    if(session.planned_action==="permanent_delete"||(session.planned_action==="purge_after_quarantine"&&session.actual_state==="archived"))return"等待永久删除确认 · 无14天隔离";
    if(session.actual_state!=="quarantine")return"等待进入14天隔离";
    if(session.purge_eligible)return"隔离已到期 · 等待二次确认";
    if(session.quarantine_remaining_seconds!=null)return`隔离倒计时 ${countdown(session.quarantine_remaining_seconds)}`;
    return"隔离时间待校验";
  };
  const toast = (message) => {
    const node=$("#toast"); node.textContent=message; node.classList.add("show");
    clearTimeout(toast.timer); toast.timer=setTimeout(()=>node.classList.remove("show"),3200);
  };
  async function api(path, options={}) {
    const headers={"Content-Type":"application/json",...(options.headers||{})};
    if(options.method==="POST")headers["X-CSRF-Token"]=state.csrf;
    const response=await fetch(path,{...options,headers});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||"request_failed");
    return data;
  }
  function switchView(id) {
    if(!state.scanCompleted&&id!=="scan")return;
    $$(".tab").forEach(n=>n.classList.toggle("active",n.dataset.view===id));
    $$(".tab").forEach(n=>{
      if(n.dataset.view===id)n.setAttribute("aria-current","page");else n.removeAttribute("aria-current");
    });
    $$(".view").forEach(n=>n.classList.toggle("active",n.id===`view-${id}`));
    if(id==="auto"){state.auto.visibleLimit=25;loadAutoPreview(state.auto.preset)}
    if(id==="explorer")renderExplorer();
    if(id==="queue")renderQueue();
    const heading=$(`#view-${id} h1`);
    if(heading){heading.tabIndex=-1;heading.focus({preventScroll:true})}
    window.scrollTo({top:0,behavior:"auto"});
  }
  function metric(label,value,note){
    const card=el("article","metric"); card.append(el("span","label",label),el("strong","",value),el("small","",note)); return card;
  }
  function renderOverview(){
    const c=state.catalog,s=c.summary,grid=$("#metricGrid");
    $("#scanResultSummary").textContent=`扫描完成：${s.total} 条会话，${s.by_state.archived||0} 条普通归档`;
    const deleteCandidateBytes=c.sessions
      .filter(item=>item.actual_state==="archived"&&["delete_candidate","permanent_delete_candidate"].includes(item.recommendation))
      .reduce((total,item)=>total+Number(item.size_bytes||0),0);
    grid.replaceChildren(
      metric("全部会话",String(s.total),`${s.indexed} 条已索引`),
      metric("普通归档",String(s.by_state.archived||0),`${Math.round(100*(s.by_state.archived||0)/Math.max(s.total,1))}% 归档率`),
      metric("未索引日志",String(s.unindexed),s.unindexed?"需要人工复核":"索引一致"),
      metric("日志占用",humanBytes(s.total_bytes),"按真实文件大小"),
      metric("清理候选占用",humanBytes(deleteCandidateBytes),c.pin_snapshot_status==="snapshot"?"永久删除仍需手动确认":"执行前需刷新置顶快照")
    );
    $("#scanMeta").textContent=`扫描于 ${new Date(c.generated_at).toLocaleString()} · ${c.selected_database||"未识别数据库"}`;
    const warning=$("#warningPanel"), issues=[];
    if(c.database_ambiguous)issues.push("候选数据库存在歧义，所有写操作已禁用。");
    if(c.pin_snapshot_status!=="snapshot")issues.push("置顶保护将在最终执行前重新校验；当前可以浏览和整理计划。");
    warning.classList.toggle("hidden",!issues.length); warning.textContent=issues.join(" ");
    const planningAllowed=Boolean(c.selected_database&&!c.database_ambiguous);
    const gate=$("#gateBadge");
    gate.textContent=c.mutation_allowed?"执行校验可用":planningAllowed?"可规划 · 执行待刷新":"只读保护中";
    gate.classList.toggle("ok",c.mutation_allowed);
    const chart=$("#recommendationChart");chart.replaceChildren();
    const recommendationOrder=[
      "cold_archive","high_value","delete_candidate","permanent_delete_candidate",
      "protected","review_required","unknown"
    ];
    const extraRecommendations=Object.keys(s.by_recommendation)
      .filter(key=>!recommendationOrder.includes(key));
    const recommendationEntries=[...recommendationOrder,...extraRecommendations]
      .map(key=>[key,Number(s.by_recommendation[key]||0)]);
    const max=Math.max(1,...recommendationEntries.map(([,value])=>value));
    recommendationEntries.forEach(([key,value])=>{
      const row=el("div","bar-row"),track=el("div","bar-track"),fill=el("div","bar-fill");
      if(key==="permanent_delete_candidate")fill.classList.add("danger");
      fill.style.width=`${100*value/max}%`;track.append(fill);row.append(el("span","",labels[key]||key),track,el("strong","",String(value)));chart.append(row);
    });
    const facts=$("#integrityList");facts.replaceChildren();
    [
      ["数据库候选",String(c.database_candidates.length)],
      ["已选择",c.selected_database||"无"],
      ["数据库歧义",c.database_ambiguous?"有":"无"],
      ["置顶保护",c.pin_snapshot_status==="snapshot"?"已同步":"执行前待同步"],
      ["未索引日志",String(s.unindexed)],
      ["状态冲突",String(s.state_conflicts||0)]
    ].forEach(([k,v])=>{const wrap=el("div");wrap.append(el("dt","",k),el("dd","",v));facts.append(wrap)});
  }
  function effectiveLane(session){
    const action=session.planned_action;
    if(action==="protect"||session.permanent_protection)return"protected";
    if(action==="permanent_delete"||action==="purge_after_quarantine")return"incinerator";
    if(action==="cold_archive")return"cold";
    if(action==="quarantine")return"quarantine";
    if(action==="archive")return"archived";
    if(action==="unarchive"||action==="keep")return"keep";
    if(session.actual_state==="active")return"keep";
    if(session.actual_state==="archived"||session.actual_state==="unindexed"||session.actual_state==="missing")return"archived";
    return session.actual_state;
  }
  function sessionPlanBlocked(session){
    return session.actual_state==="active"||session.pinned||session.permanent_protection||
      session.state_conflict||session.actual_state==="missing"||session.actual_state==="unindexed";
  }
  function cardFor(session){
    const className=`session-card${sessionPlanBlocked(session)?" protected":""}${session.execution_blocker?" grouped":""}`;
    const card=el("article",className);card.tabIndex=0;card.draggable=true;card.dataset.id=session.id;
    card.setAttribute("role","button");
    card.setAttribute("aria-label",`查看会话：${session.title||"(无标题)"}`);
    const cardTitle=el("h3","",compactTitle(session.title));cardTitle.title=session.title||"(无标题)";card.append(cardTitle);
    const meta=el("div","meta");
    meta.append(
      el("span","",["permanent_delete","purge_after_quarantine"].includes(session.planned_action)?incineratorStatus(session):(labels[session.recommendation]||session.recommendation)),
      el("span","",humanBytes(session.size_bytes))
    );
    card.append(meta);
    card.addEventListener("dragstart",()=>{state.dragged=session.id});
    card.addEventListener("click",()=>showDetail(session));
    card.addEventListener("keydown",(event)=>{
      if(event.key==="Enter"){showDetail(session);return}
      if(!event.altKey)return;
      const current=lanes.findIndex(x=>x.id===effectiveLane(session));
      const next=event.key==="ArrowRight"?current+1:event.key==="ArrowLeft"?current-1:-1;
      if(next>=0&&next<lanes.length){event.preventDefault();plan(session.id,lanes[next].accepts)}
    });
    return card;
  }
  function renderBoard(){
    const board=$("#kanban");board.replaceChildren();
    lanes.forEach(lane=>{
      const allSessions=state.catalog.sessions.filter(s=>effectiveLane(s)===lane.id),sessions=allSessions.slice(0,100);
      const column=el("section","lane");column.dataset.action=lane.accepts;
      const head=el("div","lane-head");head.append(el("h2","",lane.title),el("span","",String(allSessions.length)));
      const cards=el("div","cards");sessions.forEach(s=>cards.append(cardFor(s)));column.append(head,cards);
      if(lane.id==="incinerator"){
        (state.catalog.purge_history||[]).slice(0,100).forEach(item=>{
          const tombstone=el("article","session-card tombstone");
          tombstone.append(
            el("h3","","已永久删除 · "+item.session_id.slice(0,8)),
            el("div","meta",`${new Date(item.purged_at).toLocaleString()} · ${humanBytes(item.bytes_purged)}`)
          );
          cards.append(tombstone);
        });
      }
      column.addEventListener("dragover",e=>{e.preventDefault();column.classList.add("dragover")});
      column.addEventListener("dragleave",()=>column.classList.remove("dragover"));
      column.addEventListener("drop",e=>{e.preventDefault();column.classList.remove("dragover");if(state.dragged)plan(state.dragged,lane.accepts)});
      board.append(column);
    });
  }
  async function plan(id,action){
    try{
      const data=await api("/api/plan",{method:"POST",body:JSON.stringify({session_id:id,action})});
      state.catalog=data.catalog;state.confirmationSheet=null;state.manifests=[];renderAll();toast(action?`已加入计划：${labels[action]||action}`:"已取消计划");
    }catch(error){
      const known=labels[error.message];
      toast(known||`计划失败：${error.message}`);
    }
  }
  function fillSelect(node,values){
    const current=node.value;[...new Set(values)].sort().forEach(value=>node.append(new Option(labels[value]||value,value)));node.value=current;
  }
  function filteredSessions(){
    const q=$("#searchInput").value.trim().toLowerCase(),st=$("#stateFilter").value,rec=$("#recommendationFilter").value,risk=$("#riskFilter").value,turn=$("#turnFilter").value;
    const contentSearch=state.contentSearch?.query===q?state.contentSearch:null;
    const candidates=contentSearch?state.catalog.sessions.filter(s=>contentSearch.byId.has(s.id)):state.catalog.sessions;
    return candidates.filter(s=>{
      const hay=`${s.title} ${s.id} ${s.cwd}`.toLowerCase();
      return(contentSearch||!q||hay.includes(q))&&(!st||s.actual_state===st)&&(!rec||s.recommendation===rec)&&
      (!turn||(turn==="one"&&s.business_turns===1)||(turn==="short"&&s.business_turns>=1&&s.business_turns<=3)||(turn==="reviewed"&&s.semantic_review)||(turn==="disposable"&&s.semantic_review?.label==="one_off_disposable"))&&
      (!risk||(risk==="hard"&&sessionPlanBlocked(s))||(risk==="group"&&s.execution_blocker==="group_action_required")||(risk==="conflict"&&s.state_conflict)||(risk==="planned"&&s.planned_action));
    });
  }
  function renderExplorer(){
    const rows=$("#sessionRows");rows.replaceChildren();
    const filtered=filteredSessions();
    const visible=filtered.slice(0,state.explorerVisibleLimit);
    $("#resultCount").textContent=`匹配 ${filtered.length} 条 · 当前显示 ${visible.length} 条`;
    visible.forEach(s=>{
      const tr=el("tr");
      const td=el("td","title-cell"),open=el("button","session-link");
      open.setAttribute("aria-label",`查看会话：${s.title||"(无标题)"}`);
      const openTitle=el("strong","",compactTitle(s.title));openTitle.title=s.title||"(无标题)";
      open.append(openTitle,el("small","",s.id));
      const hit=state.contentSearch?.byId.get(s.id);
      if(hit){
        const first=hit.excerpts?.[0];
        if(first){
          const role=first.role==="user"?"用户":first.role==="assistant"?"Codex": "工具产出";
          open.append(el("small","content-hit",`正文命中（${role}）：${first.excerpt}`));
        }
      }
      open.addEventListener("click",()=>showDetail(s));td.append(open);tr.append(td);
      const actual=el("td");actual.append(el("span",`state-pill${s.state_conflict?" danger":""}`,labels[s.actual_state]||s.actual_state));tr.append(actual);
      const recClass=sessionPlanBlocked(s)?" danger":s.execution_blocker?" warn":s.recommendation==="high_value"?" safe":"";
      const rec=el("td");rec.append(el("span",`state-pill${recClass}`,labels[s.recommendation]||s.recommendation));tr.append(rec);
      tr.append(el("td","",shortDate(s.updated_at)),el("td","",humanBytes(s.size_bytes)));
      const planCell=el("td");
      planCell.append(el("span","",labels[s.planned_action]||s.planned_action||"—"));
      if(hit&&s.actual_state==="archived"){
        const action=s.planned_action==="unarchive"?null:"unarchive";
        const planButton=el("button","secondary content-plan",action?"加入取消归档计划":"取消取消归档计划");
        planButton.addEventListener("click",()=>plan(s.id,action));planCell.append(planButton);
      }
      tr.append(planCell);rows.append(tr);
    });
    $("#explorerTableStatus").textContent=filtered.length?`已显示 ${visible.length} / ${filtered.length} 条匹配会话`:"没有符合条件的会话";
    $("#loadMoreExplorerBtn").classList.toggle("hidden",visible.length>=filtered.length);
  }
  async function searchArchivedContent(){
    const query=$("#searchInput").value.trim();
    if(query.length<2){toast("请输入至少两个字后再搜索归档正文");return}
    const button=$("#searchContentBtn"),status=$("#contentSearchStatus");
    button.disabled=true;button.textContent="正在搜索正文…";status.classList.remove("hidden");status.textContent="正在准备归档正文搜索；不会更改任何会话。";
    try{
      const started=await api("/api/search-archived-content",{method:"POST",body:JSON.stringify({query,limit:100})});
      let data;
      while(true){
        const progress=await api(`/api/search-archived-content/status?job=${encodeURIComponent(started.job_id)}`);
        const total=Math.max(0,Number(progress.total)||0),scanned=Math.min(total,Number(progress.scanned)||0);
        const percent=total?Math.round(scanned*100/total):0;
        status.textContent=`正在搜索归档正文：${scanned} / ${total} 条（${percent}%），已发现 ${Number(progress.matches)||0} 条，耗时 ${Number(progress.elapsed_seconds||0).toFixed(1)} 秒。`;
        if(progress.status==="complete"){data=progress.result;break}
        if(progress.status==="error")throw new Error(progress.error||"content_search_failed");
        await pause(350);
      }
      state.contentSearch={query:query.toLowerCase(),byId:new Map(data.matches.map(item=>[item.session_id,item]))};
      state.explorerVisibleLimit=50;renderExplorer();
      status.textContent=data.matches.length?`正文搜索完成：${data.matches.length} 条归档会话命中。可打开详情查看上下文；“加入取消归档计划”只记录选择，不会立即改变 Codex 侧边栏。`:`未在可读取的归档会话正文中找到“${query}”。`;
    }catch(error){
      state.contentSearch=null;renderExplorer();status.textContent=`正文搜索失败：${labels[error.message]||error.message}`;
    }finally{button.disabled=false;button.textContent="搜索归档正文"}
  }
  function detailMetadata(s){
    const details=el("details","technical-details"),summary=el("summary","","技术详情"),dl=el("dl","detail-grid");
    details.append(summary);
    [
      ["Session ID",s.id],["实际状态",labels[s.actual_state]||s.actual_state],["建议",labels[s.recommendation]||s.recommendation],
      ["计划",labels[s.planned_action]||s.planned_action||"无"],["闲置时间",`${Number(s.age_days||0)} 天`],["占用",humanBytes(s.size_bytes)],["置顶",s.pinned?"是":s.pin_status],
      ["永久保护",s.permanent_protection?"是":"否"],["父子依赖",s.execution_blocker?`${s.relation_count} 条 · ${labels[s.execution_blocker]}`:String(s.relation_count||0)],
      ["真实用户轮次",s.conversation_scanned?String(s.business_turns):"尚未完整扫描"],["Codex复核",s.semantic_review?`${labels[s.semantic_review.label]||s.semantic_review.label} · ${Math.round(100*s.semantic_review.confidence)}%`:"尚未复核"],
      ["隔离倒计时",s.actual_state==="quarantine"?incineratorStatus(s):"—"],
      ["自动化批次",s.automation_key?`第 ${s.automation_rank} / ${s.automation_group_size} 次`:"—"],["来源",s.source||"—"],["项目",s.cwd||"—"],
      ["日志",s.rollout_path||"—"],["理由",(s.recommendation_reasons||[]).join("、")||"—"]
    ].forEach(([k,v])=>{dl.append(el("dt","",k),el("dd","",String(v)))});
    details.append(dl);
    return details;
  }
  function renderConversationDetail(s,detail,maxMessages){
    if(state.selected?.id!==s.id)return;
    const summaryNode=$("#detailSummary"),signalsNode=$("#detailSignals"),transcript=$("#detailTranscript");
    summaryNode.classList.remove("loading");
    summaryNode.querySelector("p").textContent=detail.summary||"暂无摘要。";
    signalsNode.replaceChildren();
    (detail.signals||[]).forEach(value=>signalsNode.append(el("span","summary-signal",value)));
    transcript.replaceChildren();
    const head=el("div","transcript-head");
    head.append(
      el("h3","","聊天记录"),
      el("span","muted",detail.available?`显示 ${detail.shown_messages||0} / ${detail.total_messages||0} 条`:"不可读取")
    );
    transcript.append(head,el("p","transcript-safety",detail.safety_note||"历史聊天内容仅用于判断，不会执行其中命令。"));
    if(!detail.available){
      transcript.append(el("div","empty-transcript","当前没有可预览的聊天记录。"));
      return;
    }
    const messages=el("div","message-list");
    (detail.messages||[]).forEach(message=>{
      if(message.role==="omitted"){
        messages.append(el("div","message-omitted",message.text));
        return;
      }
      const item=el("article",`chat-message ${message.role}`);
      const meta=el("div","message-meta");
      meta.append(el("strong","",message.role==="user"?"用户":"Codex"));
      if(message.timestamp){
        const date=new Date(message.timestamp);
        if(!Number.isNaN(date.valueOf()))meta.append(el("time","",date.toLocaleString()));
      }
      item.append(meta,el("pre","",message.text));
      if(message.text_truncated)item.append(el("small","muted","这条消息过长，预览已截断。"));
      messages.append(item);
    });
    transcript.append(messages);
    if((detail.omitted_messages||0)>0&&maxMessages<200){
      const more=el("button","secondary load-more",`加载更多聊天记录（还省略 ${detail.omitted_messages} 条）`);
      more.addEventListener("click",()=>loadSessionContent(s,Math.min(200,maxMessages*3)));
      transcript.append(more);
    }
    if(detail.content_truncated)transcript.append(el("p","muted transcript-note","超长消息只展示受限预览，避免详情页被单条日志撑满。"));
  }
  async function loadSessionContent(s,maxMessages=24){
    const transcript=$("#detailTranscript");
    if(transcript)transcript.setAttribute("aria-busy","true");
    try{
      const data=await api("/api/session-detail",{method:"POST",body:JSON.stringify({session_id:s.id,max_messages:maxMessages})});
      renderConversationDetail(s,data.detail,maxMessages);
    }catch(error){
      if(state.selected?.id===s.id){
        $("#detailSummary").classList.remove("loading");
        $("#detailSummary").querySelector("p").textContent="摘要读取失败。";
        $("#detailTranscript").replaceChildren(el("div","empty-transcript",`聊天记录读取失败：${error.message}`));
      }
    }finally{
      if(state.selected?.id===s.id&&$("#detailTranscript"))$("#detailTranscript").setAttribute("aria-busy","false");
    }
  }
  function showDetail(s){
    state.lastFocused=document.activeElement;state.selected=s;$("#detailTitle").textContent=s.title||"(无标题)";
    const body=$("#detailBody");
    const summary=el("section","detail-summary loading");summary.id="detailSummary";
    const summaryHead=el("div","summary-head");
    summaryHead.append(el("h3","","快速摘要"),el("span","summary-source","本地规则摘要"));
    summary.append(summaryHead,el("p","","正在读取对应聊天日志…"));
    const signals=el("div","summary-signals");signals.id="detailSignals";summary.append(signals);
    const transcript=el("section","transcript");transcript.id="detailTranscript";transcript.setAttribute("aria-live","polite");
    transcript.append(el("div","empty-transcript","正在加载聊天记录…"));
    const actions=el("div","drawer-actions");
    const protect=el("button","",s.permanent_protection?"解除永久保护":"设为永久保护");
    protect.addEventListener("click",()=>toggleProtect(s.id,!s.permanent_protection));actions.append(protect);
    const clear=el("button","secondary","清除计划");clear.addEventListener("click",()=>plan(s.id,null));actions.append(clear);
    body.replaceChildren(summary,transcript,detailMetadata(s),actions);
    $("#drawer").classList.add("open");$("#drawer").setAttribute("aria-hidden","false");
    $("#drawerScrim").classList.add("open");$("#drawerScrim").setAttribute("aria-hidden","false");
    document.body.classList.add("drawer-open");
    $("#closeDrawer").focus();
    loadSessionContent(s);
  }
  async function toggleProtect(id,enabled){
    try{const data=await api("/api/protect",{method:"POST",body:JSON.stringify({session_id:id,enabled})});state.catalog=data.catalog;state.confirmationSheet=null;state.manifests=[];renderAll();closeDrawer();toast(enabled?"已永久保护":"已解除永久保护")}
    catch(error){toast(`操作失败：${error.message}`)}
  }
  function closeDrawer(){
    $("#drawer").classList.remove("open");$("#drawer").setAttribute("aria-hidden","true");
    $("#drawerScrim").classList.remove("open");$("#drawerScrim").setAttribute("aria-hidden","true");
    document.body.classList.remove("drawer-open");
    const returnTarget=state.lastFocused?.isConnected?state.lastFocused:state.selected&&document.querySelector(`[data-id="${state.selected.id}"]`);
    if(returnTarget?.focus)returnTarget.focus();
  }
  function closeFinalConfirm(){
    const dialog=$("#finalConfirmDialog");dialog.classList.remove("open");dialog.setAttribute("aria-hidden","true");
    const scrim=$("#finalConfirmScrim");scrim.classList.remove("open");scrim.setAttribute("aria-hidden","true");
    const returnTarget=state.confirmDialog?.trigger?.isConnected?state.confirmDialog.trigger:null;
    state.confirmDialog=null;if(returnTarget?.focus)returnTarget.focus();
  }
  function openFinalConfirm({title,body,warning,acknowledgement,confirmLabel,onConfirm,trigger}){
    const dialog=$("#finalConfirmDialog"),scrim=$("#finalConfirmScrim"),warningNode=$("#finalConfirmWarning");
    $("#finalConfirmTitle").textContent=title;$("#finalConfirmBody").textContent=body;
    warningNode.className=warning?"danger-callout":"hidden";warningNode.textContent=warning||"";
    const ackWrap=$("#finalConfirmAcknowledgement"),ack=$("#finalConfirmAck");ack.checked=!acknowledgement;
    ackWrap.classList.toggle("hidden",!acknowledgement);$("#finalConfirmAckText").textContent=acknowledgement||"";
    const commit=$("#commitFinalConfirm");commit.textContent=confirmLabel;commit.disabled=Boolean(acknowledgement);
    const update=()=>{commit.disabled=Boolean(acknowledgement)&&!ack.checked};ack.onchange=update;
    state.confirmDialog={trigger,onConfirm};
    commit.onclick=async()=>{if(commit.disabled||!state.confirmDialog)return;commit.disabled=true;const completed=await state.confirmDialog.onConfirm(ack.checked);if(completed)closeFinalConfirm();else update()};
    dialog.classList.add("open");dialog.setAttribute("aria-hidden","false");scrim.classList.add("open");scrim.setAttribute("aria-hidden","false");
    setTimeout(()=>$("#cancelFinalConfirm").focus(),0);
  }
  function renderQueue(){
    const list=$("#queueList"),plans=state.catalog.sessions.filter(s=>s.planned_action);list.replaceChildren();
    const isNoop=s=>(s.planned_action==="archive"&&s.actual_state==="archived")||(s.planned_action==="unarchive"&&s.actual_state==="active");
    const destructive=s=>["cold_archive","quarantine","permanent_delete","purge_after_quarantine"].includes(s.planned_action);
    const actionable=plans.filter(s=>destructive(s)&&!isNoop(s)&&!s.execution_blocker&&!(s.planned_action==="purge_after_quarantine"&&s.actual_state==="quarantine"));
    plans.forEach(s=>{
      const item=el("article",`queue-item${isNoop(s)?" noop":s.execution_blocker?" blocked":""}`);
      const status=isNoop(s)?"无需执行：状态已经一致":s.execution_blocker?labels[s.execution_blocker]:["permanent_delete","purge_after_quarantine"].includes(s.planned_action)?incineratorStatus(s):labels[s.planned_action]||s.planned_action;
      item.append(el("strong","",s.title||s.id),el("span","",status),el("span","",humanBytes(s.size_bytes)));
      if(s.planned_action==="purge_after_quarantine"&&s.actual_state==="quarantine"&&s.purge_eligible){
        const purge=el("button","","二次确认永久删除");purge.addEventListener("click",()=>requestPurge(s.id));item.append(purge);
      }
      const btn=el("button","secondary","取消计划");btn.addEventListener("click",()=>plan(s.id,null));item.append(btn);list.append(item)
    });
    if(!plans.length)list.append(el("div","panel muted","还没有计划。到生命周期看板拖拽会话，或在详情中设置。"));
    $("#plannedBytes").textContent=humanBytes(actionable.reduce((a,s)=>a+Number(s.size_bytes||0),0));
    $("#planCount").textContent=String(plans.filter(s=>destructive(s)&&!isNoop(s)).length);
    $("#prepareBtn").disabled=!actionable.length;
    const restoreText=state.capabilities.indexed_restore_to_codex?"恢复到 Codex 已通过真实验证。":state.capabilities.reason;
    $("#capabilityNotice").textContent=`拖入“垃圾焚烧厂”代表直接永久删除：不会进入14天隔离，也没有恢复期。点击下一步先生成本次操作确认单；重要会话会被单独标红提醒。${restoreText}`;
    renderConfirmationSheet();
    renderManifests();
  }
  function renderConfirmationSheet(){
    const host=$("#confirmationSheet");host.replaceChildren();
    const sheet=state.confirmationSheet;
    if(!sheet){host.classList.add("hidden");return}
    host.classList.remove("hidden");
    const panel=el("section","confirmation-panel");
    const head=el("div","confirmation-head");
    const title=el("div");title.append(el("p","eyebrow","LOCAL OPERATION RECEIPT"),el("h2","","本次本地操作确认单"));
    head.append(title,el("span","state-pill",sheet.confirmed?"已确认并生成执行单":sheet.can_execute?"等待二次确认":"存在执行阻塞"));
    panel.append(head);
    const metrics=el("div","confirmation-metrics");
    [
      ["冷存档",sheet.counts.cold_archive],
      ["14天隔离",sheet.counts.quarantine],
      ["垃圾焚烧厂",sheet.counts.permanent_delete],
      ["影响空间",humanBytes(sheet.total_bytes)]
    ].forEach(([label,value])=>{const item=el("div");item.append(el("span","",label),el("strong","",String(value)));metrics.append(item)});
    panel.append(metrics);
    if(sheet.counts.permanent_delete){
      panel.append(el("div","danger-callout",`垃圾焚烧厂有 ${sheet.counts.permanent_delete} 条：确认后将直接永久删除，不经过14天隔离，无法恢复。`));
    }
    if(sheet.warnings.length){
      const warning=el("section","receipt-section warning-section");
      warning.append(el("h3","",`发现 ${sheet.warnings.length} 条可能重要的焚烧项`),el("p","muted","这些项目不会替你取消，但必须逐项知情后才能确认。"));
      const rows=el("div","receipt-rows");
      sheet.warnings.forEach(item=>{
        const row=el("article","receipt-row");row.append(el("strong","",item.title),el("span","",item.reasons.join("；")),el("small","",humanBytes(item.size_bytes)));rows.append(row);
      });
      warning.append(rows);panel.append(warning);
    }
    if(sheet.blockers.length){
      const blocked=el("section","receipt-section blocker-section");
      blocked.append(el("h3","",`当前有 ${sheet.blockers.length} 个执行阻塞`));
      const list=el("ul");sheet.blockers.forEach(item=>list.append(el("li","",item.message||labels[item.code]||item.code)));blocked.append(list);panel.append(blocked);
    }
    const confirm=el("section","local-confirm");
    confirm.append(el("p","",sheet.confirmed?"本次确认已完成，已生成不可变本地执行单。":"下一步会弹出二次确认；确认前不会创建执行单，也不会移动或删除会话。"));
    const button=el("button","",sheet.confirmed?"已生成本地执行单":"下一步：二次确认");
    button.disabled=sheet.confirmed||!sheet.can_execute;
    button.addEventListener("click",()=>openFinalConfirm({
      title:sheet.counts.permanent_delete?"确认生成永久删除执行单？":"确认生成本地执行单？",
      body:`本次将生成 ${sheet.total_count} 条会话的不可变执行单。真正执行时仍会等待 Codex 完全退出。`,
      warning:sheet.counts.permanent_delete?`垃圾焚烧厂包含 ${sheet.counts.permanent_delete} 条。执行后将直接永久删除，无法恢复。`:"",
      acknowledgement:sheet.warnings.length?"我已逐项检查上述可能重要的焚烧会话，仍确认继续":"",
      confirmLabel:"确认并生成执行单",trigger:button,
      onConfirm:(acknowledged)=>confirmOperationSheet(sheet,acknowledged)
    }));
    confirm.append(button);panel.append(confirm);host.append(panel);
  }
  function renderManifests(){
    const list=$("#manifestList");list.replaceChildren();
    state.manifests.forEach(m=>{
      const item=el("article","manifest-item");
      item.append(el("strong","",`${labels[m.action]||m.action} · ${m.session_ids.length} 条 · ${humanBytes(m.bytes)}`));
      const launch=el("button","","退出 Codex 并开始执行");
      launch.addEventListener("click",()=>launchAndQuitHelper(m,m.confirmation_phrase));
      item.append(launch);
      const note=el("small","muted",m.action==="permanent_delete"?"直接永久删除，不生成14天恢复包；失败时使用临时副本与数据库备份回滚。":(m.volume_notes||[]).includes("same_volume_no_system_disk_reclaim")?"目标与原日志同盘：不会释放系统盘空间。":"执行助手会等待 Codex 完全退出。");
      item.append(note);list.append(item);
    });
    state.purgeRequests.forEach(request=>{
      const item=el("article","manifest-item purge-confirm");
      item.append(el("strong","",`垃圾焚烧厂 · ${request.session_id}`));
      const launch=el("button","","下一步：永久删除确认");launch.addEventListener("click",()=>openFinalConfirm({
        title:"确认永久删除隔离包？",body:"此操作会清除已到期的隔离包，只保留脱敏审计记录。",
        warning:"这条会话已经过隔离期；本次确认后无法恢复。",confirmLabel:"确认永久删除",trigger:launch,
        onConfirm:()=>launchPurge(request)
      }));
      item.append(launch,el("small","muted","这一步会清除隔离包，只保留脱敏审计墓碑。"));list.append(item);
    });
  }
  async function requestPurge(sessionId){
    try{
      const data=await api("/api/purge-request",{method:"POST",body:JSON.stringify({session_id:sessionId})});
      state.purgeRequests=[...state.purgeRequests.filter(item=>item.session_id!==sessionId),data.request];
      renderManifests();toast("已生成第二次永久删除确认");
    }catch(error){toast(`无法准备永久删除：${labels[error.message]||error.message}`)}
  }
  async function launchPurge(request){
    try{
      const data=await api("/api/launch-purge",{method:"POST",body:JSON.stringify({session_id:request.session_id,second_confirmation:true})});
      toast(`永久删除助手已启动，PID ${data.helper.pid}`);return true;
    }catch(error){toast(`永久删除未启动：${labels[error.message]||error.message}`);return false}
  }
  async function prepareConfirmationSheet(){
    try{
      const data=await api("/api/confirmation-sheet",{method:"POST",body:"{}"});
      state.confirmationSheet=data.sheet;state.manifests=[];renderQueue();
      $("#confirmationSheet").scrollIntoView({behavior:"smooth",block:"start"});
      toast("已生成本次本地操作确认单");
    }catch(error){toast(`确认单生成失败：${labels[error.message]||error.message}`)}
  }
  async function confirmOperationSheet(sheet,warningsAcknowledged){
    try{
      const data=await api("/api/confirm-sheet",{method:"POST",body:JSON.stringify({sheet_id:sheet.sheet_id,warnings_acknowledged:warningsAcknowledged,second_confirmation:true})});
      sheet.confirmed=true;state.manifests=data.manifests;renderQueue();
      $("#manifestList").scrollIntoView({behavior:"smooth",block:"start"});
      toast(`已生成 ${state.manifests.length} 个不可变本地执行单`);return true;
    }catch(error){toast(`二次确认未通过：${labels[error.message]||error.message}`);return false}
  }
  async function launchHelper(manifest,confirmation){
    try{
      const data=await api("/api/launch-helper",{method:"POST",body:JSON.stringify({manifest:manifest.path,confirmation})});
      toast(`助手已启动，PID ${data.helper.pid}；请完全退出 Codex`);
    }catch(error){toast(`助手未启动：${error.message}`)}
  }
  async function quitCodexDesktop(){
    try{await api("/api/quit-codex",{method:"POST",body:"{}"})}
    catch(error){toast(`无法请求退出 Codex：${error.message}`)}
  }
  async function launchAndQuitHelper(manifest,confirmation){
    try{await api("/api/launch-and-quit",{method:"POST",body:JSON.stringify({manifest:manifest.path,confirmation})})}
    catch(error){toast(`无法开始执行：${labels[error.message]||error.message}`)}
  }
  function autoMetric(label,value,note){return metric(label,String(value),note)}
  function renderReviewMetrics(){
    const summary=state.catalog.summary,node=$("#reviewMetrics");node.replaceChildren();
    [
      ["已完整扫描",summary.conversation_scanned||0],
      ["3轮以内",summary.short_conversations||0],
      ["Codex已复核",summary.codex_reviewed||0],
      ["一次性对话",summary.codex_one_off||0]
    ].forEach(([label,value])=>node.append(el("span","",`${label} ${value}`)));
  }
  async function prepareReviewBundle(){
    const button=$("#prepareReviewBtn");button.disabled=true;button.textContent="正在扫描真实轮次…";
    try{
      const data=await api("/api/review-bundle",{method:"POST",body:JSON.stringify({max_turns:Number($("#reviewMaxTurns").value)})});
      state.catalog=data.catalog;renderAll();
      const notice=$("#reviewBundleNotice");notice.classList.remove("hidden");notice.replaceChildren(
        el("strong","",`发现 ${data.summary.short_conversations} 条短对话，其中 ${data.summary.clean_one_off_candidates} 条没有写入或附件。`),
        el("code","",data.bundle_path),
        el("span","","回到 Codex 输入“复核一次性对话”，Codex会读取这个最小化复核包并写回判断。")
      );
    }catch(error){toast(`短对话扫描失败：${error.message}`)}
    finally{button.disabled=false;button.textContent="扫描并准备Codex复核包"}
  }
  function renderAuto(){
    const preview=state.auto.preview;
    if(!preview)return;
    const summary=preview.summary;
    const archivedBreakdown=summary.archived_by_recommendation||{};
    const policy=state.catalog.classification_policy||{};
    const eligible=preview.proposals.length-summary.blocked;
    const strategyRate=100*summary.strategy_candidates/Math.max(summary.archived_total,1);
    const strategyRateText=summary.strategy_candidates>0&&strategyRate<1?"<1%":`${Math.round(strategyRate)}%`;
    $("#autoMetricGrid").replaceChildren(
      autoMetric("全部普通归档",summary.archived_total,"已完整扫描并归类"),
      autoMetric("当前策略命中",summary.strategy_candidates,`占全部归档的 ${strategyRateText}`),
      autoMetric("可加入计划",eligible,"只写 planned_action"),
      autoMetric("暂不自动处理",summary.outside_strategy,"仍可在全部归档中查看"),
      autoMetric("本策略空间",humanBytes(summary.candidate_bytes),"候选会话当前占用")
    );
    const breakdown=$("#archivedBreakdown");breakdown.replaceChildren();
    [
      ["protected","真正锁定"],["high_value","近期有产出"],["review_required","待复核"],
      ["cold_archive","建议冷存档"],["delete_candidate","建议14天隔离"],
      ["permanent_delete_candidate","建议永久删除"]
    ].forEach(([key,label])=>{
      const item=el("div","breakdown-item");item.append(el("span","",label),el("strong","",String(archivedBreakdown[key]||0)));breakdown.append(item);
    });
    $("#viewAllArchivedBtn").textContent=`查看全部 ${summary.archived_total} 条归档`;
    $("#autoCount").textContent=String(summary.strategy_candidates);
    $("#autoSummary").textContent=`闲置门槛 ${policy.cleanup_age_days||30} 天；超过 ${policy.permanent_delete_age_days||60} 天的低风险项会标为“建议永久删除”，但不会自动加入删除计划。每个自动化至少保留最近 ${policy.automation_keep_runs||3} 次，并保留 7 天内运行。当前策略显示 ${summary.strategy_candidates} / ${summary.archived_total} 条归档。`;
    $$(".preset").forEach(node=>node.classList.toggle("active",node.dataset.preset===state.auto.preset));
    const gate=$("#autoGateNotice");
    gate.classList.toggle("hidden",preview.execution_ready);
    gate.textContent=preview.planning_allowed
      ?"置顶快照已过期：现在仍可生成和调整计划，但生成执行 manifest 前必须重新获取置顶列表。"
      :"数据库选择存在歧义：可以查看全部归档，但暂不能生成计划。";
    const rows=$("#autoProposalRows");rows.replaceChildren();
    const visibleProposals=preview.proposals.slice(0,state.auto.visibleLimit);
    visibleProposals.forEach(item=>{
      const tr=el("tr",item.blocked_reason?"blocked":"");
      tr.classList.toggle("selected",state.auto.selected.has(item.session_id));
      const checkCell=el("td"),check=el("input");
      check.type="checkbox";check.checked=state.auto.selected.has(item.session_id);
      check.disabled=Boolean(item.blocked_reason);check.setAttribute("aria-label",`选择 ${item.title}`);
      check.addEventListener("change",()=>{
        if(check.checked)state.auto.selected.add(item.session_id);else state.auto.selected.delete(item.session_id);
        renderAuto();
      });
      const checkHit=el("label","check-hit");checkHit.append(check);checkCell.append(checkHit);tr.append(checkCell);
      const session=state.catalog.sessions.find(value=>value.id===item.session_id);
      const title=el("td","proposal-title"),titleText=el("strong","",compactTitle(item.title));titleText.title=item.title;
      title.append(titleText,el("small","",`${item.session_id} · 闲置 ${Number(session?.age_days||0)} 天`));tr.append(title);
      const action=el("td");action.append(el("span",`action-pill ${item.action}`,labels[item.action]||item.action));tr.append(action);
      const reasons=item.reasons
        .filter(reason=>reason!=="pin_snapshot_unavailable_or_stale")
        .map(reason=>labels[reason]||reason);
      if(item.blocked_reason)reasons.push(`阻断：${labels[item.blocked_reason]||item.blocked_reason}`);
      else if(item.execution_warning)reasons.push(labels[item.execution_warning]||item.execution_warning);
      tr.append(el("td","proposal-reason",reasons.join("、")||"确定性规则命中"),el("td","",humanBytes(item.size_bytes)));rows.append(tr);
    });
    if(!preview.proposals.length){
      const tr=el("tr"),td=el("td","muted","当前策略没有发现可自动处理的会话。");
      td.colSpan=5;tr.append(td);rows.append(tr);
    }
    $("#autoTableStatus").textContent=preview.proposals.length
      ?`已显示 ${visibleProposals.length} / ${preview.proposals.length} 条候选`
      :"当前策略没有候选";
    $("#loadMoreAutoBtn").classList.toggle("hidden",visibleProposals.length>=preview.proposals.length);
    const selected=preview.proposals.filter(item=>state.auto.selected.has(item.session_id)&&!item.blocked_reason);
    $("#autoSelectedSummary").textContent=`${selected.length} 条 · ${humanBytes(selected.reduce((sum,item)=>sum+item.size_bytes,0))}`;
    $("#applyAutoPlanBtn").disabled=!selected.length||!preview.planning_allowed;
  }
  async function loadAutoPreview(preset){
    state.auto.preset=preset;
    state.auto.visibleLimit=25;
    $("#autoLoading").classList.remove("hidden");
    $$(".preset").forEach(node=>node.disabled=true);
    try{
      const data=await api("/api/auto-preview",{method:"POST",body:JSON.stringify({preset})});
      state.auto.preview=data.preview;
      state.auto.selected=new Set(data.preview.proposals.filter(item=>item.selected).map(item=>item.session_id));
      renderAuto();
    }catch(error){toast(`自动分析失败：${error.message}`)}
    finally{
      $("#autoLoading").classList.add("hidden");
      $$(".preset").forEach(node=>node.disabled=false);
    }
  }
  function setAutoSelection(enabled){
    if(!state.auto.preview)return;
    state.auto.selected=new Set(enabled?state.auto.preview.proposals.filter(item=>!item.blocked_reason).map(item=>item.session_id):[]);
    renderAuto();
  }
  async function applyAutoPlan(){
    if(!state.auto.preview)return;
    const items=state.auto.preview.proposals
      .filter(item=>state.auto.selected.has(item.session_id)&&!item.blocked_reason)
      .map(item=>({session_id:item.session_id,action:item.action}));
    try{
      const data=await api("/api/auto-apply",{method:"POST",body:JSON.stringify({preset:state.auto.preset,items})});
      state.catalog=data.catalog;state.confirmationSheet=null;state.manifests=[];renderAll();await loadAutoPreview(state.auto.preset);
      switchView("queue");toast(`已批量加入 ${data.applied} 条计划，尚未移动或删除任何会话`);
    }catch(error){toast(labels[error.message]||`批量计划失败：${error.message}`)}
  }
  async function clearAutoPlans(){
    try{
      const data=await api("/api/auto-clear",{method:"POST",body:"{}"});
      state.catalog=data.catalog;state.confirmationSheet=null;state.manifests=[];renderAll();await loadAutoPreview(state.auto.preset);
      toast(`已清除 ${data.removed} 条自动计划，人工计划未受影响`);
    }catch(error){toast(`清除失败：${error.message}`)}
  }
  function renderAll(){
    renderOverview();renderBoard();renderExplorer();renderQueue();renderReviewMetrics();
    const recommendations=state.catalog.summary.by_recommendation;
    $("#autoCount").textContent=String((recommendations.cold_archive||0)+(recommendations.delete_candidate||0)+(recommendations.permanent_delete_candidate||0));
  }
  const scanPhases = [
    {id:"database",progress:18,text:"正在识别真实数据库…"},
    {id:"logs",progress:42,text:"正在匹配当前与归档日志…"},
    {id:"protection",progress:68,text:"正在核对保护与父子关系…"},
    {id:"classification",progress:88,text:"正在生成分类和整理建议…"}
  ];
  const pause = (milliseconds) => new Promise(resolve=>setTimeout(resolve,milliseconds));
  function updateScanProgress(index,progress,text){
    $("#scanProgressBar").style.width=`${progress}%`;
    $("#scanProgressValue").textContent=`${progress}%`;
    $("#scanProgressText").textContent=text;
    $("#scanProgress").setAttribute("aria-valuenow",String(progress));
    $$(".scan-steps li").forEach((node,nodeIndex)=>{
      node.classList.toggle("active",nodeIndex===index);
      node.classList.toggle("done",nodeIndex<index||progress===100);
    });
  }
  async function startScan(){
    const button=$("#startScanBtn");
    button.disabled=true;button.textContent="正在扫描…";
    $("#scanProgress").classList.remove("hidden");$("#scanError").classList.add("hidden");
    state.scanCompleted=false;switchView("scan");
    const request=api("/api/refresh",{method:"POST",body:"{}"})
      .then(data=>({data}),error=>({error}));
    try{
      for(let index=0;index<scanPhases.length;index+=1){
        const phase=scanPhases[index];updateScanProgress(index,phase.progress,phase.text);
        await pause(420);
      }
      const result=await request;
      if(result.error)throw result.error;
      state.catalog=result.data.catalog;state.confirmationSheet=null;state.manifests=[];
      if(!state.filtersReady){
        fillSelect($("#stateFilter"),state.catalog.sessions.map(s=>s.actual_state));
        fillSelect($("#recommendationFilter"),state.catalog.sessions.map(s=>s.recommendation));
        state.filtersReady=true;
      }
      renderAll();
      updateScanProgress(scanPhases.length-1,100,"扫描完成，分类和建议已经生成");
      await pause(450);
      state.scanCompleted=true;
      $("#mainTabs").classList.remove("hidden");$("#dashboardToolbar").classList.remove("hidden");
      button.disabled=false;button.textContent="重新扫描本地 Codex 会话";
      switchView("overview");
    }catch(error){
      $("#scanProgressText").textContent="扫描未完成";
      $("#scanError").textContent=`扫描失败：${error.message}`;
      $("#scanError").classList.remove("hidden");
      button.disabled=false;button.textContent="重新扫描";
    }
  }
  function exportPlan(){
    const plans=state.catalog.sessions.filter(s=>s.planned_action).map(s=>({session_id:s.id,title:s.title,actual_state:s.actual_state,planned_action:s.planned_action,size_bytes:s.size_bytes,hard_protected:s.hard_protected}));
    const blob=new Blob([JSON.stringify({schema_version:1,generated_at:new Date().toISOString(),plans},null,2)],{type:"application/json"});
    const link=document.createElement("a");link.href=URL.createObjectURL(blob);link.download="codex-session-plan.json";link.click();URL.revokeObjectURL(link.href);
  }
  async function initialize(){
    const data=await api("/api/bootstrap");state.csrf=data.csrf;state.catalog=data.catalog;state.settings=data.settings;state.capabilities=data.capabilities;
    Object.entries(state.settings).forEach(([k,v])=>{const n=$(`[name="${k}"]`);if(n)n.value=v});
  }
  $$(".tab").forEach(n=>n.addEventListener("click",()=>switchView(n.dataset.view)));
  $$(".preset").forEach(n=>n.addEventListener("click",()=>loadAutoPreview(n.dataset.preset)));
  $("#viewAllArchivedBtn").addEventListener("click",()=>{
    $("#searchInput").value="";$("#stateFilter").value="archived";$("#recommendationFilter").value="";$("#riskFilter").value="";
    switchView("explorer");
  });
  $("#selectAllAutoBtn").addEventListener("click",()=>setAutoSelection(true));
  $("#clearSelectionAutoBtn").addEventListener("click",()=>setAutoSelection(false));
  $("#applyAutoPlanBtn").addEventListener("click",applyAutoPlan);
  $("#clearAutoPlansBtn").addEventListener("click",clearAutoPlans);
  $("#loadMoreAutoBtn").addEventListener("click",()=>{state.auto.visibleLimit+=25;renderAuto()});
  $("#startScanBtn").addEventListener("click",startScan);
  $("#refreshBtn").addEventListener("click",()=>{switchView("scan");startScan()});
  $("#openAutoBtn").addEventListener("click",()=>switchView("auto"));
  $("#openExplorerBtn").addEventListener("click",()=>switchView("explorer"));
  ["searchInput","stateFilter","recommendationFilter","turnFilter","riskFilter"].forEach(id=>$("#"+id).addEventListener(id==="searchInput"?"input":"change",()=>{
    if(id==="searchInput"){$("#contentSearchStatus").classList.add("hidden");state.contentSearch=null}
    state.explorerVisibleLimit=50;renderExplorer();
  }));
  $("#searchContentBtn").addEventListener("click",searchArchivedContent);
  $("#loadMoreExplorerBtn").addEventListener("click",()=>{state.explorerVisibleLimit+=50;renderExplorer()});
  $("#prepareReviewBtn").addEventListener("click",prepareReviewBundle);
  $("#closeDrawer").addEventListener("click",closeDrawer);
  $("#drawerScrim").addEventListener("click",closeDrawer);
  $("#closeFinalConfirm").addEventListener("click",closeFinalConfirm);
  $("#cancelFinalConfirm").addEventListener("click",closeFinalConfirm);
  $("#finalConfirmScrim").addEventListener("click",closeFinalConfirm);
  document.addEventListener("keydown",event=>{if(event.key!=="Escape")return;if($("#finalConfirmDialog").classList.contains("open")){closeFinalConfirm();return}if($("#drawer").classList.contains("open"))closeDrawer()});
  $("#exportPlanBtn").addEventListener("click",exportPlan);
  $("#prepareBtn").addEventListener("click",prepareConfirmationSheet);
  $("#settingsForm").addEventListener("submit",async e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(e.currentTarget));try{const d=await api("/api/settings",{method:"POST",body:JSON.stringify(payload)});state.settings=d.settings;state.catalog=d.catalog;state.confirmationSheet=null;state.manifests=[];renderAll();await loadAutoPreview(state.auto.preset);toast("设置已保存并重新分类")}catch(err){toast(err.message)}});
  initialize().catch(error=>{document.body.textContent=`看板初始化失败：${error.message}`});
})();
