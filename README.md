# Stock Lab

一个面向 **A 股 / 港股 / 美股** 的股票研究与模拟交易框架仓库。

这个公开版本刻意只保留：

- 多市场状态机
- 模拟账户与风险纪律
- 看板与移动端 UI
- 定时调度脚本
- 可扩展的数据抓取与策略评分框架

**不会包含作者个人持仓、观察股、复盘记录、选股偏好或可直接照抄的交易模板。**

## 适合拿它做什么

- 搭建自己的 AI 股票研究看板
- 学习“状态文件 + 前端看板 + 定时刷新”的项目结构
- 在纸面交易环境里测试自己的选股、风控和调仓规则
- 作为多市场监控 / 风险面板的起点

## 不适合拿它做什么

- 直接复制作者的实盘思路
- 当作券商实盘下单系统直接使用
- 把默认配置当作投资建议

## 核心特性

- **多市场会话**：A / HK / US 各自按本地交易时段进入盘前、盘中、盘后阶段
- **纸面交易账户**：支持多账户、多币种、持仓与交易日志
- **纪律优先**：止损 / 止盈 / 移动止盈 / 时间止损等逻辑独立执行
- **状态驱动 UI**：后端生成 `simulation_state.json`，桌面端与移动端都只渲染真实状态
- **可替换策略层**：你可以保留看板，换掉候选池、评分器、执行规则
- **轻部署**：纯 Python + 静态页面，无需复杂前端构建

## 项目结构

```text
stock-lab/
├── trading_engine.py                # 主入口：生成 simulation_state.json
├── dashboard_server.py              # 看板 HTTP 服务
├── init_dashboard_state.py          # 初始化空状态
├── intraday_quick_refresh.py        # 兼容轻刷新命令
├── live_enrich_state.py             # 兼容旧入口
├── core/
│   ├── config.py                    # 默认配置与环境变量读取
│   ├── market_data.py               # 行情/新闻/宏观数据源适配
│   ├── discipline.py                # 风险与仓位纪律
│   ├── strategy.py                  # 候选构建、评分、委员会、模拟进场
│   ├── state_builder.py             # 全局状态拼装
│   └── utils.py                     # 多市场时间/金额/通用工具
├── static/
│   ├── dashboard.html
│   ├── app.js
│   ├── styles.css
│   ├── mobile.html
│   ├── mobile_app.js
│   └── mobile.css
├── tests/
├── .env.example
├── config.example.json
└── PROJECT_AUDIT.md
```

## 安装

### Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 启动

生成状态：

```bash
python trading_engine.py
```

启动看板：

```bash
python dashboard_server.py
```

默认地址：

- `http://127.0.0.1:8765/dashboard`
- `http://127.0.0.1:8765/m`
- `http://127.0.0.1:8765/api/state`

## 配置方式

仓库只提交模板，不提交你的真实配置。

1. 复制模板：

```bash
cp config.example.json config.json
```

2. 按你的需求填写：

- 账户资金
- 关注市场
- watchlists
- 风控阈值
- API keys

### 环境变量

推荐通过环境变量提供 API key：

```bash
export TWELVE_DATA_API_KEY="..."
export ALPHA_VANTAGE_API_KEY="..."
export FINNHUB_API_KEY="..."
export NEWS_API_KEY="..."
export FRED_API_KEY="..."
```

没有 key 时系统不会崩溃，但相关数据源会显示为 unavailable。

## 默认公开版约定

这个公开版本默认：

- `watchlists` 为空
- 不附带作者持仓或交易日志
- 不附带作者复盘/学习笔记
- 不附带可直接复刻的个股选择偏好

你需要自行在 `config.json` 中填入自己的：

- 股票池
- 主题分类
- 风险参数
- 调仓逻辑

## 示例 watchlist 配置

把下面内容放进 `config.json` 即可开始自定义：

```json
{
  "watchlists": {
    "A": [
      {"symbol": "510300", "name": "CSI 300 ETF", "theme": "Index/ETF"}
    ],
    "HK": [
      {"symbol": "2800.HK", "name": "Tracker Fund of Hong Kong", "theme": "Index/ETF"}
    ],
    "US": [
      {"symbol": "SPY", "name": "SPDR S&P 500 ETF", "theme": "Index/ETF"}
    ]
  }
}
```

## 调度

仓库提供了多市场会话循环脚本，可配合 cron / scheduler 使用。

典型方式：

- A 股：每 15 分钟触发一次，由脚本自行判断是否命中有效会话点
- 港股：同上
- 美股：同上

核心思路不是“无脑每次都跑完整分析”，而是：

- 先判断市场是否开市
- 再判断当前是否处于需要更新的阶段
- 命中时才刷新状态与执行纸面交易逻辑

## 测试

```bash
python3 -m unittest discover -s tests
```

## 二次开发建议

如果你想把它做成自己的系统，优先改这几层：

1. `core/config.py`：默认参数与账户结构
2. `core/market_data.py`：接入你信任的数据源
3. `core/strategy.py`：候选评分与进场逻辑
4. `core/discipline.py`：风控与退出规则
5. `static/`：UI 风格与页面布局

## 风险提示

这个项目当前是：

- **研究工具**
- **模拟交易框架**
- **风险与状态可视化面板**

它不是：

- 券商实盘交易系统
- 投资建议服务
- 收益承诺工具

如要接入实盘，至少还需要：

- broker adapter
- 权限隔离
- 二次确认
- 风险熔断
- 完整日志审计
- 异常回滚与告警
