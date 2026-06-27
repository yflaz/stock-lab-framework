let STATE = null;
let activeTab = "home";
let accountId = "";
let market = "ALL";
let query = "";
let stockInput = "";
let stockAnalysis = null;
let stockAnalysisError = "";
let stockLoading = false;

const $ = (id) => document.getElementById(id);
const num = (v) => Number(v || 0);
const fmt = (v, d = 2) => num(v).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v) => `${fmt(v)}%`;

function account() {
  return (STATE.accounts || []).find((x) => x.id === accountId) || STATE.account || {};
}

function currency() {
  return account().currency || "CNY";
}

function money(v, c = currency()) {
  const prefix = c === "USD" ? "$" : c === "HKD" ? "HK$" : "¥";
  return `${prefix}${fmt(v)}`;
}

function signClass(v) {
  return num(v) >= 0 ? "gain" : "loss";
}

function tag(text, kind = "") {
  return `<span class="tag ${kind}">${text || ""}</span>`;
}

function list(items) {
  const clean = (items || []).filter(Boolean);
  return clean.length ? `<ul class="list">${clean.map((x) => `<li>${x}</li>`).join("")}</ul>` : "";
}

function card(title, sub, right, body) {
  return `<section class="card"><div class="card-pad"><div class="section-head"><div><div class="section-title">${title}</div>${sub ? `<div class="section-sub">${sub}</div>` : ""}</div>${right || ""}</div>${body || ""}</div></section>`;
}

function rowsFor(key) {
  const text = query.toLowerCase();
  return (STATE[key] || []).filter((x) => {
    const accountOk = !x.account_id || String(x.account_id) === accountId;
    const marketOk = market === "ALL" || x.market === market;
    const textOk = `${x.symbol || ""} ${x.name || ""} ${x.theme || ""}`.toLowerCase().includes(text);
    return accountOk && marketOk && textOk;
  });
}

function setupControls() {
  const accounts = STATE.accounts || [];
  $("mobileAccounts").innerHTML = accounts.map((a) => `<button class="${a.id === accountId ? "active" : ""}" data-account="${a.id}">${a.label || a.id}</button>`).join("");
  $("mobileAccounts").querySelectorAll("button").forEach((btn) => {
    btn.onclick = () => {
      accountId = btn.dataset.account;
      render();
    };
  });

  const markets = [["ALL", "全部"], ["A", "A股"], ["HK", "港股"], ["US", "美股"]];
  $("mobileMarkets").innerHTML = markets.map(([code, label]) => `<button class="${code === market ? "active" : ""}" data-market="${code}">${label}</button>`).join("");
  $("mobileMarkets").querySelectorAll("button").forEach((btn) => {
    btn.onclick = () => {
      market = btn.dataset.market;
      render();
    };
  });

  $("mobileSearch").value = query;
  $("mobileSearch").oninput = (event) => {
    query = event.target.value.trim();
    render();
  };

  $("mobileRefresh").onclick = () => loadState(true);
  $("bottomNav").querySelectorAll("button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === activeTab);
    btn.onclick = () => {
      activeTab = btn.dataset.tab;
      render();
      window.scrollTo({ top: 0, behavior: "smooth" });
    };
  });
}

function kpiGrid(items) {
  return `<div class="kpi-grid">${items.map((x) => `<div class="kpi"><div class="k">${x[0]}</div><div class="v ${x[3] || ""}">${x[1]}</div><div class="n">${x[2] || ""}</div></div>`).join("")}</div>`;
}

function stockCard(p) {
  const monitor = (STATE.position_monitor || []).find((x) => x.symbol === p.symbol && x.account_id === p.account_id) || {};
  return `<details class="stock-card collapsible-card">
    <summary class="collapse-summary">
      <div class="stock-head">
        <div><div class="stock-name">${p.name || p.symbol}</div><div class="stock-code mono">${p.symbol} · ${p.market} · ${p.theme || ""}</div></div>
        <div class="collapse-side">
          <div class="stock-price ${signClass(p.unrealized_pnl)}">${money(p.unrealized_pnl)}<div class="stock-code">${pct(p.unrealized_pnl_pct)}</div></div>
        </div>
      </div>
      <div class="collapse-brief">
        <span>现价 ${money(p.latest_price)}</span>
        <span>止损 ${money(p.stop_loss)}</span>
        <span>目标 ${money(p.target_price)}</span>
      </div>
    </summary>
    <div class="collapse-content">
      <div class="detail-grid">
        <div class="detail"><div class="k">股数</div><div class="v">${p.shares || 0}</div></div>
        <div class="detail"><div class="k">成本</div><div class="v">${money(p.cost_price)}</div></div>
        <div class="detail"><div class="k">现价</div><div class="v">${money(p.latest_price)}</div></div>
        <div class="detail"><div class="k">市值</div><div class="v">${money(p.market_value)}</div></div>
        <div class="detail"><div class="k">止损</div><div class="v">${money(p.stop_loss)}</div></div>
        <div class="detail"><div class="k">目标</div><div class="v">${money(p.target_price)}</div></div>
      </div>
      ${monitor.reason ? `<div class="stock-note">${tag(monitor.status, monitor.severity === "pass" ? "info" : "warn")} ${monitor.reason}</div>` : ""}
    </div>
  </details>`;
}

function orderCard(o, expanded = false) {
  const actionKind = o.committee_action === "direct_follow" ? "good" : o.committee_action === "avoid_for_now" ? "bad" : "warn";
  if (expanded) {
    return `<div class="stock-card">
      <div class="stock-head">
        <div><div class="stock-name">${o.name || o.symbol}</div><div class="stock-code mono">${o.symbol} · ${o.market} · ${o.theme || ""}</div></div>
        <div class="stock-price">${money(o.latest_price)}<div class="${signClass(o.change_pct)}">${pct(o.change_pct)}</div></div>
      </div>
      <div class="stock-note">${tag(o.committee_action, actionKind)} ${o.committee_summary || ""}</div>
      <div class="detail-grid">
        <div class="detail"><div class="k">评分</div><div class="v">${fmt(o.committee_score || o.score, 1)}</div></div>
        <div class="detail"><div class="k">置信</div><div class="v">${o.confidence || ""}</div></div>
        <div class="detail"><div class="k">仓位</div><div class="v">${pct(num(o.target_position_pct) * 100)}</div></div>
        <div class="detail"><div class="k">买入区间</div><div class="v">${money(o.entry_zone?.[0])}<br>${money(o.entry_zone?.[1])}</div></div>
        <div class="detail"><div class="k">止损</div><div class="v">${money(o.stop_loss)}</div></div>
        <div class="detail"><div class="k">目标</div><div class="v">${money(o.target_price)}</div></div>
      </div>
      <div class="stock-note"><strong>入选理由</strong>${list(o.reason)}<strong>风险</strong>${list(o.risks)}</div>
    </div>`;
  }
  return `<details class="stock-card collapsible-card">
    <summary class="collapse-summary">
      <div class="stock-head">
        <div><div class="stock-name">${o.name || o.symbol}</div><div class="stock-code mono">${o.symbol} · ${o.market} · ${o.theme || ""}</div></div>
        <div class="collapse-side">
          ${tag(o.committee_action, actionKind)}
          <div class="stock-price">${money(o.latest_price)}<div class="${signClass(o.change_pct)}">${pct(o.change_pct)}</div></div>
        </div>
      </div>
      <div class="collapse-brief">
        <span>区间 ${money(o.entry_zone?.[0])} - ${money(o.entry_zone?.[1])}</span>
        <span>止损 ${money(o.stop_loss)}</span>
        <span>目标 ${money(o.target_price)}</span>
      </div>
    </summary>
    <div class="collapse-content">
      <div class="stock-note">${o.committee_summary || ""}</div>
      <div class="detail-grid">
        <div class="detail"><div class="k">评分</div><div class="v">${fmt(o.committee_score || o.score, 1)}</div></div>
        <div class="detail"><div class="k">置信</div><div class="v">${o.confidence || ""}</div></div>
        <div class="detail"><div class="k">仓位</div><div class="v">${pct(num(o.target_position_pct) * 100)}</div></div>
        <div class="detail"><div class="k">买入区间</div><div class="v">${money(o.entry_zone?.[0])}<br>${money(o.entry_zone?.[1])}</div></div>
        <div class="detail"><div class="k">止损</div><div class="v">${money(o.stop_loss)}</div></div>
        <div class="detail"><div class="k">目标</div><div class="v">${money(o.target_price)}</div></div>
      </div>
      <div class="stock-note"><strong>入选理由</strong>${list(o.reason)}</div>
      ${o.risks?.length ? `<div class="stock-note"><strong>风险</strong>${list(o.risks)}</div>` : ""}
    </div>
  </details>`;
}

function renderHome() {
  const a = account();
  const analytics = STATE.account_analytics?.[accountId] || {};
  const positions = rowsFor("positions");
  const orders = rowsFor("orders");
  const direct = orders.filter((x) => x.committee_action === "direct_follow");
  const discipline = (STATE.discipline_summary?.queue || []).filter((x) => x.account_id === accountId && x.severity !== "pass");
  return [
    card("账户概览", a.label || "", tag(STATE.meta?.session_phase_label || "", "info"), kpiGrid([
      ["权益", money(a.equity), `收益率 ${pct(analytics.return_pct)}`],
      ["今日", money(analytics.today_pnl), "按持仓最新价", signClass(analytics.today_pnl)],
      ["浮盈亏", money(a.unrealized_pnl), "未实现盈亏", signClass(a.unrealized_pnl)],
      ["机会", `${a.daily_ops_used || 0}/${a.daily_ops_limit || 4}`, "主动交易批次"],
    ])),
    card("今日动作", "先看纪律，再看可跟候选", discipline.length ? tag(`${discipline.length} 个风险`, "warn") : tag("纪律正常", "info"),
      discipline.length
        ? discipline.slice(0, 3).map((x) => `<div class="stock-card"><div class="stock-head"><div><div class="stock-name">${x.name || x.symbol}</div><div class="stock-code">${x.action}</div></div>${tag(x.executed ? "已执行" : "待处理", x.executed ? "good" : "warn")}</div><div class="stock-note">${x.reason}</div></div>`).join("")
        : `<div class="stock-card"><div class="stock-name">${STATE.decision_latest?.summary || "等待下一轮有效决策"}</div>${list(STATE.decision_latest?.planned_focus)}</div>`
    ),
    `<section class="card"><div class="card-pad"><div class="section-head"><div><div class="section-title">当前持仓</div><div class="section-sub">仓位、盈亏、止损和目标</div></div>${tag(`${positions.length} 只`)}</div></div>${positions.length ? positions.map(stockCard).join("") : '<div class="empty">当前账户暂无持仓</div>'}</section>`,
    `<section class="card"><div class="card-pad"><div class="section-head"><div><div class="section-title">可跟候选</div><div class="section-sub">只显示委员会放行的 direct_follow</div></div>${tag(`${direct.length} 个`, direct.length ? "good" : "info")}</div></div>${direct.length ? direct.slice(0, 5).map((x) => orderCard(x)).join("") : '<div class="empty">暂无可直接跟随候选</div>'}</section>`,
  ].join("");
}

function renderPending() {
  const orders = rowsFor("orders");
  const groups = [
    ["direct_follow", "可直接跟", "good"],
    ["watch_pullback", "等回踩", "warn"],
    ["watch_confirm", "等确认", "warn"],
    ["avoid_for_now", "暂回避", "bad"],
    ["observe_only", "仅观察", "info"],
  ];
  return groups.map(([code, title, kind]) => {
    const rows = orders.filter((x) => x.committee_action === code);
    return `<section class="card"><div class="card-pad"><div class="section-head"><div><div class="section-title">${title}</div><div class="section-sub">${triggerText(code)}</div></div>${tag(`${rows.length} 个`, kind)}</div></div>${rows.length ? rows.map((x) => orderCard(x, true)).join("") : '<div class="empty">暂无</div>'}</section>`;
  }).join("");
}

function triggerText(code) {
  return {
    direct_follow: "价格仍在计划区间附近，且现金/机会允许时才执行",
    watch_pullback: "只在回到计划区间且量能不塌时升级",
    watch_confirm: "等待板块、量价或新闻确认",
    avoid_for_now: "风险收益比不划算，先不跟",
    observe_only: "保留样本，不占用交易机会",
  }[code] || "";
}

function barRows(items, valueKey = "pct") {
  const rows = items || [];
  if (!rows.length) return '<div class="empty">暂无暴露数据</div>';
  return `<div class="bar-row">${rows.map((x) => `<div class="bar-line"><span>${x.name}</span><div class="bar-track"><div class="bar-fill" style="width:${Math.max(Math.min(num(x[valueKey]), 100), 1)}%"></div></div><span>${pct(x[valueKey])}</span></div>`).join("")}</div>`;
}

function renderProfit() {
  const analysis = STATE.profit_analysis_by_account?.[accountId] || STATE.profit_analysis || {};
  const summary = STATE.account_analytics?.[accountId] || analysis.summary || {};
  const exposure = summary.exposure || {};
  return [
    card("收益总览", analysis.headline || "", tag(account().label || ""), kpiGrid([
      ["总收益率", pct(summary.return_pct), "权益相对初始资金", signClass(summary.return_pct)],
      ["已实现", money(summary.realized_pnl), "卖出/减仓确认", signClass(summary.realized_pnl)],
      ["未实现", money(summary.unrealized_pnl), "当前持仓浮盈亏", signClass(summary.unrealized_pnl)],
      ["胜率", pct(summary.win_rate), `闭合交易 ${summary.closed_trade_count || 0} 笔`],
    ])),
    card("主题暴露", "看收益是否来自单一主题", "", barRows(exposure.by_theme || [])),
    card("市场暴露", "A/HK/US 账户维度", "", barRows(exposure.by_market || [])),
    `<section class="card"><div class="card-pad"><div class="section-head"><div><div class="section-title">赢家与亏损样本</div><div class="section-sub">复盘时先问贡献来自哪里</div></div></div></div>${renderPnlRows("正贡献", analysis.top_winners, "good")}${renderPnlRows("负贡献", analysis.top_losers, "bad")}</section>`,
    card("复盘问题", "盘后用这些问题拆解收益质量", tag("Review", "info"), list(analysis.questions)),
  ].join("");
}

function renderPnlRows(title, rows, kind) {
  const c = kind === "good" ? "gain" : "loss";
  return `<div class="stock-card"><div class="stock-head"><div class="stock-name">${title}</div>${tag(`${(rows || []).length} 个`, kind)}</div>${(rows || []).length ? rows.map((x) => `<div class="stock-note"><strong>${x.name}</strong> <span class="${c}">${money(x.pnl)} / ${pct(x.pnl_pct)}</span><br>${x.reason}</div>`).join("") : '<div class="stock-note">暂无</div>'}</div>`;
}

function renderThought() {
  const thought = STATE.thought_process || {};
  return [
    card("本轮总判断", thought.headline || "", tag(STATE.decision_latest?.phase_label || ""), list(STATE.decision_latest?.checks)),
    `<section class="card"><div class="card-pad"><div class="section-head"><div><div class="section-title">思考链路</div><div class="section-sub">从数据、纪律、组合、候选到动作</div></div></div><div class="timeline">${(thought.stages || []).map((s) => `<div class="stage"><div class="stage-title"><div><div class="stock-name">${s.name}</div><div class="stock-note">${s.summary || ""}</div></div>${tag(s.status || "", s.status && String(s.status).includes("正常") ? "info" : "warn")}</div>${list(s.details)}</div>`).join("")}</div></div></section>`,
    `<section class="card"><div class="card-pad"><div class="section-head"><div><div class="section-title">候选拆解</div><div class="section-sub">每只票对应多角色审议</div></div></div></div>${(thought.top_reviews || []).filter(rowMatchesLoose).slice(0, 8).map(reviewCard).join("") || '<div class="empty">暂无审议</div>'}</section>`,
    renderLearning(),
  ].join("");
}

function rowMatchesLoose(item) {
  const accountOk = !item.account_id || String(item.account_id) === accountId;
  const marketOk = market === "ALL" || item.market === market;
  const text = `${item.symbol || ""} ${item.name || ""}`.toLowerCase();
  return accountOk && marketOk && text.includes(query.toLowerCase());
}

function reviewCard(r) {
  return `<div class="stock-card">
    <div class="stock-head"><div><div class="stock-name">${r.name || r.symbol}</div><div class="stock-code mono">${r.symbol} · ${r.conviction || ""}</div></div>${tag(r.action || "", r.action === "direct_follow" ? "good" : r.action === "avoid_for_now" ? "bad" : "warn")}</div>
    ${list(r.debate)}
    <div class="agent-grid">${(r.agents || []).filter(Boolean).map((a) => `<div class="agent"><div class="name">${agentName(a)} ${tag(a.verdict || a.action || "", a.verdict === "pass" || a.verdict === "positive" ? "info" : a.verdict === "avoid" ? "bad" : "warn")}</div><div class="text">${a.summary || ""}</div></div>`).join("")}</div>
  </div>`;
}

function agentName(agent) {
  if (!agent) return "";
  if (agent.action) return "组合经理";
  if (String(agent.summary || "").includes("主题")) return "主题研究";
  if (String(agent.summary || "").includes("计划区间")) return "技术分析";
  if (String(agent.summary || "").includes("基本面")) return "基本面";
  if (String(agent.summary || "").includes("纪律")) return "纪律门";
  return "风控";
}

function renderLearning() {
  const learning = STATE.learning_center || {};
  return [
    card("稳定规则", "", tag(`${(learning.stable_rules || []).length} 条`, "info"), list(learning.stable_rules)),
    card("复盘问题", "", tag("Review", "warn"), list(learning.today_review_questions)),
    card("过程记录", "", "", list(learning.process_lessons)),
    `<section class="card"><div class="card-pad"><div class="section-head"><div><div class="section-title">最近记录</div></div>${tag(`${(learning.recent_decisions || []).length} 条`)}</div></div>${(learning.recent_decisions || []).slice(0, 10).map((d) => `<div class="stock-card"><div class="stock-head"><div><div class="stock-name">${d.phase_label || d.phase}</div><div class="stock-code">${d.timestamp || ""}</div></div>${tag(d.date || "")}</div><div class="stock-note">${d.summary || ""}</div></div>`).join("")}</section>`,
  ].join("");
}

function holdingAnalysisCard(p) {
  const monitor = (STATE.position_monitor || []).find((x) => x.symbol === p.symbol && x.account_id === p.account_id) || {};
  return `<details class="stock-card collapsible-card">
    <summary class="collapse-summary">
      <div class="stock-head">
        <div>
          <div class="stock-name">${p.name || p.symbol}</div>
          <div class="stock-code mono">${p.symbol} · ${p.theme || ""} · ${p.market}</div>
        </div>
        <div class="collapse-side">
          ${tag(monitor.status || "持有中", monitor.severity === "pass" ? "info" : "warn")}
          <div class="stock-price ${signClass(p.unrealized_pnl)}">${money(p.unrealized_pnl)}<div class="stock-code">${pct(p.unrealized_pnl_pct)}</div></div>
        </div>
      </div>
      <div class="collapse-brief">
        <span>现价 ${money(p.latest_price)}</span>
        <span>止损 ${money(p.stop_loss)}</span>
        <span>目标 ${money(p.target_price)}</span>
      </div>
    </summary>
    <div class="collapse-content">
      <div class="detail-grid">
        <div class="detail"><div class="k">成本 / 现价</div><div class="v">${money(p.cost_price)}<br>${money(p.latest_price)}</div></div>
        <div class="detail"><div class="k">浮盈亏</div><div class="v ${signClass(p.unrealized_pnl)}">${money(p.unrealized_pnl)}<br>${pct(p.unrealized_pnl_pct)}</div></div>
        <div class="detail"><div class="k">今日波动</div><div class="v ${signClass(p.today_pnl)}">${money(p.today_pnl)}<br>${pct(p.today_pnl_pct)}</div></div>
        <div class="detail"><div class="k">止损</div><div class="v">${money(p.stop_loss)}</div></div>
        <div class="detail"><div class="k">目标</div><div class="v">${money(p.target_price)}</div></div>
        <div class="detail"><div class="k">仓位意图</div><div class="v">${pct(p.target_position_pct || 0)}</div></div>
      </div>
      <div class="stock-note"><strong>持有逻辑</strong>${list(p.holding_thesis)}</div>
      ${monitor.reason ? `<div class="stock-note"><strong>跟踪结论：</strong>${monitor.reason}${list(monitor.bullets)}</div>` : ""}
      ${p.invalidation ? `<div class="stock-note"><strong>失效条件：</strong>${p.invalidation}</div>` : ""}
    </div>
  </details>`;
}

function watchAnalysisCard(o) {
  const review = (STATE.candidate_reviews || []).find((x) => x.symbol === o.symbol && x.account_id === o.account_id) || {};
  const actionKind = o.committee_action === "direct_follow" ? "good" : o.committee_action === "avoid_for_now" ? "bad" : "warn";
  return `<details class="stock-card collapsible-card">
    <summary class="collapse-summary">
      <div class="stock-head">
        <div>
          <div class="stock-name">${o.name || o.symbol}</div>
          <div class="stock-code mono">${o.symbol} · ${o.theme || ""} · ${o.market}</div>
        </div>
        <div class="collapse-side">
          ${tag(o.committee_action || "观察", actionKind)}
          <div class="stock-price ${signClass(o.change_pct)}">${money(o.latest_price)}<div class="stock-code">${pct(o.change_pct)}</div></div>
        </div>
      </div>
      <div class="collapse-brief">
        <span>区间 ${money(o.entry_zone?.[0])} - ${money(o.entry_zone?.[1])}</span>
        <span>止损 ${money(o.stop_loss)}</span>
        <span>目标 ${money(o.target_price)}</span>
      </div>
    </summary>
    <div class="collapse-content">
      <div class="detail-grid">
        <div class="detail"><div class="k">现价 / 涨跌</div><div class="v">${money(o.latest_price)}<br>${pct(o.change_pct)}</div></div>
        <div class="detail"><div class="k">计划区间</div><div class="v">${money(o.entry_zone?.[0])}<br>${money(o.entry_zone?.[1])}</div></div>
        <div class="detail"><div class="k">止损 / 目标</div><div class="v">${money(o.stop_loss)}<br>${money(o.target_price)}</div></div>
        <div class="detail"><div class="k">评分</div><div class="v">${fmt(o.committee_score || o.score, 1)}</div></div>
        <div class="detail"><div class="k">置信 / 仓位</div><div class="v">${o.confidence || ""}<br>${pct(num(o.target_position_pct) * 100)}</div></div>
        <div class="detail"><div class="k">结论</div><div class="v">${o.committee_summary || ""}</div></div>
      </div>
      <div class="stock-note"><strong>判断依据</strong>${list(o.reason)}</div>
      ${o.risks?.length ? `<div class="stock-note"><strong>主要风险：</strong>${list(o.risks)}</div>` : ""}
      ${review.debate?.length ? `<div class="stock-note"><strong>审议摘要：</strong>${list(review.debate.slice(0, 4))}</div>` : ""}
    </div>
  </details>`;
}

function formatAlertValue(item) {
  return `${fmt(item.current, item.unit === "x" ? 2 : 2)}${item.unit || ""}`;
}

function renderAlertRow(item) {
  return `<div class="alert-row">
    <div class="alert-head"><strong>${item.label}</strong>${tag(item.triggered ? "已触发" : "观察中", item.triggered ? "warn" : "info")}</div>
    <div class="alert-meta">当前 ${formatAlertValue(item)} · 阈值 ${fmt(item.threshold, item.unit === "x" ? 2 : 2)}${item.unit || ""}${item.reference_label ? ` · ${item.reference_label} ${item.reference}` : ""}</div>
    <div class="bar-track"><div class="bar-fill ${item.triggered ? "hot" : ""}" style="width:${Math.max(2, item.progress_pct)}%"></div></div>
  </div>`;
}

function renderStockAnalysisResult() {
  if (stockLoading) {
    return '<div class="empty">正在加载…</div>';
  }
  if (stockAnalysisError) {
    return `<div class="empty">${stockAnalysisError}</div>`;
  }
  if (!stockAnalysis) {
    return '<div class="empty">输入 6 位股票代码后查看分析结果。</div>';
  }
  const a = stockAnalysis;
  return `
    <details class="stock-card stock-analysis-shell collapsible-card">
      <summary class="collapse-summary">
        <div class="stock-head">
          <div>
            <div class="stock-name">${a.name} <span class="stock-code mono">${a.symbol}</span></div>
            <div class="stock-code">截至 ${a.as_of || ""}</div>
          </div>
          <div class="collapse-side">
            ${tag(a.status?.text || "状态未知", a.status?.kind || "info")}
            <div class="stock-price ${signClass(a.quote?.change_pct)}">${money(a.quote?.latest)}<div class="stock-code">${pct(a.quote?.change_pct)}</div></div>
          </div>
        </div>
        <div class="collapse-brief">
          <span>3日偏离 ${pct(a.metrics?.deviation_3d_pct)}</span>
          <span>10日偏离 ${pct(a.metrics?.deviation_10d_pct)}</span>
          <span>30日偏离 ${pct(a.metrics?.deviation_30d_pct)}</span>
        </div>
      </summary>
      <div class="collapse-content">
        <div class="stock-note">${a.status?.summary || ""}</div>
        ${kpiGrid([
          ["3日偏离", pct(a.metrics?.deviation_3d_pct), `相对近3日低点`],
          ["10日偏离", pct(a.metrics?.deviation_10d_pct), `相对近10日低点`],
          ["30日偏离", pct(a.metrics?.deviation_30d_pct), `相对近30日低点`],
          ["10天同向", `${a.metrics?.same_direction_10d?.days || 0} 天`, a.metrics?.same_direction_10d?.label || ""],
        ])}
        <div class="detail-grid stock-metric-grid">
          <div class="detail"><div class="k">现价 / 涨跌</div><div class="v">${money(a.quote?.latest)}<br>${pct(a.quote?.change_pct)}</div></div>
          <div class="detail"><div class="k">趋势</div><div class="v">${a.metrics?.trend_label || ""}<br>MA5 ${a.metrics?.ma5 || 0}</div></div>
          <div class="detail"><div class="k">防守 / 硬止损</div><div class="v">${money(a.levels?.support)}<br>${money(a.levels?.hard_stop)}</div></div>
          <div class="detail"><div class="k">阻力 / 止盈</div><div class="v">${money(a.levels?.resistance)}<br>${money(a.levels?.take_profit)}</div></div>
        </div>
        <div class="stock-note"><strong>分析结论</strong>${list(a.analysis)}</div>
        <div class="section-head stock-alert-head"><div><div class="section-title">异动预警</div></div>${tag(`${a.status?.triggered_count || 0}/${a.status?.total_checks || 0} 项`, a.status?.triggered_count >= 2 ? "warn" : "info")}</div>
        ${(a.alerts || []).map(renderAlertRow).join("")}
      </div>
    </details>
  `;
}

function renderStockTab() {
  const positions = rowsFor("positions");
  const watchRows = rowsFor("orders");
  return [
    card("持仓分析", "", tag(`${positions.length} 只`, positions.length ? "info" : "warn"), positions.length ? positions.map(holdingAnalysisCard).join("") : '<div class="empty">当前账户暂无持仓</div>'),
    card("观察股分析", "", tag(`${watchRows.length} 只`, watchRows.length ? "info" : "warn"), watchRows.length ? watchRows.map(watchAnalysisCard).join("") : '<div class="empty">当前筛选条件下没有观察股</div>'),
    card("自定义个股分析", "", "", `
      <div class="analysis-input-row">
        <input id="stockCodeInput" class="mobile-search mono" placeholder="例如 600584" value="${stockInput}" maxlength="6" inputmode="numeric" />
        <button id="analyzeBtn" class="primary-button">开始分析</button>
      </div>
      ${renderStockAnalysisResult()}
    `),
  ].join("");
}

function bindStockActions() {
  const input = $("stockCodeInput");
  const btn = $("analyzeBtn");
  if (!input || !btn) return;
  input.oninput = (event) => {
    stockInput = String(event.target.value || "").replace(/\D/g, "").slice(0, 6);
    event.target.value = stockInput;
  };
  input.onkeydown = (event) => {
    if (event.key === "Enter") requestStockAnalysis();
  };
  btn.onclick = () => requestStockAnalysis();
}

async function requestStockAnalysis() {
  stockInput = String(stockInput || "").replace(/\D/g, "").slice(0, 6);
  if (stockInput.length !== 6) {
    stockAnalysis = null;
    stockAnalysisError = "请输入 6 位 A 股代码。";
    render();
    return;
  }
  stockLoading = true;
  stockAnalysisError = "";
  render();
  try {
    const res = await fetch(`/api/analyze_stock?symbol=${encodeURIComponent(stockInput)}`, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `analyze ${res.status}`);
    stockAnalysis = data;
    stockAnalysisError = "";
  } catch (err) {
    stockAnalysis = null;
    stockAnalysisError = `分析失败：${err.message}`;
  } finally {
    stockLoading = false;
    render();
  }
}

function render() {
  if (!STATE) return;
  setupControls();
  $("mobileMeta").textContent = `${STATE.meta?.session_phase_label || ""} · ${STATE.meta?.generated_at || ""}`;
  const map = { home: renderHome, pending: renderPending, profit: renderProfit, thought: renderThought, stock: renderStockTab };
  $("mobileContent").innerHTML = (map[activeTab] || renderHome)();
  if (activeTab === "stock") bindStockActions();
}

async function loadState(refresh = false) {
  const res = await fetch(`/api/state${refresh ? "?refresh=1" : ""}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`state ${res.status}`);
  STATE = await res.json();
  accountId = accountId || STATE.active_account_id || STATE.accounts?.[0]?.id || "";
  render();
}

loadState(false).catch((err) => {
  $("mobileMeta").textContent = `加载失败：${err.message}`;
});
