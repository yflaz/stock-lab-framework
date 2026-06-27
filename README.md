# Stock Lab Framework

一个面向 **A 股 / 港股 / 美股** 的研究、模拟交易与看板可视化框架。

它适合这样使用：你把仓库交给自己的 agent，告诉它你的交易风格、交易频率、关注板块、风险约束和执行偏好；然后让它在你的本地环境里完成配置、扩展和部署。

这个仓库默认只提供 **框架、状态结构、看板界面和可扩展逻辑层**。首次打开时，你会看到一个空白起点，再由你或你的 agent 把它定制成自己的版本。

## 你拿到这个项目之后可以做什么

- 搭建自己的 AI 股票研究看板
- 维护一个本地运行的多市场模拟交易系统
- 把个人交易风格沉淀成结构化文档与配置
- 让 agent 按你的风格持续迭代选股、风控和展示逻辑
- 作为后续接入更多数据源、执行层和自动调度的基础工程

## 这个仓库默认提供什么

- **多市场会话管理**：A / HK / US 各自按本地交易时段切换盘前、盘中、盘后阶段
- **纸面交易账户模型**：支持多账户、多币种、持仓、订单与交易记录
- **纪律与风控层**：止损、止盈、移动止盈、时间止损、仓位约束
- **状态驱动看板**：后端输出统一状态文件，桌面端与移动端基于同一份状态渲染
- **可替换策略层**：你可以保留框架，替换候选池、评分器、审议逻辑和执行规则
- **轻量部署方式**：纯 Python + 静态页面，无需前端构建链

## 项目结构

```text
stock-lab-framework/
├── trading_engine.py                # 主入口：生成 simulation_state.json
├── dashboard_server.py              # 看板 HTTP 服务
├── init_dashboard_state.py          # 初始化空状态
├── intraday_quick_refresh.py        # 兼容轻刷新命令
├── live_enrich_state.py             # 兼容旧入口
├── core/
│   ├── config.py                    # 默认配置与环境变量读取
│   ├── market_data.py               # 行情/新闻/宏观数据源适配
│   ├── discipline.py                # 风险与仓位纪律
│   ├── strategy.py                  # 候选构建、评分、审议、模拟进场
│   ├── state_builder.py             # 全局状态拼装
│   ├── state_store.py               # 状态文件读写
│   ├── stock_analysis.py            # 个股分析逻辑
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
├── TRADING_STRATEGY.md              # 交易风格模板：留给你或你的 agent 填写
└── PROJECT_AUDIT.md
```

## 推荐使用方式

### 方式一：自己改

1. 克隆仓库
2. 建立虚拟环境
3. 填写 `config.json`
4. 编辑 `TRADING_STRATEGY.md`
5. 运行引擎并启动看板

### 方式二：交给自己的 agent

你可以把这个仓库链接直接交给自己的 agent，并告诉它：

- 你的交易市场（A / HK / US）
- 你的交易风格（趋势、波段、事件驱动、网格、低吸等）
- 你的交易频率（日内、3-5 天、波段、中线）
- 你的板块偏好或禁区
- 你的仓位规则与止损方式
- 你的 UI 偏好和部署环境

然后让它完成：

- 填写 `TRADING_STRATEGY.md`
- 生成 `config.json`
- 调整 `core/strategy.py` / `core/discipline.py`
- 启动本地看板并验证可用性

## 安装

这个项目不是 PyPI 包，**正确的开始方式是先从 GitHub 克隆仓库**。

### Linux / macOS

```bash
git clone https://github.com/yflaz/stock-lab-framework.git
cd stock-lab-framework
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
git clone https://github.com/yflaz/stock-lab-framework.git
cd stock-lab-framework
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## 初始化

### 1. 复制配置模板

Linux / macOS:

```bash
cp config.example.json config.json
```

Windows PowerShell:

```powershell
Copy-Item config.example.json config.json
```

### 2. 编辑交易风格模板

请打开 `TRADING_STRATEGY.md`，填入你自己的：

- 交易目标
- 持仓周期
- 选股范围
- 风险预算
- 进出场规则
- 板块偏好
- 不做的交易类型

如果你在用 agent，也可以直接让 agent 根据你的描述填写这份文档。

### 3. 按需填写 API key

推荐通过环境变量提供 API key：

```bash
export TWELVE_DATA_API_KEY="..."
export ALPHA_VANTAGE_API_KEY="..."
export FINNHUB_API_KEY="..."
export NEWS_API_KEY="..."
export FRED_API_KEY="..."
```

没有 key 时系统不会崩溃，但相关数据源会显示为 unavailable。

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
- `http://127.0.0.1:8765/api/analyze_stock?symbol=600519`

## 仓库默认是空白起点

公开模板默认：

- `watchlists` 为空
- 不提交 `config.json`
- 不提交运行态状态文件
- 不附带现成交易风格文档内容

也就是说，别人拿到仓库后看到的是一个可运行的框架，而不是一个预先写满内容的交易系统。

## 配置方式

`config.example.json` 只保留结构化模板。你需要自行确定并填写：

- 使用哪些市场
- 每个账户的初始资金
- `watchlists`
- 风控阈值
- 数据源 key
- 是否自动进入纸面持仓

## 调度

仓库提供了多市场会话循环脚本，可配合 cron / scheduler 使用。

典型方式：

- A 股：每 15 分钟触发一次，由脚本判断是否命中有效时段
- 港股：同上
- 美股：同上

核心思路不是每次都跑完整分析，而是：

1. 先判断市场是否开市
2. 再判断当前是否处于需要更新的阶段
3. 命中时才刷新状态与执行纸面交易逻辑

## 测试

```bash
python3 -m unittest discover -s tests
```

## 建议优先改哪些地方

如果你想把它做成自己的系统，优先改这几层：

1. `TRADING_STRATEGY.md`：把交易风格写清楚
2. `config.json`：把账户、市场、标的池、风险参数写进去
3. `core/market_data.py`：接入你信任的数据源
4. `core/strategy.py`：实现你的候选评分与进场逻辑
5. `core/discipline.py`：实现你的风控与退出规则
6. `static/`：调整 UI 风格与信息架构

## 风险提示

这个项目当前定位是：

- **研究工具**
- **模拟交易框架**
- **风险与状态可视化面板**

它不是：

- 券商实盘交易系统
- 投资建议服务
- 收益承诺工具

如果你后续要接入实盘，至少还需要补齐：

- broker adapter
- 权限隔离
- 二次确认
- 风险熔断
- 审计日志
- 异常回滚与告警
