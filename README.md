# HyperHedge 配对交易系统文档

## 1. 整体架构介绍

### 1.1 策略概述

HyperHedge 是一个基于 **Z-Score 均值回归** 的 Silver/Gold 配对交易策略系统，运行在 Hyperliquid 交易所。

**核心逻辑**：
- **配对交易**：同时交易 Silver (S) 和 Gold (PAXG) 两种资产，利用它们之间的价格相关性
- **价差分析**：计算 Silver/Gold 价格比率 (Spread)，当价差偏离历史均值时产生交易信号
- **均值回归**：当 Z-Score 偏离阈值时开仓，回归时平仓，预期价差会回到均值

**交易规则**：
| 信号 | 条件 | 操作 |
|------|------|------|
| SHORT_SILVER | Z-score > 2.0 | 做空 Silver，做多 Gold |
| LONG_SILVER | Z-score < -2.5 | 做多 Silver，做空 Gold |
| CLOSE_ALL | Z-score 回归到 ±0.1 | 全部平仓 |

### 1.2 系统架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         HyperHedge                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐      │
│  │  DataManager │───▶│   Strategy   │───▶│TradingEngine │      │
│  │  (数据获取)   │    │  (信号生成)   │    │  (订单执行)   │      │
│  └──────────────┘    └──────────────┘    └──────────────┘      │
│         │                   │                   │               │
│         ▼                   ▼                   ▼               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                      RiskManager                         │   │
│  │              (风控检查、告警、状态恢复)                     │   │
│  └──────────────────────────────────────────────────────────┘   │
│                              │                                   │
│                              ▼                                   │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │                       Dashboard                           │   │
│  │                    (实时状态显示)                          │   │
│  └──────────────────────────────────────────────────────────┘   │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 1.3 数据流

```
API (Hyperliquid) 
      │
      ▼
DataManager.fetch_realtime_klines() 
      │
      ├─▶ silver_data DataFrame
      └─▶ gold_data DataFrame
              │
              ▼
      DataManager.get_spread_series()
              │
              ▼
      Strategy.calculate_zscore()
              │
              ▼
      Strategy.generate_signal() ──▶ TradingEngine.execute_order()
              │
              ▼
      RiskManager.check_position_alignment()
              │
              ▼
      Dashboard.render()
```

---

## 2. 目录结构

```
hyperHedge/
├── main.py              # 主程序入口，包含主循环和状态管理
├── strategy.py          # 策略逻辑：Z-score 计算、信号生成
├── trading.py           # 交易引擎：订单执行、持仓管理
├── data_manager.py      # 数据管理：K线获取、历史数据加载
├── risk_manager.py      # 风险管理：风控检查、告警、重连
├── config.py            # 配置文件：所有参数配置
├── logger.py            # 日志系统：主日志/交易日志/风控日志
├── dashboard.py         # 仪表盘：终端 UI 显示
├── state.json           # 状态文件：断点续跑用
├── hisdata/             # 历史数据目录
│   ├── SILVER.csv       # Silver 历史 K线
│   └── GOLD.csv         # Gold 历史 K线
└── logs/                # 日志目录
    ├── hyperHedge_YYYYMMDD.log
    ├── trades_YYYYMMDD.log
    └── risk_YYYYMMDD.log
```

---

## 3. 核心模块说明

### 3.1 main.py - 主程序入口

**职责**：系统初始化、主循环控制、断点续跑、信号处理

**主要类**：`HyperHedge`

**关键方法**：

| 方法 | 功能 |
|------|------|
| `__init__()` | 初始化所有模块、设置信号处理 |
| `initialize(resume)` | 初始化数据，可选断点续跑 |
| `run(interval)` | 主循环，每 interval 秒执行一次 |
| `run_once()` | 执行单次交易循环 |
| `save_state()` | 保存状态到 JSON 文件 |
| `load_state()` | 从 JSON 文件加载状态 |
| `restore_position_state()` | 恢复仓位状态 |
| `check_and_fill_gaps()` | 检查并补全缺失的 K 线数据 |
| `cleanup()` | 退出前保存数据 |

**运行模式**：
```bash
# 交易模式 (默认)
python main.py --mode trade --interval 60

# 仪表盘模式 (只看不交易)
python main.py --mode dashboard

# 测试连接
python main.py --mode test

# 实盘模式
python main.py --real
```

---

### 3.2 strategy.py - 策略逻辑

**职责**：Z-score 计算、交易信号生成、仓位计算

**主要类**：`PairTradingStrategy`

**关键方法**：

| 方法 | 输入 | 输出 | 功能 |
|------|------|------|------|
| `calculate_zscore(spread_series)` | pd.Series | pd.Series | 计算滚动 Z-score |
| `generate_signal(zscore, position, prices, spread)` | float, dict, dict, float | (str, str) | 生成交易信号 |
| `get_position_size(direction, capital)` | str, float | dict | 计算开仓数量 |
| `get_status()` | - | dict | 获取策略状态 |

**Z-score 计算公式**：
```
Z-score = (spread - rolling_mean) / rolling_std
```
- `spread` = Silver / Gold 价格比率
- `rolling_mean` = 过去 24 根 K 线的均值
- `rolling_std` = 过去 24 根 K 线的标准差

**信号生成逻辑**：
```
Z-score > 2.0  ─────────────────────────▶ SHORT_SILVER (做空 Silver，做多 Gold)
Z-score < -2.5 ─────────────────────────▶ LONG_SILVER  (做多 Silver，做空 Gold)

持仓期间:
  做空入场: Z-score < 0.1 或回落 50%  ──▶ CLOSE_ALL
  做多入场: Z-score > -0.1            ──▶ CLOSE_ALL
```

---

### 3.3 trading.py - 交易引擎

**职责**：订单执行、持仓管理、模拟/实盘切换

**主要类**：`TradingEngine`

**关键方法**：

| 方法 | 输入 | 输出 | 功能 |
|------|------|------|------|
| `execute_order(direction, symbol, qty, price, type)` | str, str, float, float, str | dict | 执行订单 |
| `open_position(direction, prices)` | str, dict | bool | 开仓 |
| `close_position(prices)` | dict | bool | 平仓 |
| `get_positions()` | - | dict | 获取当前持仓 |
| `get_pnl(prices)` | dict | float | 计算未实现盈亏 |
| `check_position_balance()` | - | dict | 检查仓位平衡 |
| `set_target_positions(silver, gold)` | float, float | - | 设置目标仓位 |

**持仓结构**：
```python
positions = {
    'silver': float,   # 正=多头，负=空头
    'gold': float      # 正=多头，负=空头
}
```

---

### 3.4 data_manager.py - 数据管理

**职责**：历史数据加载、实时 K 线获取、数据保存

**主要类**：`DataManager`

**关键方法**：

| 方法 | 输入 | 输出 | 功能 |
|------|------|------|------|
| `__init__()` | - | - | 初始化，加载历史数据 |
| `fetch_realtime_klines(symbol, interval, limit)` | str, str, int | pd.DataFrame | 获取实时 K 线 |
| `update_data()` | - | bool | 更新历史+实时数据 |
| `save_data()` | - | - | 保存数据到 CSV |
| `get_latest_prices()` | - | dict | 获取最新价格 |
| `get_spread_series()` | - | pd.Series | 获取 Silver/Gold 价差序列 |
| `is_data_ready(min_bars)` | int | bool | 检查数据是否足够 |

**数据格式** (DataFrame)：
```
timestamp  |  open  |  high  |  low  |  close  |  volume
------------|--------|--------|-------|---------|----------
2024-01-01  | 23.50 | 23.80  | 23.40 | 23.70   | 1000000
```

---

### 3.5 risk_manager.py - 风险管理

**职责**：风控检查、告警、网络重连、仓位对齐

**主要类**：`RiskManager`

**关键方法**：

| 方法 | 输入 | 输出 | 功能 |
|------|------|------|------|
| `check_connection()` | - | bool | 检查网络连接 |
| `_attempt_reconnect()` | - | - | 尝试重连 |
| `check_position_alignment()` | - | bool | 检查仓位是否平衡 |
| `validate_signal(signal, prices)` | str, dict | bool | 验证信号有效性 |
| `check_data_freshness(max_age_seconds)` | int | bool | 检查数据时效性 |
| `heartbeat()` | - | - | 定期心跳检查 |
| `get_status()` | - | dict | 获取风控状态 |
| `set_alert_callback(callback)` | Callable | - | 设置告警回调 |

**风控规则**：
1. **仓位平衡**：Silver 和 Gold 必须同时持仓，不允许单边
2. **数据时效**：数据必须小于 5 分钟
3. **价格有效**：价格必须为正数
4. **网络连接**：连续 3 次错误触发告警

---

### 3.6 config.py - 配置

所有系统配置参数，详见第 6 节。

---

### 3.7 logger.py - 日志系统

**职责**：统一日志记录，分为三个日志器

**日志器**：

| 日志器 | 用途 | 文件 |
|--------|------|------|
| `logger` | 主日志 | `logs/hyperHedge_YYYYMMDD.log` |
| `trade_logger` | 交易日志 | `logs/trades_YYYYMMDD.log` |
| `risk_logger` | 风控日志 | `logs/risk_YYYYMMDD.log` |

**关键函数**：

| 函数 | 功能 |
|------|------|
| `trade_logger.log_signal(signal)` | 记录交易信号 |
| `trade_logger.log_order(order)` | 记录订单 |
| `trade_logger.log_exit(position)` | 记录平仓 |
| `risk_logger.log_event(type, message)` | 记录风控事件 |
| `risk_logger.log_reconnect(attempt, success)` | 记录重连 |
| `risk_logger.log_position_check(positions)` | 记录仓位检查 |

---

### 3.8 dashboard.py - 仪表盘

**职责**：终端实时显示交易状态

**主要类**：`Dashboard`

**关键方法**：

| 方法 | 功能 |
|------|------|
| `render()` | 渲染完整仪表盘 (清屏 + 打印) |
| `render_simple()` | 渲染简洁版 (返回字符串) |
| `get_status_summary()` | 获取状态摘要字典 |

**显示内容**：
- 📊 市场数据 (Silver/Gold 价格)
- 🎯 策略状态 (Z-score、信号、阈值)
- 💼 持仓状态 (仓位方向、数量、市值)
- 🛡️ 风控状态 (连接、平衡度)
- 📜 最近信号 (最近 5 笔订单)

---

## 4. 关键函数说明

### 4.1 main.py 关键函数

#### `save_state(filepath: str = None) -> bool`

保存当前运行状态到 JSON 文件，用于断点续跑。

**输入**：
- `filepath`: 状态文件路径 (默认 `state.json`)

**输出**：
- `bool`: 是否保存成功

**保存内容**：
```json
{
  "position": {"silver": 0.0, "gold": 0.0},
  "entry_zscore": 2.1,
  "entry_direction": "SHORT_SILVER",
  "iteration": 150,
  "timestamp": "2024-01-15T10:30:00"
}
```

---

#### `load_state(filepath: str = None) -> dict`

从 JSON 文件加载状态。

**输入**：
- `filepath`: 状态文件路径

**输出**：
- `dict`: 状态字典，不存在则返回 `None`

---

#### `restore_position_state(state: dict)`

恢复策略和仓位状态。

**输入**：
- `state`: 状态字典

**处理**：
1. 恢复 `strategy.entry_zscore` 和 `entry_direction`
2. 恢复 `trading_engine.positions`
3. 恢复 `iteration` 计数

---

#### `check_and_fill_gaps() -> list`

检查数据完整性并补全缺失的 K 线。

**输出**：
- `list`: 缺失时间段列表 `[(start, end), ...]`

**处理**：
1. 遍历时间序列找出断点
2. 从 API 获取缺失时间段的数据
3. 合并到现有数据并去重
4. 保存到 CSV

---

#### `run_once() -> bool`

执行单次交易循环。

**处理流程**：
```
1. update_data()           # 更新 K 线数据
2. get_latest_prices()    # 获取最新价格
3. get_spread_series()    # 计算价差
4. calculate_zscore()     # 计算 Z-score
5. generate_signal()      # 生成信号
6. open/close_position()  # 执行交易
7. check_position_alignment() # 风控检查
8. save_data()            # 定期保存数据
9. save_state()           # 定期保存状态
```

---

### 4.2 strategy.py 关键函数

#### `calculate_zscore(spread_series: pd.Series) -> pd.Series`

计算 Z-score 序列。

**输入**：
- `spread_series`: Silver/Gold 价差序列

**输出**：
- `pd.Series`: Z-score 序列

**计算公式**：
```python
rolling_mean = spread.rolling(window=LOOKBACK).mean()
rolling_std = spread.rolling(window=LOOKBACK).std()
zscore = (spread - rolling_mean) / rolling_std
```

---

#### `generate_signal(zscore, position, prices, spread) -> Tuple[str, str]`

生成交易信号。

**输入**：
- `zscore`: 当前 Z-score
- `position`: 当前持仓 `{'silver': float, 'gold': float}`
- `prices`: 当前价格
- `spread`: 当前价差

**输出**：
- `(direction, reason)`: 信号方向和原因

**信号规则**：
| 条件 | 信号 | 原因 |
|------|------|------|
| `zscore > 2.0` 且无持仓 | SHORT_SILVER | Z-score 偏离正向 |
| `zscore < -2.5` 且无持仓 | LONG_SILVER | Z-score 偏离负向 |
| 做空持仓且 `zscore < 0.1` | CLOSE_ALL | 均值回归 |
| 做空持仓且回落 > 50% | CLOSE_ALL | 盈利目标 |
| 做多持仓且 `zscore > -0.1` | CLOSE_ALL | 均值回归 |
| 其他 | HOLD | 等待 |

---

### 4.3 trading.py 关键函数

#### `execute_order(direction, symbol, qty, price, order_type) -> dict`

执行订单。

**输入**：
- `direction`: 'BUY' 或 'SELL'
- `symbol`: 'silver' 或 'gold'
- `qty`: 数量
- `price`: 价格
- `order_type`: 'market' 或 'limit'

**输出**：
- `dict`: 订单结果

**处理**：
- 模拟盘：直接更新持仓
- 实盘：TODO 调用 Hyperliquid API

---

#### `open_position(direction, prices) -> bool`

开仓。

**输入**：
- `direction`: 'SHORT_SILVER' 或 'LONG_SILVER'
- `prices`: 价格字典

**处理**：
- SHORT_SILVER: 做空 Silver + 做多 Gold
- LONG_SILVER: 做多 Silver + 做空 Gold

---

### 4.4 data_manager.py 关键函数

#### `fetch_realtime_klines(symbol, interval, limit) -> pd.DataFrame`

获取实时 K 线数据。

**输入**：
- `symbol`: 交易对代码 (如 "xyz:SILVER")
- `interval`: K 线周期 ("15m")
- `limit`: 获取数量

**输出**：
- `pd.DataFrame`: K 线数据

**API 请求**：
```python
payload = {
    "type": "candleSnapshot",
    "req": {
        "coin": symbol,
        "interval": interval,
        "startTime": start_time,
        "endTime": end_time
    }
}
```

---

#### `get_spread_series() -> pd.Series`

获取价差序列。

**输出**：
- `pd.Series`: Silver / Gold 价格比率

**处理**：
1. 按 timestamp 内联合并数据
2. 计算 `silver / gold` 比率

---

## 5. 状态恢复功能

### 5.1 断点续跑机制

当程序因断电、网络中断等原因停止后，重新启动时可恢复之前的运行状态。

### 5.2 恢复流程

```
启动程序
      │
      ▼
initialize(resume=True)
      │
      ├─▶ 1. check_and_fill_gaps()  ── 检查并补全缺失数据
      │
      ├─▶ 2. load_state()          ── 加载 state.json
      │
      ├─▶ 3. restore_position_state() ── 恢复策略和持仓状态
      │
      └─▶ 4. update_data()         ── 获取最新数据
                │
                ▼
           开始运行 (从上次迭代继续)
```

### 5.3 恢复内容

| 状态项 | 说明 |
|--------|------|
| `position.silver` | Silver 持仓数量 |
| `position.gold` | Gold 持仓数量 |
| `entry_zscore` | 入场时的 Z-score |
| `entry_direction` | 入场方向 (SHORT_SILVER/LONG_SILVER) |
| `iteration` | 已完成的迭代次数 |

### 5.4 自动保存

- 每 `SAVE_INTERVAL` (默认 100 次循环) 保存一次状态
- 程序退出时 (`cleanup()`) 也会保存
- 数据文件 (`hisdata/SILVER.csv`, `GOLD.csv`) 也会定期保存

### 5.5 手动恢复

如果需要强制从头开始运行：

```bash
# 方法 1: 删除状态文件
rm state.json

# 方法 2: 修改 main.py 中 initialize() 的参数
app.initialize(resume=False)
```

---

## 6. 配置参数说明

### 6.1 交易对配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `SYMBOL_SILVER` | str | `"xyz:SILVER"` | Silver 交易代码 |
| `SYMBOL_GOLD` | str | `"xyz:GOLD"` | Gold 交易代码 |

### 6.2 K线周期

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `INTERVAL` | str | `"15m"` | K线周期 (1m/5m/15m/1h 等) |

### 6.3 策略参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `LOOKBACK` | int | `24` | Z-score 计算回看周期 (24 根 15m K线 = 6 小时) |
| `ENTRY_SHORT` | float | `2.0` | 做空入场阈值 (Z-score > 2.0) |
| `ENTRY_LONG` | float | `-2.5` | 做多入场阈值 (Z-score < -2.5) |
| `EXIT_THRESH` | float | `0.1` | 出场阈值 (Z-score 回归到 ±0.1) |

### 6.4 模拟/实盘模式

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `SIMULATION_MODE` | bool | `True` | True=模拟盘, False=实盘 |

### 6.5 API 配置

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `API_BASE_URL` | str | `"https://api.hyperliquid.xyz/info"` | Hyperliquid API 地址 |
| `PROXY` | str | `"http://127.0.0.1:7890"` | 代理服务器地址 |

### 6.6 数据保存

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `DATA_DIR` | str | `"hisdata"` | 历史数据目录 |
| `SAVE_INTERVAL` | int | `100` | 每多少次迭代保存一次 |

### 6.7 风控参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `MAX_POSITION_IMBALANCE` | float | `0.1` | 允许的最大仓位不平衡比例 (10%) |
| `RECONNECT_DELAY` | int | `5` | 重连延迟 (秒) |
| `ALERT_THRESHOLD` | int | `3` | 连续异常次数告警阈值 |

### 6.8 仪表盘

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `DASHBOARD_REFRESH` | int | `5` | 仪表盘刷新间隔 (秒) |

---

## 7. 依赖

```
pandas
numpy
requests
```

安装依赖：
```bash
pip install pandas numpy requests
```

---

## 8. 快速开始

```bash
# 1. 进入目录
cd hyperHedge

# 2. 运行交易 (模拟盘)
python main.py --mode trade

# 2. 仅查看仪表盘
python main.py --mode dashboard

# 3. 测试 API 连接
python main.py --mode test

# 4. 启用实盘
python main.py --mode trade --real
```

---

*文档生成时间: 2024*
