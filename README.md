# Stock Lab Framework

> **免责声明 / Disclaimer**
>
> 本项目仅作为**本地部署的股票研究、状态可视化与模拟交易框架**，用于技术交流、界面实验、策略工程练习与个人学习。
>
> - **不构成任何投资建议、证券推荐或收益承诺**
> - **不提供实盘托管、代客理财或自动荐股服务**
> - 使用者应自行判断、自行承担风险，并在接入真实资金前完成独立验证、风控与合规评估
>
> This repository is provided for **educational and framework-sharing purposes only**. It is **not financial advice**.

一个面向本地部署的股票研究与模拟交易框架，支持：

- 多市场 watchlist（A / HK / US）
- 模拟账户与订单状态
- 可视化 dashboard / mobile dashboard
- 可扩展的数据源、策略与风控模块
- 定时生成状态与本地查看

## 目录结构

```text
stock_lab/
├── core/
├── static/
├── tests/
├── scripts/
├── .env.example
├── config.example.json
└── PROJECT_AUDIT.md
```

## 安装

### Linux

```bash
python3 -m venv .venv
.venv/bin/python -m ensurepip --upgrade
.venv/bin/python -m pip install -r requirements.txt
```

### Windows

```bash
python -m venv .venv
.venv\Scripts\python -m ensurepip --upgrade
.venv\Scripts\python -m pip install -r requirements.txt
```

## 启动

生成状态：

```bash
.venv/bin/python trading_engine.py
```

启动看板（推荐，固定使用项目自己的解释器，不吃当前 shell 的 PATH 污染）：

```bash
./scripts/start-dashboard.sh
```

如果要改端口：

```bash
STOCK_LAB_PORT=8877 ./scripts/start-dashboard.sh
```

默认地址：

- `http://127.0.0.1:8765/dashboard`
- `http://127.0.0.1:8765/m`
- `http://127.0.0.1:8765/api/state`

## 环境排查

如果怀疑 `python/pip` 串了环境，运行：

```bash
./scripts/env-doctor.sh
```

安装依赖时，优先使用：

```bash
.venv/bin/python -m pip install <package>
```

不要盲信裸 `pip install`，否则很容易装进别的虚拟环境。

## 配置方式

复制示例配置后，按自己的市场、观察池和风险参数调整：

```bash
cp config.example.json config.json
```

说明：`config.example.json` 里的示例标的只使用宽基 / 指数 ETF 作为占位样本，目的是帮助你验证流程，不代表任何个股或交易推荐。

然后修改：

- `markets`
- `watchlists`
- `capital`
- `risk`
- `execution`

## 测试

```bash
.venv/bin/python -m unittest discover -s tests
```

## 二次开发建议

如果你想把它做成自己的系统，优先改这几层：

1. `core/config.py`：默认参数与账户结构
2. `core/market_data.py`：接入你信任的数据源
3. `core/strategy.py`：候选评分与进场逻辑
4. `core/discipline.py`：风控与退出规则
5. `static/`：UI 风格与页面布局

## 风险提示

更完整的英文免责声明见 [`DISCLAIMER.md`](./DISCLAIMER.md)。

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
