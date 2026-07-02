let STATE = null;
let selectedAccount = "";
let selectedMarket = "ALL";
let searchText = "";
let symbolAnalysisInput = "";
let symbolAnalysisData = null;
let symbolAnalysisError = "";
let symbolAnalysisLoading = false;

const $ = (id) => document.getElementById(id);
const n = (v) => Number(v || 0);
const fmt = (v, digits = 2) => n(v).toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
const pct = (v) => `${fmt(v)}%`;

function money(v, currency = "CNY") {
  const prefix = currency === "USD" ? "$" : currency === "HKD" ? "HK$" : "¥";
  return `${prefix}${fmt(v)}`;
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function clsByValue(v) {
  return n(v) >= 0 ? "gain" : "loss";
}

function tag(text, kind = "") {
  return `<span class="tag ${kind}">${esc(text)}</span>`;
}

function list(items) {
  const clean = (items || []).filter(Boolean);
  if (!clean.length) return "";
  return `<ul class="bullet-list">${clean.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>`;
}

function changeList(items) {
  const clean = (items || []).filter(Boolean);
  if (!clean.length) return "";
  return `<ul class="bullet-list">${clean.map((x) => `<li class="change-text">${esc(x)}</li>`).join("")}</ul>`;
}

function panel(id, title, sub, right, body) {
  $(id).innerHTML = `
    <div class="panel-head">
      <div><div class="panel-title">${esc(title)}</div>${sub ? `<div class="panel-sub">${esc(sub)}</div>` : ""}</div>
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

function accountTopReviews() {
  return (STATE.thought_process?.top_reviews || []).filter((x) => String(x.account_id || "") === selectedAccount).filter(rowMatches);
}

function setupControls() {
  const select = $("accountSelect");
  select.innerHTML = (STATE.accounts || []).map((a) => `<option value="${esc(a.id)}">${esc(a.label || a.id)}</option>`).join("");
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
      <div class="metric-k">${esc(k)}</div>
      <div class="metric-v ${klass || ""}">${v}</div>
      <div class="metric-note">${esc(note)}</div>
    </div>`).join("");
}

function renderHomeDigest() {
  const digest = STATE.home_digest || {};
  const metrics = (digest.summary_items || []).map((item) => `
    <div class="digest-metric">
      <div class="metric-k">${esc(item.label || "")}</div>
      <div class="metric-v ${item.kind === "good" ? "change-text" : ""}">${esc(String(item.value ?? 0))}</div>
      <div class="metric-note">${esc(item.note || "")}</div>
    </div>`).join("");
  const body = `
    ${metrics ? `<div class="digest-grid">${metrics}</div>` : ""}
    ${metrics ? "" : '<div class="empty">今日总览暂未生成，先看下方决策与持仓模块。</div>'}
  `;
  panel("homeDigestPanel", "今日总览", "首页只保留最关键的盘面摘要，具体改动放到思考和线索区里看", tag(digest.headline || "今日概览", "info"), body.trim());
}

function renderDiscipline() {
  const queue = (STATE.discipline_summary?.queue || []).filter((x) => String(x.account_id || "") === selectedAccount).filter(rowMatches);
  const important = queue.filter((x) => x.severity !== "pass");
  const rows = important.length ? important : queue.slice(0, 5);
  const body = rows.map((x) => `
    <div class="row-card">
      <div class="row-card-head">
        <div>
          <div class="row-title">${esc(x.name || x.symbol)}</div>
          <div class="stock-meta mono">${esc(x.symbol || "")} · ${esc(x.market || "")}</div>
        </div>
        ${tag(x.executed ? "已执行" : x.action, x.severity === "critical" ? "bad" : x.severity === "important" ? "good" : x.severity === "warning" ? "warn" : "info")}
      </div>
      <div class="row-text">${esc(x.reason || "")}</div>
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
            const review = (STATE.learning_center?.position_reviews || []).find((x) => x.symbol === p.symbol) || {};
            return `<tr>
              <td><div class="stock-name">${esc(p.name || p.symbol)}</div><div class="stock-meta mono">${esc(p.symbol)} · ${esc(p.market)}</div></td>
              <td>${esc(p.theme || "")}</td>
              <td class="num">${p.shares || 0}</td>
              <td class="num">${money(p.cost_price, a.currency)}<br><span class="muted">${money(p.latest_price, a.currency)}</span></td>
              <td class="num">${money(p.market_value, a.currency)}</td>
              <td class="num ${clsByValue(p.unrealized_pnl)}">${money(p.unrealized_pnl, a.currency)}<br><span>${pct(p.unrealized_pnl_pct)}</span></td>
              <td class="num ${review.changed_fields?.stop_loss || review.changed_fields?.target_price ? "change-text" : ""}">${money(p.stop_loss, a.currency)}<br><span class="${review.changed_fields?.target_price ? "change-text" : "muted"}">${money(p.target_price, a.currency)}</span></td>
              <td>${tag(review.action_bias || monitor.status || "跟踪", monitor.severity === "pass" ? "info" : "warn")}<div class="stock-meta">${esc(monitor.reason || "")}</div></td>
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
            <td><div class="stock-name">${esc(o.name || o.symbol)}</div><div class="stock-meta mono">${esc(o.symbol)} · ${esc(o.market)} · ${esc(o.theme || "")}</div></td>
            <td>${tag(o.committee_action || "", o.committee_action === "direct_follow" ? "good" : o.committee_action === "avoid_for_now" ? "bad" : "warn")}</td>
            <td class="num">${fmt(o.committee_score || o.score, 1)}</td>
            <td class="num">${money(o.latest_price, a.currency)}<br><span class="${clsByValue(o.change_pct)}">${pct(o.change_pct)}</span></td>
            <td class="num">${money(o.entry_zone?.[0], a.currency)}<br><span class="muted">${money(o.entry_zone?.[1], a.currency)}</span></td>
            <td class="num">${money(o.stop_loss, a.currency)}<br><span class="muted">${money(o.target_price, a.currency)}</span></td>
            <td><div>${esc(o.committee_summary || "")}</div>${list((o.reason || []).slice(0, 2))}</td>
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
    ${d.summary ? `<div class="row-card"><div class="row-title">${esc(d.summary)}</div><div class="stock-meta">${esc(d.phase_label || "")} · ${esc(d.timestamp || "")}</div></div>` : ""}
    <div class="split-list">
      ${blocks.map(([title, items]) => `<div class="decision-block"><div class="decision-title">${esc(title)}</div>${list(items)}</div>`).join("")}
    </div>`;
  panel("decisionPanel", "本轮决策记录", "只显示状态里真实写入的决策字段", tag(d.phase_label || "阶段"), body.trim());
}

function renderCommittee() {
  const reviews = (STATE.candidate_reviews || []).filter((x) => String(x.account_id || "") === selectedAccount).filter(rowMatches).slice(0, 5);
  const fallback = reviews.length ? reviews : accountTopReviews().slice(0, 5).map((x) => ({
    ...x,
    committee_action: x.action,
    committee_score: x.score,
  }));
  const body = fallback.map((r) => `
    <div class="row-card">
      <div class="row-card-head">
        <div><div class="row-title">${esc(r.name || r.symbol)}</div><div class="stock-meta mono">${esc(r.symbol)} · ${esc(r.market || "")} · ${esc(r.theme || "")}</div></div>
        ${tag(r.committee_action || "观察", r.committee_action === "direct_follow" ? "good" : r.committee_action === "avoid_for_now" ? "bad" : "warn")}
      </div>
      ${list(r.debate || [])}
    </div>`).join("");
  panel("committeePanel", "委员会审议", "宏观、主题、技术、赔率、风险、组合和纪律门统一给出动作", tag(`${fallback.length} 条`), body);
}

function renderMarket() {
  const headlines = STATE.market_context?.mapped_headlines || [];
  const body = headlines.length
    ? `<div class="news-hit-list">${headlines.map((x) => `<div class="news-hit"><div class="row-card-head"><div><div class="row-title">${esc(x.title || "")}</div><div class="stock-meta">${esc(x.source || "")}${x.published_at ? ` · ${esc(x.published_at)}` : ""}</div></div>${tag(`${(x.related_positions || []).length} 持仓 / ${(x.related_watchlist || []).length} 观察`, (x.related_positions || []).length ? 'good' : 'warn')}</div><div class="chip-row">${(x.matched_themes || []).map((theme) => tag(theme, 'info')).join('')}</div>${(x.related_positions || []).length ? `<div class="analysis-block"><div class="decision-title">关联持仓</div><div class="chip-row">${(x.related_positions || []).map((item) => tag(`${item.name || item.symbol} ${item.symbol || ''}`, 'good')).join('')}</div></div>` : ""}${(x.related_watchlist || []).length ? `<div class="analysis-block"><div class="decision-title">关联观察股</div><div class="chip-row">${(x.related_watchlist || []).map((item) => tag(`${item.name || item.symbol} ${item.symbol || ''}`, 'warn')).join('')}</div></div>` : ""}</div>`).join("")}</div>`
    : '<div class="empty">今天暂无命中持仓/观察池的新增外部线索</div>';
  panel("marketPanel", "外部线索", "新闻先映射到主题，再映射到持仓和观察股；这样你能直接看到它影响哪部分股票池", "", body);
}

function positionAnalysisCards() {
  const positions = accountItems("positions");
  const a = currentAccount();
  return positions.map((p) => {
    const monitor = (STATE.position_monitor || []).find((x) => x.symbol === p.symbol && x.account_id === p.account_id) || {};
    const review = (STATE.learning_center?.position_reviews || []).find((x) => x.symbol === p.symbol) || {};
    const thesis = p.holding_thesis || monitor.reason || "当前持仓暂无额外说明，先看纪律与盈亏比。";
    const invalidation = p.invalidation || (p.stop_loss ? `跌破 ${money(p.stop_loss, a.currency)} 附近视为逻辑受损。` : "暂无明确失效条件。");
    const riskPoints = (p.risk_points || []).slice(0, 4);
    const chips = [
      tag(`现价 ${money(p.latest_price, a.currency)}`, "info"),
      tag(`止损 ${money(p.stop_loss, a.currency)}`, review.changed_fields?.stop_loss ? "good" : "warn"),
      tag(`目标 ${money(p.target_price, a.currency)}`, review.changed_fields?.target_price ? "good" : "info"),
      tag(`${pct(p.unrealized_pnl_pct)} 浮盈亏`, clsByValue(p.unrealized_pnl) === "gain" ? "good" : "bad"),
    ].join("");
    return `
      <div class="row-card analysis-card">
        <div class="row-card-head">
          <div>
            <div class="row-title">${esc(p.name || p.symbol)}</div>
            <div class="stock-meta mono">${esc(p.symbol)} · ${esc(p.market)} · ${esc(p.theme || "")}</div>
          </div>
          ${tag(review.action_bias || monitor.status || "持仓跟踪", monitor.severity === "pass" ? "info" : "warn")}
        </div>
        <div class="chip-row">${chips}</div>
        ${review.summary ? `<div class="analysis-block"><div class="decision-title">今日判断</div><div class="row-text">${esc(review.summary)}</div></div>` : ""}
        ${review.what_if ? `<div class="analysis-block"><div class="decision-title">如果今天更主动</div><div class="row-text">${esc(review.what_if)}</div></div>` : ""}
        ${review.changes?.length ? `<div class="analysis-block change-note"><div class="decision-title">今天改过的参数</div>${changeList(review.changes.map((x) => x.text))}</div>` : ""}
        ${review.lessons?.length ? `<div class="analysis-block"><div class="decision-title">为什么这么看</div>${list(review.lessons)}</div>` : ""}
        <div class="analysis-block"><div class="decision-title">为什么继续拿 / 当前判断</div><div class="row-text ${review.changed_fields?.invalidation ? "change-text" : ""}">${esc(thesis)}</div></div>
        <div class="analysis-block"><div class="decision-title">失效条件</div><div class="row-text ${review.changed_fields?.invalidation ? "change-text" : ""}">${esc(invalidation)}</div></div>
        ${riskPoints.length ? `<div class="analysis-block"><div class="decision-title">风险点</div>${list(riskPoints)}</div>` : ""}
      </div>`;
  }).join("");
}

function watchAnalysisCards() {
  const a = currentAccount();
  const orders = accountItems("orders").slice(0, 8);
  const fallback = orders.length ? orders : accountTopReviews().slice(0, 8).map((x) => ({
    symbol: x.symbol,
    name: x.name,
    market: x.market,
    account_id: x.account_id,
    committee_action: x.action,
    committee_score: x.score,
    committee_summary: (x.debate || [])[0] || "观察池说明待补充。",
    debate: x.debate || [],
  }));
  return fallback.map((o) => {
    const actionKind = o.committee_action === "direct_follow" ? "good" : o.committee_action === "avoid_for_now" ? "bad" : "warn";
    const quickAnalyzeBtn = (o.market === "A" && String(o.symbol || "").match(/^\d{6}$/))
      ? `<button class="mini-btn" data-symbol-analyze="${esc(o.symbol)}">分析 ${esc(o.symbol)}</button>`
      : "";
    return `
      <div class="row-card analysis-card">
        <div class="row-card-head">
          <div>
            <div class="row-title">${esc(o.name || o.symbol)}</div>
            <div class="stock-meta mono">${esc(o.symbol || "")} · ${esc(o.market || "")} · ${esc(o.theme || "")}</div>
          </div>
          <div class="chip-row compact">${tag(o.committee_action || "观察", actionKind)}${quickAnalyzeBtn}</div>
        </div>
        <div class="mini-grid">
          <div class="mini"><div class="mini-k">评分</div><div class="mini-v">${fmt(o.committee_score || o.score || 0, 1)}</div></div>
          <div class="mini"><div class="mini-k">现价</div><div class="mini-v">${o.latest_price ? money(o.latest_price, a.currency) : "--"}</div></div>
          <div class="mini"><div class="mini-k">止损</div><div class="mini-v">${o.stop_loss ? money(o.stop_loss, a.currency) : "--"}</div></div>
          <div class="mini"><div class="mini-k">目标</div><div class="mini-v">${o.target_price ? money(o.target_price, a.currency) : "--"}</div></div>
        </div>
        <div class="analysis-block"><div class="decision-title">为什么这样看</div><div class="row-text">${esc(o.committee_summary || "暂无说明")}</div></div>
        ${(o.reason || o.debate || []).length ? `<div class="analysis-block"><div class="decision-title">补充依据</div>${list((o.reason || o.debate || []).slice(0, 4))}</div>` : ""}
      </div>`;
  }).join("");
}

function renderBookAnalysis() {
  const positions = accountItems("positions");
  const watchItems = accountItems("orders");
  const body = `
    <div class="analysis-section">
      <div class="section-label">持仓分析</div>
      ${positions.length ? `<div class="analysis-list">${positionAnalysisCards()}</div>` : `<div class="empty">当前筛选下没有持仓。</div>`}
    </div>
    <div class="analysis-section section-top-gap">
      <div class="section-label">观察股分析</div>
      ${(watchItems.length || accountTopReviews().length) ? `<div class="analysis-list">${watchAnalysisCards()}</div>` : `<div class="empty">当前没有可展示的观察股 / 审议对象。</div>`}
    </div>`;
  panel("bookAnalysisPanel", "个股分析（持仓 / 观察）", "优先复用 state 里已经算过或写过的理由，不默认额外调用 LLM", tag(`${positions.length} 持仓 / ${watchItems.length || accountTopReviews().length} 观察`, "info"), body);
}

async function analyzeSymbol(symbol) {
  const digits = String(symbol || "").replace(/\D/g, "").slice(0, 6);
  symbolAnalysisInput = digits;
  if (digits.length !== 6) {
    symbolAnalysisError = "请输入 6 位 A 股代码";
    symbolAnalysisData = null;
    symbolAnalysisLoading = false;
    renderSymbolAnalysis();
    return;
  }
  symbolAnalysisLoading = true;
  symbolAnalysisError = "";
  renderSymbolAnalysis();
  try {
    const res = await fetch(`/api/analyze_stock?symbol=${encodeURIComponent(digits)}&detailed=1`, { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || `analyze ${res.status}`);
    symbolAnalysisData = data;
    symbolAnalysisError = "";
  } catch (err) {
    symbolAnalysisData = null;
    symbolAnalysisError = err.message || String(err);
  } finally {
    symbolAnalysisLoading = false;
    renderSymbolAnalysis();
  }
}

function quickAnalyzeButtons() {
  document.querySelectorAll("[data-symbol-analyze]").forEach((btn) => {
    btn.onclick = () => analyzeSymbol(btn.getAttribute("data-symbol-analyze") || "");
  });
}

function renderSymbolAnalysis() {
  const d = symbolAnalysisData;
  const inputValue = esc(symbolAnalysisInput || "");
  const top = `
    <div class="symbol-form">
      <label class="field symbol-field">
        <span>输入 6 位 A 股代码</span>
        <div class="symbol-input-row">
          <input id="symbolAnalysisInput" value="${inputValue}" placeholder="例如 600519" maxlength="6" inputmode="numeric" />
          <button class="icon-btn" id="symbolAnalysisBtn">分析</button>
        </div>
      </label>
      <div class="symbol-quick-row">
        ${accountItems("positions").filter((x) => x.market === "A").slice(0, 4).map((x) => `<button class="mini-btn" data-symbol-analyze="${esc(x.symbol)}">${esc(x.symbol)}</button>`).join("")}
      </div>
    </div>`;

  let body = top;
  if (symbolAnalysisLoading) {
    body += `<div class="row-card"><div class="row-text">正在按 AKShare + 本地规则计算，请稍等…</div></div>`;
  } else if (symbolAnalysisError) {
    body += `<div class="row-card"><div class="row-title">分析失败</div><div class="row-text">${esc(symbolAnalysisError)}</div></div>`;
  } else if (d) {
    const statusKind = d.status?.kind === "good" ? "info" : d.status?.kind === "warn" ? "warn" : d.status?.kind === "info" ? "info" : "good";
    body += `
      <div class="row-card analysis-card">
        <div class="row-card-head">
          <div>
            <div class="row-title">${esc(d.name || d.symbol)}</div>
            <div class="stock-meta mono">${esc(d.symbol)} · ${esc(d.as_of || "")}</div>
          </div>
          ${tag(d.status?.text || "状态未知", statusKind)}
        </div>
        <div class="row-text">${esc(d.status?.summary || "")}</div>
        <div class="mini-grid">
          <div class="mini"><div class="mini-k">现价</div><div class="mini-v">${fmt(d.quote?.latest)}</div></div>
          <div class="mini"><div class="mini-k">涨跌幅</div><div class="mini-v ${clsByValue(d.quote?.change_pct)}">${pct(d.quote?.change_pct)}</div></div>
          <div class="mini"><div class="mini-k">支撑</div><div class="mini-v">${fmt(d.levels?.support)}</div></div>
          <div class="mini"><div class="mini-k">止损</div><div class="mini-v">${fmt(d.levels?.hard_stop)}</div></div>
          <div class="mini"><div class="mini-k">压力</div><div class="mini-v">${fmt(d.levels?.resistance)}</div></div>
          <div class="mini"><div class="mini-k">止盈</div><div class="mini-v">${fmt(d.levels?.take_profit)}</div></div>
          <div class="mini"><div class="mini-k">MA5/10/20</div><div class="mini-v">${fmt(d.metrics?.ma5)} / ${fmt(d.metrics?.ma10)} / ${fmt(d.metrics?.ma20)}</div></div>
          <div class="mini"><div class="mini-k">趋势</div><div class="mini-v">${esc(d.metrics?.trend_label || "--")}</div></div>
        </div>
        <div class="analysis-block"><div class="decision-title">规则结论</div>${list(d.analysis || [])}</div>
        <div class="analysis-block"><div class="decision-title">异动检查</div>
          <div class="alert-list">
            ${(d.alerts || []).map((a) => `<div class="alert-item ${a.triggered ? 'triggered' : ''}"><div><strong>${esc(a.label)}</strong><div class="stock-meta">当前 ${esc(a.current)}${esc(a.unit || '')} / 阈值 ${esc(a.threshold)}${esc(a.unit || '')}</div></div>${tag(a.triggered ? '已触发' : '未触发', a.triggered ? 'warn' : 'info')}</div>`).join("")}
          </div>
        </div>
        <div class="analysis-block"><div class="decision-title">现实新闻</div>${(d.news_context?.has_hits ? `${list((d.news_context.items || []).slice(0, 4).map((item) => {
          const final = item.news_analysis?.final || {};
          return `${item.title || ''}｜${final.sentiment || 'neutral'}｜影响分 ${final.impact_score || 0}/5｜${final.action_hint || '继续观察'}`;
        }))}<div class="stock-meta">处理模式：${esc(d.news_context?.processing?.mode || 'rule_only')} · 命中 ${esc(d.news_context?.hit_count || 0)} 条</div>` : '<div class="row-text">当前未命中与该股直接相关的实时新闻，暂按量价结构为主。</div>')}</div>
        ${d.detailed_report ? `<div class="analysis-block"><div class="decision-title">详细说明</div>${list([...(d.detailed_report.overview || []), ...(d.detailed_report.thesis || []), ...(d.detailed_report.news || []), ...(d.detailed_report.risk_notes || [])])}</div>` : ""}
      </div>`;
  } else {
    body += `<div class="empty">输入 A 股六位代码后，这里会给出异动、支撑/压力、止损/止盈与风险标签。默认不调用 LLM。</div>`;
  }

  panel("symbolAnalysisPanel", "单股快速分析", "异动检测、止盈止损、支撑压力和风险标签走 deterministic 规则层；适合高频查询", d ? tag(`${d.status?.triggered_count || 0}/${d.status?.total_checks || 0} 异动触发`, "info") : "", body);

  const input = $("symbolAnalysisInput");
  const btn = $("symbolAnalysisBtn");
  if (input) {
    input.oninput = (e) => {
      symbolAnalysisInput = e.target.value.replace(/\D/g, "").slice(0, 6);
    };
    input.onkeydown = (e) => {
      if (e.key === "Enter") analyzeSymbol(symbolAnalysisInput || input.value);
    };
  }
  if (btn) btn.onclick = () => analyzeSymbol(symbolAnalysisInput || input.value);
  quickAnalyzeButtons();
}

function renderJournal() {
  const log = STATE.decision_log || [];
  const body = log.slice(0, 8).map((x) => `
    <div class="row-card">
      <div class="row-card-head">
        <div><div class="row-title">${esc(x.phase_label || x.phase || "")}</div><div class="stock-meta">${esc(x.timestamp || "")}</div></div>
        ${tag(x.date || "")}
      </div>
      <div class="row-text">${esc(x.summary || "")}</div>
    </div>`).join("");
  panel("journalPanel", "滚动决策日志", "按阶段保留最近记录，用于盘后复盘", tag(`${log.length} 条`), body);
}

function render() {
  if (!STATE) return;
  setupControls();
  renderMeta();
  renderMetrics();
  renderHomeDigest();
  renderDiscipline();
  renderPositions();
  renderOrders();
  renderBookAnalysis();
  renderDecision();
  renderCommittee();
  renderMarket();
  renderSymbolAnalysis();
  renderJournal();
}

loadState(false).catch((err) => {
  $("metaLine").textContent = `加载失败：${err.message}`;
});
