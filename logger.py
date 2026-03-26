"""
日志系统 - 统一的日志记录
"""
import logging
import os
from datetime import datetime
from pathlib import Path

# 日志目录
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# 创建日志格式
LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 主日志器
logger = logging.getLogger("hyperHedge")
logger.setLevel(logging.DEBUG)

# 文件处理器 - 记录所有日志
file_handler = logging.FileHandler(
    LOG_DIR / f"hyperHedge_{datetime.now().strftime('%Y%m%d')}.log",
    encoding="utf-8"
)
file_handler.setLevel(logging.DEBUG)
file_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

# 控制台处理器 - 记录 INFO 及以上
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)
console_handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))

logger.addHandler(file_handler)
logger.addHandler(console_handler)


class TradeLogger:
    """交易专用日志器"""
    
    def __init__(self):
        self.trade_log = logging.getLogger("hyperHedge.trade")
        self.trade_log.setLevel(logging.DEBUG)
        
        # 交易日志文件
        trade_file = LOG_DIR / f"trades_{datetime.now().strftime('%Y%m%d')}.log"
        handler = logging.FileHandler(trade_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        self.trade_log.addHandler(handler)
    
    def log_signal(self, signal: dict):
        """记录交易信号"""
        spread = signal.get('spread', 0)
        self.trade_log.info(
            f" SIGNAL | {signal.get('direction', 'N/A')} | "
            f"Z-score: {signal.get('zscore', 0):.4f} | "
            f"Spread: {spread:.6f} | "
            f"SILVER: {signal.get('silver_price', 0):.4f} | "
            f"GOLD: {signal.get('gold_price', 0):.4f}"
        )
    
    def log_order(self, order: dict):
        """记录下单"""
        self.trade_log.info(
            f" ORDER  | {order.get('type', 'N/A')} | "
            f"{order.get('symbol', 'N/A')} | "
            f"Price: {order.get('price', 0):.4f} | "
            f"Qty: {order.get('qty', 0):.4f} | "
            f"Mode: {order.get('mode', 'SIM')}"
        )
    
    def log_exit(self, position: dict):
        """记录平仓"""
        self.trade_log.info(
            f" EXIT   | {position.get('symbol', 'N/A')} | "
            f"PnL: {position.get('pnl', 0):.4f} | "
            f"Reason: {position.get('reason', 'N/A')}"
        )
    
    def log_pnl(self, pnl_info: dict):
        """
        记录盈亏信息
        
        Args:
            pnl_info: {
                'realized_pnl': float,
                'unrealized_pnl': float,
                'total_pnl': float,
                'position_value': float,
                'return_pct': float
            }
        """
        self.trade_log.info(
            f" PnL    | 已实现: ${pnl_info.get('realized_pnl', 0):>10.4f} | "
            f"未实现: ${pnl_info.get('unrealized_pnl', 0):>10.4f} | "
            f"总计: ${pnl_info.get('total_pnl', 0):>10.4f} | "
            f"收益率: {pnl_info.get('return_pct', 0):>8.2f}%"
        )


class RiskLogger:
    """风控专用日志器"""
    
    def __init__(self):
        self.risk_log = logging.getLogger("hyperHedge.risk")
        self.risk_log.setLevel(logging.DEBUG)
        
        risk_file = LOG_DIR / f"risk_{datetime.now().strftime('%Y%m%d')}.log"
        handler = logging.FileHandler(risk_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter(LOG_FORMAT, DATE_FORMAT))
        self.risk_log.addHandler(handler)
    
    def log_event(self, event_type: str, message: str):
        """记录风控事件"""
        self.risk_log.warning(f" {event_type} | {message}")
    
    def log_reconnect(self, attempt: int, success: bool):
        """记录重连"""
        status = "SUCCESS" if success else "FAILED"
        self.risk_log.info(f" RECONNECT | Attempt {attempt} | {status}")
    
    def log_position_check(self, positions: dict):
        """记录仓位检查"""
        imbalance = positions.get('imbalance', 0)
        status = "OK" if abs(imbalance) < 0.1 else "WARNING"
        self.risk_log.info(
            f" POSITION_CHECK | SILVER: {positions.get('silver', 0):.4f} | "
            f"GOLD: {positions.get('gold', 0):.4f} | "
            f"Imbalance: {imbalance:.4f} | {status}"
        )


# 导出
trade_logger = TradeLogger()
risk_logger = RiskLogger()
