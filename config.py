"""
HyperHedge 配置文件
"""

# ===== 交易对配置 =====
SYMBOL_SILVER = "xyz:SILVER"  # Silver 代码 (正确)
SYMBOL_GOLD = "xyz:GOLD"   # Gold 代码

# ===== K线周期 =====
INTERVAL = "15m"          # 15分钟K线

# ===== 策略参数 =====
LOOKBACK = 24            # Z-score 计算回看周期
ENTRY_SHORT = 2.0        # Short 入场阈值 (Z-score > 2.0)
ENTRY_LONG = -2.5         # Long 入场阈值 (Z-score < -2.5)
EXIT_THRESH = 0.1         # 出场阈值 (Z-score 回归到 ±0.1 以内)

# ===== 模拟/实盘模式 =====
SIMULATION_MODE = True    # True = 模拟盘, False = 实盘

# ===== API 配置 =====
API_BASE_URL = "https://api.hyperliquid.xyz/info"
PROXY = "http://127.0.0.1:7890"

# ===== 数据保存 =====
DATA_DIR = "hisdata"
SAVE_INTERVAL = 100      # 每多少根K线保存一次

# ===== 风控参数 =====
MAX_POSITION_IMBALANCE = 0.1  # 允许的最大仓位不平衡比例
RECONNECT_DELAY = 5           # 重连延迟(秒)
ALERT_THRESHOLD = 3           # 连续异常次数告警阈值

# ===== 仪表盘刷新间隔 =====
DASHBOARD_REFRESH = 5         # 秒
