let STATE = null;
let selectedAccount = "";
let selectedMarket = "ALL";
let searchText = "";

const $ = (id) => document.getElementById(id);
const n = (v) => Number(v || 0);
const fmt = (v, digits = 2) => n(v).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pct = (v) => `${fmt(v)}%`;

function money(v, currency = "CNY") {
  const prefix = currency === "USD" ? "$" : currency === "HKD" ? "HK$" : "¥";
  return `${prefix}${fmt(v)}`;
}

function clsByValue(v) {
  return n(v) >= 0 ? "gain" : "loss";
}

function tag(text, kind = "") {
  return `<span class="tag ${kind}">${text}</span>`;
}

function list(items) {
  const clean = (items || []).filter(Boolean);
  if (!clean.length) return "";
  return `<ul class="bullet-list">${clean.map((x) => `<li>${x}</li>`).join("")}</ul>`;
}

function panel(id, title, sub, right, body) {
  $(id).innerHTML = `
    <div class="panel-head">
      <div><div class="panel-title">${title}</div>${sub ? `<div class="panel-sub">${sub}</div>` : ""}</div>
      ${right || ""}
    </div>
    <div class="panel-body">${body || '<div class="empty"></div>'}</div>`;
}

async function loadState(refresh = false) {
  const res = await fetch(`/api/state${refresh ? "?refresh=1" : ""}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`state ${res.status}`);
  STATE = await res.json();
  selectedAccount = selectedAccount || STATE.active_account_id || (STATE.accounts?.[0]?.id || "");
  render();
}

function currentAccount() {
  return (STATE.accounts || []).find((x) => x.id === selectedAccount) || STATE.account || {};
}

function rowMatches(item) {
  const marketOk = selectedMarket === "ALL" || item.market === selectedMarket;
  const text = `${item.symbol || ""} ${item.name || ""} ${item.theme || ""}`.toLowerCase();
  return marketOk && text.includes(searchText.toLowerCase());
}

function accountItems(listName) {
  return (STATE[listName] || []).filter((x) => String(x.account_id || "") === selectedAccount).filter(rowMatches);
}

function setupControls() {
  const select = $("accountSelect");
  select.innerHTML = (STATE.accounts || []).map((a) => `<option value="${a.id}">${a.label || a.id}</option>`).join("");
  select.value = selectedAccount;
  select.onchange = () => {
    selectedAccount = select.value;
    render();
  };
  $("marketSelect").value = selectedMarket;
  $("marketSelect").onchange = (e) => {
    selectedMarket = e.target.value;
    render();
  };
  $("searchInput").value = searchText;
  $("searchInput").oninput = (e) => {
    searchText = e.target.value.trim();
    render();
  };
  $("refreshBtn").onclick = () => loadState(true);
}

function renderMeta() {
  const meta = STATE.meta || {};
  $("metaLine").textContent = `${meta.session_phase_label || ""} · ${meta.generated_at || ""} · ${meta.mode || ""}`;
}

function renderMetrics() {
  const a = currentAccount();
  const summary = STATE.portfolio_summary || {};
  const items = [
    ["账户权益", money(a.equity, a.currency), "现金 + 持仓市值"],
    ["可用现金", money(a.cash, a.currency), `现金占比 ${pct(summary.cash_pct)}`],
    ["持仓市值", money(a.market_value, a.currency), `投入占比 ${pct(summary.invested_pct)}`],
    ["浮动盈亏", money(a.unrealized_pnl, a.currency), "未实现盈亏", clsByValue(a.unrealized_pnl)],
    ["今日机会", `${a.daily_ops_used || 0}/${a.daily_ops_limit || 4}`, "主动买入批次"],
  ];
  $("metrics").innerHTML = items.map(([k, v, note, klass]) => `
    <div class="metric">
      <div class="metric-k">${k}</div>
      <div class="metric-v ${klass || ""}">${v}</div>
      <div class="metric-note">${note}</div>
    </div>`).join("");
}

function renderDiscipline() {
  const queue = (STATE.discipline_summary?.queue || []).filter((x) => String(x.account_id || "") === selectedAccount).filter(rowMatches);
  const important = queue.filter((x) => x.severity !== "pass");
  const rows = important.length ? important : queue.slice(0, 5);
  const body = rows.map((x) => `
    <div class="row-card">
      <div class="row-card-head">
        <div>
          <div class="row-title">${x.name || x.symbol}</div>
          <div class="stock-meta mono">${x.symbol || ""} · ${x.market || ""}</div>
        </div>
        ${tag(x.executed ? "已执行" : x.action, x.severity === "critical" ? "bad" : x.severity === "important" ? "good" : x.severity === "warning" ? "warn" : "info")}
      </div>
      <div class="row-text">${x.reason || ""}</div>
      ${list(x.checks)}
    </div>`).join("");
  panel(
    "disciplinePanel",
    "纪律队列",
    "止损、止盈、移动止盈和集中度先于新增买入",
    tag(`${important.length} 个需处理`, important.length ? "warn" : "info"),
    body,
  );
}

function renderPositions() {
  const a = currentAccount();
  const rows = accountItems("positions");
  const html = rows.length ? `
    <div class="table-wrap">
      <table>
        <thead><tr><th>股票</th><th>主题</th><th class="num">股数</th><th class="num">成本/现价</th><th class="num">市值</th><th class="num">浮盈亏</th><th class="num">止损/目标</th><th>纪律</th></tr></thead>
        <tbody>
          ${rows.map((p) => {
            const monitor = (STATE.position_monitor || []).find((x) => x.symbol === p.symbol && x.account_id === p.account_id) || {};
            return `<tr>
              <td><div class="stock-name">${p.name || p.symbol}</div><div class="stock-meta mono">${p.symbol} · ${p.market}</div></td>
              <td>${p.theme || ""}</td>
              <td class="num">${p.shares || 0}</td>
              <td class="num">${money(p.cost_price, a.currency)}<br><span class="muted">${money(p.latest_price, a.currency)}</span></td>
              <td class="num">${money(p.market_value, a.currency)}</td>
              <td class="num ${clsByValue(p.unrealized_pnl)}">${money(p.unrealized_pnl, a.currency)}<br><span>${pct(p.unrealized_pnl_pct)}</span></td>
              <td class="num">${money(p.stop_loss, a.currency)}<br><span class="muted">${money(p.target_price, a.currency)}</span></td>
              <td>${tag(monitor.status || "跟踪", monitor.severity === "pass" ? "info" : "warn")}<div class="stock-meta">${monitor.reason || ""}</div></td>
            </tr>`;
          }).join("")}
        </tbody>
      </table>
    </div>` : "";
  panel("positionsPanel", "当前持仓", "按交易软件视角显示仓位、成本、盈亏、关键价和纪律状态", tag(`${rows.length} 只`), html);
}

function renderOrders() {
  const a = currentAccount();
  const rows = accountItems("orders");
  const html = rows.length ? `
    <div class="table-wrap">
      <table>
        <thead><tr><th>候选</th><th>动作</th><th class="num">评分</th><th class="num">现价</th><th class="num">进场区间</th><th class="num">止损/目标</th><th>理由</th></tr></thead>
        <tbody>
          ${rows.map((o) => `<tr>
            <td><div class="stock-name">${o.name || o.symbol}</div><div class="stock-meta mono">${o.symbol} · ${o.market} · ${o.theme || ""}</div></td>
            <td>${tag(o.committee_action || "", o.committee_action === "direct_follow" ? "good" : o.committee_action === "avoid_for_now" ? "bad" : "warn")}</td>
            <td class="num">${fmt(o.committee_score || o.score, 1)}</td>
            <td class="num">${money(o.latest_price, a.currency)}<br><span class="${clsByValue(o.change_pct)}">${pct(o.change_pct)}</span></td>
            <td class="num">${money(o.entry_zone?.[0], a.currency)}<br><span class="muted">${money(o.entry_zone?.[1], a.currency)}</span></td>
            <td class="num">${money(o.stop_loss, a.currency)}<br><span class="muted">${money(o.target_price, a.currency)}</span></td>
            <td><div>${o.committee_summary || ""}</div>${list((o.reason || []).slice(0, 2))}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>` : "";
  panel("ordersPanel", "候选与计划单", "A股、港股、美股统一纳入观察；只有 direct_follow 才会进入主动买入", tag(`${rows.length} 个`), html);
}

function renderDecision() {
  const d = STATE.decision_latest || {};
  const blocks = [
    ["先检查", d.checks],
    ["为什么卖", d.why_sell],
    ["为什么买", d.why_buy],
    ["为什么继续拿", d.why_hold],
    ["为什么暂时不买", d.why_not_buy],
    ["下一步盯什么", d.planned_focus],
  ].filter(([, items]) => (items || []).filter(Boolean).length);
  const body = `
    ${d.summary ? `<div class="row-card"><div class="row-title">${d.summary}</div><div class="stock-meta">${d.phase_label || ""} · ${d.timestamp || ""}</div></div>` : ""}
    <div class="split-list">
      ${blocks.map(([title, items]) => `<div class="decision-block"><div class="decision-title">${title}</div>${list(items)}</div>`).join("")}
    </div>`;
  panel("decisionPanel", "本轮决策记录", "只显示状态里真实写入的决策字段", tag(d.phase_label || "阶段"), body.trim());
}

function renderCommittee() {
  const reviews = (STATE.candidate_reviews || []).filter((x) => String(x.account_id || "") === selectedAccount).filter(rowMatches).slice(0, 5);
  const body = reviews.map((r) => `
    <div class="row-card">
      <div class="row-card-head">
        <div><div class="row-title">${r.name || r.symbol}</div><div class="stock-meta mono">${r.symbol} · ${r.market} · ${r.theme || ""}</div></div>
        ${tag(r.committee_action, r.committee_action === "direct_follow" ? "good" : r.committee_action === "avoid_for_now" ? "bad" : "warn")}
      </div>
      ${list(r.debate || [])}
    </div>`).join("");
  panel("committeePanel", "委员会审议", "宏观、主题、技术、赔率、风险、组合和纪律门统一给出动作", tag(`${reviews.length} 条`), body);
}

function renderMarket() {
  const health = STATE.market_context?.data_health || [];
  const headlines = STATE.market_context?.headlines || [];
  const macro = STATE.market_context?.macro || [];
  const body = `
    <div class="health-grid">
      ${health.map((h) => `<div class="health-item"><span>${h.market ? `${h.market} · ` : ""}${h.source || ""}</span>${tag(h.ok ? "OK" : "缺失", h.ok ? "info" : "warn")}</div>`).join("")}
    </div>
    ${headlines.length ? `<div class="decision-block"><div class="decision-title">新闻</div>${list(headlines.map((x) => x.title))}</div>` : ""}
    ${macro.length ? `<div class="decision-block"><div class="decision-title">宏观</div>${list(macro.map((x) => `${x.name}: ${x.value} (${x.date})`))}</div>` : ""}`;
  panel("marketPanel", "数据源与外部线索", "接口失败会明示，不用旧文本冒充新分析", "", body);
}

function renderJournal() {
  const log = STATE.decision_log || [];
  const body = log.slice(0, 8).map((x) => `
    <div class="row-card">
      <div class="row-card-head">
        <div><div class="row-title">${x.phase_label || x.phase || ""}</div><div class="stock-meta">${x.timestamp || ""}</div></div>
        ${tag(x.date || "")}
      </div>
      <div class="row-text">${x.summary || ""}</div>
    </div>`).join("");
  panel("journalPanel", "滚动决策日志", "按阶段保留最近记录，用于盘后复盘", tag(`${log.length} 条`), body);
}

function render() {
  if (!STATE) return;
  setupControls();
  renderMeta();
  renderMetrics();
  renderDiscipline();
  renderPositions();
  renderOrders();
  renderDecision();
  renderCommittee();
  renderMarket();
  renderJournal();
}

loadState(false).catch((err) => {
  $("metaLine").textContent = `加载失败：${err.message}`;
});

