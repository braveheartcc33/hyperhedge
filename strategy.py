"""
策略逻辑 - Silver/Gold 配对交易 Z-score 策略
"""
import pandas as pd
import numpy as np
from typing import Optional, Tuple

import config
from logger import logger, trade_logger


class PairTradingStrategy:
    """配对交易策略"""
    
    def __init__(self):
        self.lookback = config.LOOKBACK
        self.entry_short = config.ENTRY_SHORT
        self.entry_long = abs(config.ENTRY_LONG)  # 取绝对值
        self.exit_thresh = config.EXIT_THRESH
        
        # 缓存
        self.zscore: Optional[float] = None
        self.last_signal: Optional[str] = None
        # 记录入场时的 Z-score（用于计算回落幅度）
        self.entry_zscore: Optional[float] = None
        self.entry_direction: Optional[str] = None
        
        # 🐯 西蒙斯之虎要求：一笔交易结束后才能有下一笔交易
        # 添加交易冷却期，防止程序重启后错误加仓
        self.last_close_iteration: Optional[int] = None  # 上次平仓的轮次
        self.cooldown_rounds: int = 10  # 平仓后必须等待10轮才能开仓
        
        # 🐯 Bug修复: 防止同一轮次内重复开仓
        # 在 generate_signal 开头检查此标志，防止 20:44:47 开仓后 20:44:50 再次触发
        self.just_opened_this_iteration: bool = False
        
    def calculate_zscore(self, spread_series: pd.Series) -> pd.Series:
        """
        计算 Z-score
        
        Z-score = (spread - mean) / std
        
        使用滚动窗口计算
        """
        if len(spread_series) < self.lookback:
            return pd.Series()
        
        rolling_mean = spread_series.rolling(window=self.lookback).mean()
        rolling_std = spread_series.rolling(window=self.lookback).std()
        
        zscore = (spread_series - rolling_mean) / rolling_std
        
        return zscore
    
    def generate_signal(self, zscore: float, current_position: dict, 
                      prices: dict = None, spread: float = 0, iteration: int = 0) -> Tuple[str, str]:
        """
        生成交易信号
        
        Args:
            zscore: 当前 Z-score
            current_position: 当前持仓 {'silver': float, 'gold': float}
            prices: 当前价格 {'silver': float, 'gold': float}
            spread: 当前 spread
            iteration: 当前轮次（用于冷却期判断）
        
        Returns:
            (direction, reason)
            direction: 'LONG_SILVER', 'SHORT_SILVER', 'LONG_GOLD', 'SHORT_GOLD', 'CLOSE', 'HOLD'
        """
        # 🐯 存储轮次用于冷却期判断
        self.iteration = iteration
        silver_pos = current_position.get('silver', 0)
        gold_pos = current_position.get('gold', 0)
        has_position = silver_pos != 0 or gold_pos != 0
        
        # 🐯 Bug修复: 如果本轮已经开过仓，直接跳过，防止重复触发
        # 例如 20:44:47 开仓后，20:44:50 不会再触发
        if self.just_opened_this_iteration:
            logger.info(f"⏭️ 本轮已开仓，跳过信号检测 | iteration={iteration}")
            self.just_opened_this_iteration = False  # 重置，下轮可以再检测
            return ('HOLD', f'本轮已开仓，跳过')
        
        self.zscore = zscore
        
        silver_price = prices.get('silver', 0) if prices else 0
        gold_price = prices.get('gold', 0) if prices else 0
        
        # === 入场信号 ===
        
        # 🐯 西蒙斯之虎要求：一笔交易结束后必须等待冷却期才能开新仓
        # 检查是否在冷却期内
        in_cooldown = False
        if self.last_close_iteration is not None and self.iteration is not None:
            if self.iteration - self.last_close_iteration < self.cooldown_rounds:
                in_cooldown = True
                logger.info(f"⏳ 冷却期 | 平仓后需等待 {self.cooldown_rounds} 轮，当前轮次 {self.iteration}，已等待 {self.iteration - self.last_close_iteration} 轮")
        
        # Short 入场: Z-score > 2.0 (价差高于均值，做空 Silver，做多 Gold)
        if zscore > self.entry_short:
            if not has_position and not in_cooldown:
                self.entry_zscore = zscore  # 记录入场Z-score
                self.entry_direction = 'SHORT_SILVER'
                self.last_signal = 'SHORT_SILVER'
                logger.info(f"信号: SHORT_SILVER | Z-score: {zscore:.4f}")
                trade_logger.log_signal({
                    'direction': 'SHORT_SILVER',
                    'zscore': zscore,
                    'spread': spread,
                    'silver_price': silver_price,
                    'gold_price': gold_price,
                    'entry_zscore': zscore
                })
                return ('SHORT_SILVER', f'Z-score {zscore:.2f} > {self.entry_short}')
            elif silver_pos > 0:
                # 已有 Silver 多头，平仓
                self.last_signal = 'CLOSE_SILVER'
                return ('CLOSE_SILVER', 'Z-score 回归')
        
        # Long 入场: Z-score < -2.5 (价差低于均值，做多 Silver，做空 Gold)
        elif zscore < -self.entry_long:  # zscore < -2.5
            if not has_position and not in_cooldown:
                self.entry_zscore = zscore  # 记录入场Z-score
                self.entry_direction = 'LONG_SILVER'
                self.last_signal = 'LONG_SILVER'
                logger.info(f"信号: LONG_SILVER | Z-score: {zscore:.4f}")
                trade_logger.log_signal({
                    'direction': 'LONG_SILVER',
                    'zscore': zscore,
                    'spread': spread,
                    'silver_price': silver_price,
                    'gold_price': gold_price,
                    'entry_zscore': zscore
                })
                return ('LONG_SILVER', f'Z-score {zscore:.2f} < -{self.entry_long}')
            elif silver_pos < 0:
                # 已有 Silver 空头，平仓
                self.last_signal = 'CLOSE_SILVER'
                return ('CLOSE_SILVER', 'Z-score 回归')
        
        # === 出场信号 ===
        # 优化后的平仓逻辑：区分做多做空方向
        
        elif has_position:
            # 判断当前持仓方向
            is_short = silver_pos < 0  # 做空 Silver
            
            if is_short:
                # 做空入场后的平仓条件：
                # 1. Z-score 回落低于 +0.1
                # 2. Z-score 回落幅度超过入场时幅度的 50%
                if zscore < self.exit_thresh:  # zscore < 0.1
                    self.last_signal = 'CLOSE_ALL'
                    self.last_close_iteration = iteration  # 🐯 记录平仓轮次
                    reason = f'做空平仓: Z-score {zscore:.2f} < {self.exit_thresh}'
                    logger.info(f"信号: CLOSE_ALL | {reason}")
                    trade_logger.log_signal({
                        'direction': 'CLOSE_ALL',
                        'zscore': zscore,
                        'spread': spread,
                        'silver_price': silver_price,
                        'gold_price': gold_price,
                        'entry_zscore': self.entry_zscore,
                        'exit_reason': 'zscore_fell_below_threshold'
                    })
                    return ('CLOSE_ALL', reason)
                
                # 检查回落幅度是否超过 50%
                if self.entry_zscore is not None and self.entry_zscore > 0:
                    entry_magnitude = self.entry_zscore  # 入场时的 Z-score 幅度
                    current_magnitude = zscore
                    drop_ratio = (entry_magnitude - current_magnitude) / entry_magnitude
                    if drop_ratio >= 0.5:  # 回落超过 50%
                        self.last_signal = 'CLOSE_ALL'
                        self.last_close_iteration = iteration  # 🐯 记录平仓轮次
                        reason = f'做空平仓: Z-score 回落 {drop_ratio*100:.1f}% (>{50}%)'
                        logger.info(f"信号: CLOSE_ALL | {reason}")
                        trade_logger.log_signal({
                            'direction': 'CLOSE_ALL',
                            'zscore': zscore,
                            'spread': spread,
                            'silver_price': silver_price,
                            'gold_price': gold_price,
                            'entry_zscore': self.entry_zscore,
                            'exit_reason': 'drop_ratio_50pct'
                        })
                        return ('CLOSE_ALL', reason)
            else:
                # 做多入场后的平仓条件：Z-score 回升高于 -0.1
                if zscore > -self.exit_thresh:  # zscore > -0.1
                    self.last_signal = 'CLOSE_ALL'
                    self.last_close_iteration = iteration  # 🐯 记录平仓轮次
                    reason = f'做多平仓: Z-score {zscore:.2f} > -{-self.exit_thresh}'
                    logger.info(f"信号: CLOSE_ALL | {reason}")
                    trade_logger.log_signal({
                        'direction': 'CLOSE_ALL',
                        'zscore': zscore,
                        'spread': spread,
                        'silver_price': silver_price,
                        'gold_price': gold_price,
                        'entry_zscore': self.entry_zscore,
                        'exit_reason': 'zscore_rose_above_threshold'
                    })
                    return ('CLOSE_ALL', reason)
        
        # === 持有 ===
        
        self.last_signal = 'HOLD'
        return ('HOLD', f'Z-score {zscore:.2f} 无信号')
    
    def get_position_size(self, direction: str, capital: float = 10000, prices: dict = None) -> dict:
        """
        计算仓位
        
        Args:
            direction: 交易方向
            capital: 资金量
            prices: 当前价格 {'silver': float, 'gold': float}
        
        Returns:
            {'silver': float, 'gold': float}
            正数 = 多头, 负数 = 空头（单位是数量，不是金额！）
        """
        # 固定仓位比例
        position_pct = 0.8  # 使用 80% 资金
        usable_capital = capital * position_pct
        
        # 获取当前价格
        silver_price = prices.get('silver', 65) if prices else 65
        gold_price = prices.get('gold', 4400) if prices else 4400
        
        # 根据资金量和价格计算实际数量（各用一半资金）
        half_capital = usable_capital / 2
        silver_qty = half_capital / silver_price  # Silver 数量
        gold_qty = half_capital / gold_price       # Gold 数量
        
        if direction == 'SHORT_SILVER':
            # 做空 Silver, 做多 Gold
            return {'silver': -silver_qty, 'gold': gold_qty}
        elif direction == 'LONG_SILVER':
            # 做多 Silver, 做空 Gold
            return {'silver': silver_qty, 'gold': -gold_qty}
        elif direction == 'CLOSE_ALL' or direction == 'CLOSE_SILVER':
            return {'silver': 0, 'gold': 0}
        else:
            return {'silver': 0, 'gold': 0}
    
    def get_status(self) -> dict:
        """获取策略状态"""
        return {
            'zscore': self.zscore if self.zscore else 0,
            'last_signal': self.last_signal if self.last_signal else 'NONE',
            'lookback': self.lookback,
            'entry_short': self.entry_short,
            'entry_long': self.entry_long,
            'exit_thresh': self.exit_thresh
        }
