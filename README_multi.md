# 多策略交易框架

一个支持**多策略并行运行**的交易框架，每个策略独立运行、独立仓位、统一风控。

---

## 架构说明

### 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         main.py                                  │
│                    (多策略入口/CLI)                               │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
    │ Strategy1   │  │ Strategy2   │  │ StrategyN   │
    │ (15m Silver)│  │ (1h Gold)   │  │ (...)       │
    └──────┬──────┘  └──────┬──────┘  └──────┬──────┘
           │               │               │
           └───────────────┼───────────────┘
                           ▼
                  ┌─────────────────┐
                  │   RiskManager   │
                  │   (统一风控)     │
                  └─────────────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │    Reporter     │
                  │   (状态汇报)     │
                  └─────────────────┘
```

### 文件职责

| 文件 | 职责 |
|------|------|
| `main.py` | 入口文件，解析命令行参数，根据 `--mode` 选择单/多策略模式 |
| `strategy_instance.py` | 单策略实例类，每个策略独立的数据、仓位、状态 |
| `strategy_manager.py` | 策略管理器，调度所有策略实例、汇总状态 |
| `risk_manager.py` | 统一风控，跨策略仓位控制、回撤保护、冷却机制 |
| `reporter.py` | 汇报模块，定期向 Feishu/Telegram 推送状态 |
| `config.py` | 配置文件，定义策略列表、风控参数、汇报设置 |

### 文件调用关系

```
main.py
  ├── config.py (读取配置)
  ├── strategy_manager.py (run_multi_mode)
  │     ├── strategy_instance.py (创建策略实例)
  │     └── risk_manager.py (风控检查)
  ├── strategy_instance.py (run_single_mode)
  └── reporter.py (状态汇报)
        └── risk_manager.py (获取全局状态)
```

---

## 核心模块说明

### 1. main.py（多策略入口）

**作用**：框架入口，支持单/多策略模式切换

**主要函数**：

- `run_single_mode(args)` - 单策略模式（向后兼容）
- `run_multi_mode(args)` - 多策略模式
- `main()` - 命令行参数解析

**命令行参数**：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--mode` | 运行模式：`single` 或 `multi` | config.py 中的 `RUN_MODE` |
| `--dir` | 状态文件目录 | 当前目录 |
| `--test` | 测试模式：运行一次循环后退出 | False |
| `--interval` | 运行间隔（秒） | 60 |

---

### 2. strategy_instance.py（单策略实例）

**作用**：每个策略的独立实例，维护自己的数据、仓位、状态

**核心方法**：

| 方法 | 说明 |
|------|------|
| `__init__(config, base_dir)` | 初始化策略，加载状态文件 |
| `get_data(limit)` | 获取 K 线数据 |
| `calculate_signal(data)` | 计算交易信号（`long`/`short`/`neutral`） |
| `calculate_zscore(data)` | 计算 Z-score 指标 |
| `should_close_position(data)` | 检查是否需要平仓 |
| `execute_trade(action, price, risk_manager)` | 执行交易 |
| `get_status()` | 获取策略状态 |
| `save_state()` / `_load_state()` | 持久化状态 |

**状态结构**：

```python
{
    "name": "策略名称",
    "position": 1.0,        # 仓位: 1=做多, -1=做空, 0=空仓
    "entry_price": 0.0,    # 入场价格
    "last_signal": "neutral",
    "trade_count": 0,      # 交易次数
    "pnl": 0.0,            # 已实现盈亏
    "equity_curve": [],    # 权益曲线
}
```

---

### 3. strategy_manager.py（策略管理器）

**作用**：管理所有策略实例，协调交易执行，汇总全局状态

**核心方法**：

| 方法 | 说明 |
|------|------|
| `__init__(config, risk_config, base_dir)` | 初始化，创建所有策略实例 |
| `get_strategy(name)` | 获取指定策略 |
| `get_all_strategies()` | 获取所有策略 |
| `run_single_cycle()` | 运行一次交易周期 |
| `_run_strategy_cycle(strategy)` | 执行单个策略 |
| `start(interval_seconds)` | 启动后台运行 |
| `stop()` | 停止运行，保存状态 |
| `get_status()` | 获取全局状态 |
| `print_status()` | 打印状态报告 |

---

### 4. risk_manager.py（统一风控）

**作用**：跨策略风控，确保整体仓位安全

**核心方法**：

| 方法 | 说明 |
|------|------|
| `can_trade(strategy_name, action)` | 检查是否允许交易 |
| `register_strategy(strategy)` | 注册策略实例 |
| `record_trade(strategy_name)` | 记录交易时间（冷却用） |
| `update_equity(pnl)` | 更新权益，计算回撤 |
| `get_global_status()` | 获取全局风控状态 |
| `should_emergency_close()` | 是否需要紧急平仓 |
| `emergency_close_all()` | 强制平仓所有仓位 |

**风控规则**：

1. **冷却机制**：`cooldown_seconds` 内同一策略不能重复交易
2. **总仓位限制**：`max_total_exposure` 控制整体仓位上限
3. **单策略仓位**：`max_position_per_strategy` 限制单策略仓位
4. **回撤保护**：`max_drawdown_pct` 超过后停止开仓

---

### 5. reporter.py（汇报模块）

**作用**：定期向 Feishu/Telegram 推送策略状态

**核心方法**：

| 方法 | 说明 |
|------|------|
| `start()` | 启动汇报线程 |
| `stop()` | 停止汇报 |
| `report()` | 执行单次汇报 |
| `_build_message(status)` | 构建消息内容 |
| `_send_to_feishu(message)` | 发送到飞书 |
| `_send_to_telegram(message)` | 发送到 Telegram |

---

### 6. config.py（配置文件）

**作用**：集中管理所有配置项

**主要配置项**：

```python
# 单策略配置（向后兼容）
SINGLE_STRATEGY = {...}

# 多策略配置
STRATEGIES = [...]

# 风控配置
RISK_CONFIG = {...}

# 汇报配置
REPORTING_CONFIG = {...}

# 运行模式
RUN_MODE = "multi"
```

---

## 配置说明

### STRATEGIES 配置格式

```python
STRATEGIES = [
    {
        "name": "策略唯一名称",
        "pair": ("做多币种", "做空币种"),  # 如 ("xyz:SILVER", "xyz:GOLD")
        "interval": "K线周期",              # 如 "15m", "1h", "4h"
        "entry_short": 2.0,                 # Z-score > 此值做空
        "entry_long": -2.5,                 # Z-score < 此值做多
        "exit_thresh": 0.1,                 # Z-score 回归到此范围平仓
        "lookback": 24,                     # 回顾周期（K线根数）
    },
    # 可添加更多策略...
]
```

### 参数含义

| 参数 | 说明 | 示例值 |
|------|------|--------|
| `name` | 策略唯一标识 | `silver_gold_15m` |
| `pair` | 交易对 (做多, 做空) | `("xyz:SILVER", "xyz:GOLD")` |
| `interval` | K线周期 | `"15m"`, `"1h"`, `"4h"` |
| `entry_short` | 做空阈值（Z-score） | `2.0` |
| `entry_long` | 做多阈值（Z-score） | `-2.5` |
| `exit_thresh` | 平仓阈值（Z-score） | `0.1` |
| `lookback` | 统计回看根数 | `24` |

### RISK_CONFIG 参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `max_total_exposure` | 最大总仓位（1.0=100%） | `1.0` |
| `max_position_per_strategy` | 单策略最大仓位 | `0.5` |
| `max_drawdown_pct` | 最大回撤限制 | `0.15` |
| `stop_loss_pct` | 止损线 | `0.05` |
| `cooldown_seconds` | 交易冷却时间（秒） | `300` |

### 添加新策略

在 `config.py` 的 `STRATEGIES` 列表中添加新条目：

```python
STRATEGIES = [
    # 现有策略...
    {
        "name": "new_strategy",
        "pair": ("xyz:BTC", "xyz:ETH"),
        "interval": "1h",
        "entry_short": 1.5,
        "entry_long": -1.8,
        "exit_thresh": 0.2,
        "lookback": 48,
    },
]
```

---

## 运行方式

### 模式选择

框架支持两种运行模式，通过 `--mode` 参数指定：

| 模式 | 说明 |
|------|------|
| `single` | 单策略模式，使用 `SINGLE_STRATEGY` 配置 |
| `multi` | 多策略模式，使用 `STRATEGIES` 配置 |

默认模式在 `config.py` 中设置：`RUN_MODE = "multi"`

### 启动命令

```bash
# 多策略模式（默认）
python main.py

# 指定模式
python main.py --mode multi

# 测试模式（运行一次循环）
python main.py --mode multi --test

# 自定义间隔（秒）
python main.py --interval 30

# 指定状态文件目录
python main.py --dir /path/to/states
```

### 运行流程

**测试模式**：
```bash
python main.py --test
# 输出各策略信号、价格、仓位、操作
```

**持续运行**：
```bash
python main.py
# 后台循环执行，每 60 秒一次
```

---

## 仪表盘

### 状态显示

运行时会打印多策略状态：

```
============================================================
策略管理器状态 - 2026-03-23 00:50:00
============================================================

运行状态: 运行中
策略数量: 2

--- 策略详情 ---

[silver_gold_15m]
  交易对: ('xyz:SILVER', 'xyz:GOLD'), 周期: 15m
  Z-Score: 1.23
  仓位: 1, 入场价: 1850.5000
  信号: long, 交易次数: 5
  盈亏: 125.50

[gold_silver_1h]
  交易对: ('xyz:GOLD', 'xyz:SILVER'), 周期: 1h
  Z-Score: -0.85
  仓位: 0, 入场价: 0.0000
  信号: neutral, 交易次数: 3
  盈亏: -20.30

--- 风控状态 ---
  总仓位: 50% / 100%
  总盈亏: 105.20
  最大回撤: 3.2% / 15%
  活跃仓位: 1

============================================================
```

### 关键指标

| 指标 | 说明 |
|------|------|
| Z-Score | 价格相对均值偏离程度 |
| 仓位 | 1=做多, -1=做空, 0=空仓 |
| 信号 | long/short/neutral |
| 总仓位 | 所有策略总暴露度 |
| 最大回撤 | 当前回撤与峰值之比 |

---

## 状态持久化

每个策略实例独立保存状态文件：

```
state_{策略名称}.json
```

示例：`state_silver_gold_15m.json`

```json
{
  "name": "silver_gold_15m",
  "position": 1,
  "entry_price": 1850.5,
  "last_signal": "long",
  "last_update": "2026-03-23T00:50:00",
  "trade_count": 5,
  "pnl": 125.5
}
```

---

## 扩展开发

### 添加新数据源

修改 `strategy_instance.py` 中的 `get_data()` 方法：

```python
def get_data(self, limit: int = None) -> list:
    limit = limit or self.lookback
    # 替换为真实数据获取
    data = fetch_from_your_api(self.pair, self.interval, limit)
    return data
```

### 添加新指标

在 `strategy_instance.py` 中添加：

```python
def calculate_rsi(self, data: list, period: int = 14) -> float:
    """计算 RSI 指标"""
    # 实现 RSI 计算
    pass

def calculate_bollinger_bands(self, data: list, period: int = 20):
    """计算布林带"""
    # 实现布林带计算
    pass
```

### 自定义风控规则

在 `risk_manager.py` 中扩展 `can_trade()` 方法：

```python
def can_trade(self, strategy_name: str, action: str) -> bool:
    # 原有检查...
    
    # 新增自定义规则
    if not self._check_custom_rule(strategy_name):
        return False
    
    return True
```

---

## 文件结构

```
.
├── main.py                 # 入口文件
├── strategy_instance.py    # 策略实例类
├── strategy_manager.py     # 策略管理器
├── risk_manager.py        # 风控模块
├── reporter.py            # 汇报模块
├── config.py              # 配置文件
├── state_*.json           # 策略状态文件（运行时生成）
└── README.md             # 本文档
```

---

## 快速开始

```bash
# 1. 配置策略（编辑 config.py）
#    - 在 STRATEGIES 中添加策略
#    - 调整 RISK_CONFIG 风控参数

# 2. 测试运行
python main.py --test

# 3. 启动持续运行
python main.py
```
