"""
风控管理器 - 仓位对齐、灾备、异常告警
"""
import time
from typing import Optional, Callable

import config
from logger import logger, risk_logger


class RiskManager:
    """风控管理器"""
    
    def __init__(self, data_manager, trading_engine):
        self.data_manager = data_manager
        self.trading_engine = trading_engine
        
        # 状态跟踪
        self.consecutive_errors = 0
        self.last_heartbeat = time.time()
        self.is_connected = True
        
        # 回调函数 (可选)
        self.on_alert: Optional[Callable] = None
        self.on_disconnect: Optional[Callable] = None
        self.on_reconnect: Optional[Callable] = None
    
    def check_connection(self) -> bool:
        """
        检查网络连接
        
        Returns:
            连接状态
        """
        try:
            # 尝试获取数据检测连接
            self.data_manager.fetch_realtime_klines(
                config.SYMBOL_SILVER, 
                limit=1
            )
            
            if not self.is_connected:
                self.is_connected = True
                risk_logger.log_reconnect(1, True)
                logger.info("网络重连成功")
                if self.on_reconnect:
                    self.on_reconnect()
            
            self.consecutive_errors = 0
            return True
            
        except Exception as e:
            self.consecutive_errors += 1
            self.is_connected = False
            
            if self.consecutive_errors >= config.ALERT_THRESHOLD:
                msg = f"连续 {self.consecutive_errors} 次网络错误: {e}"
                logger.error(msg)
                risk_logger.log_event("NETWORK_ERROR", msg)
                
                if self.on_alert:
                    self.on_alert(msg)
            
            # 尝试重连
            if self.consecutive_errors < 10:
                self._attempt_reconnect()
            
            return False
    
    def _attempt_reconnect(self):
        """尝试重连"""
        logger.info(f"尝试重连... (第 {self.consecutive_errors} 次)")
        
        for attempt in range(1, 4):
            try:
                time.sleep(config.RECONNECT_DELAY * attempt)
                self.data_manager.fetch_realtime_klines(
                    config.SYMBOL_SILVER,
                    limit=1
                )
                
                self.is_connected = True
                risk_logger.log_reconnect(attempt, True)
                logger.info(f"重连成功 (第 {attempt} 次)")
                
                if self.on_reconnect:
                    self.on_reconnect()
                
                self.consecutive_errors = 0
                return
                
            except Exception as e:
                risk_logger.log_reconnect(attempt, False)
                logger.warning(f"重连失败 (第 {attempt} 次): {e}")
        
        # 重连失败
        msg = "重连多次失败，请检查网络"
        logger.error(msg)
        risk_logger.log_event("RECONNECT_FAILED", msg)
        
        if self.on_alert:
            self.on_alert(msg)
    
    def check_position_alignment(self) -> bool:
        """
        检查仓位对齐 (配对交易需要 Silver/Gold 同时持仓)
        
        Returns:
            是否对齐
        """
        positions = self.trading_engine.get_positions()
        silver = positions.get('silver', 0)
        gold = positions.get('gold', 0)
        
        # 检查是否有单边持仓
        has_silver = silver != 0
        has_gold = gold != 0
        
        # 配对交易应该同时持仓
        if has_silver != has_gold:
            imbalance = positions.get('imbalance', 1.0)
            
            msg = f"仓位不平衡! SILVER: {silver:.4f}, GOLD: {gold:.4f}"
            logger.error(msg)
            risk_logger.log_event("POSITION_IMBALANCE", msg)
            risk_logger.log_position_check(positions)
            
            if self.on_alert:
                self.on_alert(msg)
            
            return False
        
        # 检查持仓比例是否合理
        balance_check = self.trading_engine.check_position_balance()
        
        if not balance_check['balanced']:
            msg = f"持仓比例异常! 不平衡度: {balance_check['imbalance']:.4f}"
            logger.warning(msg)
            risk_logger.log_event("POSITION_RATIO_WARNING", msg)
            risk_logger.log_position_check(positions)
        
        risk_logger.log_position_check(positions)
        return True
    
    def validate_signal(self, signal: str, prices: dict) -> bool:
        """
        验证信号是否有效
        
        Args:
            signal: 信号方向
            prices: 当前价格
        
        Returns:
            是否通过验证
        """
        # 价格有效性检查
        if not prices.get('silver') or prices['silver'] <= 0:
            msg = f"无效的 Silver 价格: {prices.get('silver')}"
            logger.error(msg)
            risk_logger.log_event("INVALID_PRICE", msg)
            return False
        
        if not prices.get('gold') or prices['gold'] <= 0:
            msg = f"无效的 Gold 价格: {prices.get('gold')}"
            logger.error(msg)
            risk_logger.log_event("INVALID_PRICE", msg)
            return False
        
        # 波动性检查 (可选)
        # 如果价格波动过大，可能有问题
        
        return True
    
    def check_data_freshness(self, max_age_seconds: int = 300) -> bool:
        """
        检查数据时效性
        
        Args:
            max_age_seconds: 最大允许的数据年龄(秒)
        
        Returns:
            数据是否新鲜
        """
        try:
            prices = self.data_manager.get_latest_prices()
            
            silver_time = prices.get('silver_time')
            gold_time = prices.get('gold_time')
            
            if silver_time is None or gold_time is None:
                msg = "无法获取数据时间"
                logger.error(msg)
                risk_logger.log_event("NO_DATA_TIME", msg)
                return False
            
            import pandas as pd
            now = pd.Timestamp.now(tz='UTC')
            silver_age = (now - silver_time).total_seconds()
            gold_age = (now - gold_time).total_seconds()
            
            if silver_age > max_age_seconds or gold_age > max_age_seconds:
                msg = f"数据过期! Silver: {silver_age:.0f}s, Gold: {gold_age:.0f}s"
                logger.warning(msg)
                risk_logger.log_event("STALE_DATA", msg)
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"数据时效检查失败: {e}")
            return False
    
    def heartbeat(self):
        """心跳 (定期调用)"""
        self.last_heartbeat = time.time()
        
        # 执行各项检查
        self.check_connection()
        self.check_data_freshness()
        
        if self.trading_engine.get_positions()['silver'] != 0:
            self.check_position_alignment()
    
    def get_status(self) -> dict:
        """获取风控状态"""
        positions = self.trading_engine.get_positions()
        balance = self.trading_engine.check_position_balance()
        
        return {
            'connected': self.is_connected,
            'consecutive_errors': self.consecutive_errors,
            'last_heartbeat': self.last_heartbeat,
            'position_silver': positions.get('silver', 0),
            'position_gold': positions.get('gold', 0),
            'position_balanced': balance['balanced'],
            'position_imbalance': balance.get('imbalance', 0)
        }
    
    def set_alert_callback(self, callback: Callable):
        """设置告警回调"""
        self.on_alert = callback
    
    def set_disconnect_callback(self, callback: Callable):
        """设置断开连接回调"""
        self.on_disconnect = callback
    
    def set_reconnect_callback(self, callback: Callable):
        """设置重连回调"""
        self.on_reconnect = callback
