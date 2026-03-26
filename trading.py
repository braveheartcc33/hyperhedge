"""
交易执行模块 - 模拟盘/实盘切换
"""
from datetime import datetime
from typing import Optional, Dict
import time
import subprocess
import json
import os

import config
from logger import logger, trade_logger

# 状态文件路径
STATE_FILE = os.path.join(os.path.dirname(__file__), 'state.json')


def notify_user_415057(message: str):
    """
    通知用户 415057 (通过 OpenClaw message 工具)
    重要: 每次下单（开仓或平仓）时必须立即通知用户
    """
    import time
    max_retries = 3
    for attempt in range(max_retries):
        try:
            cmd = [
                "openclaw", "message", "send",
                "--target", "ou_64ae37522693b5bbf0002f06bfdebfe3",
                "--channel", "feishu",
                "--message", message
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                logger.info(f"✅ 已通知用户")
                return True
            else:
                logger.warning(f"⚠️ 通知失败 (尝试 {attempt+1}/{max_retries}): {result.stderr}")
        except subprocess.TimeoutExpired:
            logger.warning(f"⚠️ 通知超时 (尝试 {attempt+1}/{max_retries})")
        except Exception as e:
            logger.error(f"⚠️ 发送通知异常: {e}")
        
        if attempt < max_retries - 1:
            time.sleep(2)  # 等待2秒后重试
    
    logger.error("❌ 通知用户失败，已达到最大重试次数")
    return False


def save_state(positions: dict, entry_prices: dict, realized_pnl: float, 
              capital: float, orders: list, total_trades: int = None) -> bool:
    """
    保存交易状态到文件 (每笔交易后立即保存)
    🐯 修复: 如果文件已有 total_trades 字段，保留旧值避免覆盖
    """
    try:
        # 🐯 读取现有状态，保留 total_trades 和 last_close_iteration 等字段
        existing_state = {}
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    existing_state = json.load(f)
            except Exception:
                pass
        
        state = {
            'timestamp': datetime.now().isoformat(),
            'position': positions,  # 🐯 与 main.py 保持一致，用 singular "position"
            'entry_prices': entry_prices,
            'realized_pnl': realized_pnl,
            'capital': capital,
            'orders': orders[-100:],  # 只保留最近100笔订单
            # 🐯 保留现有 total_trades，不覆盖（除非明确传入）
            'total_trades': total_trades if total_trades is not None else existing_state.get('total_trades', 0),
            # 🐯 保留其他恢复所需的字段
            'entry_zscore': existing_state.get('entry_zscore'),
            'entry_direction': existing_state.get('entry_direction'),
            'last_close_iteration': existing_state.get('last_close_iteration'),
            'iteration': existing_state.get('iteration', 0),
        }
        
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        
        logger.info(f"✅ 状态已保存 | {STATE_FILE}")
        return True
        
    except Exception as e:
        logger.error(f"❌ 保存状态失败: {e}")
        return False


def load_state() -> dict:
    """
    从文件加载交易状态 (程序启动时调用)
    """
    try:
        if not os.path.exists(STATE_FILE):
            logger.info("📂 状态文件不存在，使用默认状态")
            return None
        
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            state = json.load(f)
        
        logger.info(f"✅ 状态已加载 | {state.get('timestamp', 'unknown')}")
        return state
        
    except Exception as e:
        logger.error(f"❌ 加载状态失败: {e}")
        return None


class TradingEngine:
    """交易引擎"""
    
    def __init__(self):
        self.simulation_mode = config.SIMULATION_MODE
        
        # 持仓状态
        self.positions = {
            'silver': 0.0,   # 正=多头, 负=空头
            'gold': 0.0
        }
        
        # 订单记录
        self.orders = []
        
        # 资金 (模拟)
        self.capital = 10000.0
        self.initial_capital = 10000.0
        
        # 盈亏记录
        self.realized_pnl = 0.0  # 已实现盈亏
        self.unrealized_pnl = 0.0  # 未实现盈亏
        
        # 入场记录 (用于计算已实现盈亏)
        self.entry_prices = {
            'silver': {'price': 0.0, 'qty': 0.0, 'direction': None},
            'gold': {'price': 0.0, 'qty': 0.0, 'direction': None}
        }
        
        # 🐯 防重复通知: 记录已通知过的持仓状态快照
        # 只在持仓状态实际变化时（开仓完成/平仓完成）才发通知
        self._notified_position_snapshot = {
            'silver_qty': 0.0,
            'gold_qty': 0.0,
            'total_trades': 0
        }
        
        # 启动时加载状态
        saved_state = load_state()
        if saved_state:
            # 🐯 兼容新旧格式：position (singular, 新) 或 positions (plural, 旧)
            self.positions = saved_state.get('position', saved_state.get('positions', self.positions))
            self.entry_prices = saved_state.get('entry_prices', self.entry_prices)
            self.realized_pnl = saved_state.get('realized_pnl', 0.0)
            self.capital = saved_state.get('capital', 10000.0)
            saved_orders = saved_state.get('orders', [])
            self.orders.extend(saved_orders)
            logger.info(f"📂 已恢复状态 | SILVER: {self.positions.get('silver', 0):.4f} | GOLD: {self.positions.get('gold', 0):.4f}")
        
        logger.info(f"交易引擎初始化 | 模式: {'模拟盘' if self.simulation_mode else '实盘'}")
    
    def execute_order(self, direction: str, symbol: str, qty: float, 
                      price: float, order_type: str = 'market') -> dict:
        """
        执行订单
        
        Args:
            direction: 'BUY' or 'SELL'
            symbol: 'silver' or 'gold'
            qty: 数量
            price: 价格
            order_type: 'market' or 'limit'
        
        Returns:
            order result dict
        """
        if self.simulation_mode:
            return self._simulate_order(direction, symbol, qty, price, order_type)
        else:
            return self._real_order(direction, symbol, qty, price, order_type)
    
    def _simulate_order(self, direction: str, symbol: str, qty: float,
                        price: float, order_type: str) -> dict:
        """模拟订单执行"""
        order = {
            'id': len(self.orders) + 1,
            'timestamp': datetime.now().isoformat(),
            'direction': direction,
            'symbol': symbol,
            'qty': qty,
            'price': price,
            'type': order_type,
            'mode': 'SIMULATION',
            'status': 'FILLED',
            'filled_price': price  # 模拟市价单成交价格
        }
        
        # 记录入场/出场价格 (用于计算盈亏)
        current_pos = self.positions.get(symbol, 0)
        
        if direction == 'BUY':
            # 买入: 如果当前是空头，平仓并计算已实现盈亏
            if current_pos < 0:
                # 平空仓: 卖出价 - 买入价 = 盈利
                exit_qty = min(qty, abs(current_pos))
                exit_price = price
                # 🐯 Fix: 如果 entry_prices 缺失或为空，使用 0.0，避免 KeyError
                entry_info = self.entry_prices.get(symbol, {'price': 0.0, 'qty': 0.0, 'direction': None})
                entry_price = entry_info.get('price', 0.0)
                pnl = (entry_price - exit_price) * exit_qty  # 做空盈利 = 低价买入 - 高价卖出
                self.realized_pnl += pnl
                logger.info(f"平仓盈亏 | {symbol} | 入场: ${entry_price:.4f} | 出场: ${exit_price:.4f} | PnL: ${pnl:.4f}")
                
                # 更新剩余空头仓位
                remaining_qty = abs(current_pos) - qty
                if remaining_qty > 0:
                    self.positions[symbol] = -remaining_qty
                    self.entry_prices[symbol] = {'price': entry_price, 'qty': remaining_qty, 'direction': 'SHORT'}
                else:
                    self.positions[symbol] = 0
                    self.entry_prices[symbol] = {'price': 0.0, 'qty': 0.0, 'direction': None}
            else:
                # 多头加仓
                self.positions[symbol] += qty
                # 加权平均成本
                old_qty = self.entry_prices[symbol]['qty']
                if old_qty > 0:
                    avg_price = (self.entry_prices[symbol]['price'] * old_qty + price * qty) / (old_qty + qty)
                    self.entry_prices[symbol] = {'price': avg_price, 'qty': old_qty + qty, 'direction': 'LONG'}
                else:
                    self.entry_prices[symbol] = {'price': price, 'qty': qty, 'direction': 'LONG'}
        else:
            # 卖出: 如果当前是多头，平仓并计算已实现盈亏
            if current_pos > 0:
                # 平多仓: 卖出价 - 买入价 = 盈利
                exit_qty = min(qty, current_pos)
                exit_price = price
                # 🐯 Fix: 如果 entry_prices 缺失或为空，使用 0.0，避免 KeyError
                entry_info = self.entry_prices.get(symbol, {'price': 0.0, 'qty': 0.0, 'direction': None})
                entry_price = entry_info.get('price', 0.0)
                pnl = (exit_price - entry_price) * exit_qty  # 做多盈利 = 高价卖出 - 低价买入
                self.realized_pnl += pnl
                logger.info(f"平仓盈亏 | {symbol} | 入场: ${entry_price:.4f} | 出场: ${exit_price:.4f} | PnL: ${pnl:.4f}")
                
                # 剩余多头仓位
                remaining_qty = current_pos - qty
                if remaining_qty > 0:
                    self.positions[symbol] = remaining_qty
                    self.entry_prices[symbol] = {'price': entry_price, 'qty': remaining_qty, 'direction': 'LONG'}
                else:
                    self.positions[symbol] = 0
                    self.entry_prices[symbol] = {'price': 0.0, 'qty': 0.0, 'direction': None}
            else:
                # 空头加仓
                self.positions[symbol] -= qty
                # 加权平均成本
                old_qty = self.entry_prices[symbol]['qty']
                if old_qty > 0:
                    avg_price = (self.entry_prices[symbol]['price'] * old_qty + price * qty) / (old_qty + qty)
                    self.entry_prices[symbol] = {'price': avg_price, 'qty': old_qty + qty, 'direction': 'SHORT'}
                else:
                    self.entry_prices[symbol] = {'price': price, 'qty': qty, 'direction': 'SHORT'}
        
        self.orders.append(order)
        
        # 记录日志
        trade_logger.log_order(order)
        logger.info(
            f"模拟下单 | {direction} {symbol} | Qty: {qty:.4f} | "
            f"Price: {price:.4f}"
        )
        
        return order
    
    def _real_order(self, direction: str, symbol: str, qty: float,
                    price: float, order_type: str) -> dict:
        """
        实盘订单执行 - 需要实现真实 API 调用
        
        TODO: 实现真实的 Hyperliquid API 调用
        """
        logger.warning("实盘模式尚未实现，请先完成 API 对接")
        
        # 占位实现
        order = {
            'id': len(self.orders) + 1,
            'timestamp': datetime.now().isoformat(),
            'direction': direction,
            'symbol': symbol,
            'qty': qty,
            'price': price,
            'type': order_type,
            'mode': 'REAL',
            'status': 'PENDING',
            'note': '实盘模式待实现'
        }
        
        # 这里应该调用真实的 Hyperliquid API
        # 参考: https://hyperliquid.gitbook.io/hyperliquid-docs/integration/trading-integration
        #
        # import requests
        # payload = {
        #     "type": "order",
        #     "order": {
        #         "asset": symbol,  # "S" or "PAXG"
        #         "side": direction.lower(),  # "buy" or "sell"
        #         "price": price,
        #         "size": qty,
        #         "orderType": {"limit": {"tif": "Gtc"}}
        #     }
        # }
        # response = requests.post(f"{config.API_BASE_URL}/order", json=payload)
        
        return order
    
    def open_position(self, direction: str, prices: dict, spread: float = 0.0, zscore: float = 0.0) -> bool:
        """
        开仓
        
        Args:
            direction: 'SHORT_SILVER' or 'LONG_SILVER'
            prices: {'silver': float, 'gold': float}
            spread: 当前 spread 值（用于回溯分析）
            zscore: 当前 z-score 值（用于回溯分析）
        
        Returns:
            是否成功
        """
        try:
            silver_price = prices.get('silver', 0)
            gold_price = prices.get('gold', 0)
            
            # 🐯 防重复通知: 先记录开仓前的持仓状态
            prev_silver = self.positions.get('silver', 0)
            prev_gold = self.positions.get('gold', 0)
            prev_total_trades = len([o for o in self.orders if 'direction' in o])
            
            if direction == 'SHORT_SILVER':
                # 做空 Silver, 做多 Gold
                silver_qty = abs(self.positions.get('target_silver', -1000))
                gold_qty = abs(self.positions.get('target_gold', 1000))
                
                # 执行 Silver 空头
                self.execute_order('SELL', 'silver', silver_qty, silver_price)
                # 执行 Gold 多头
                self.execute_order('BUY', 'gold', gold_qty, gold_price)
                
                logger.info(f"开仓 | {direction} | SILVER: {silver_qty} | GOLD: {gold_qty}")
                
                # 🐯 防重复: 只在持仓实际变化时通知（开仓前无持仓，开仓后有持仓）
                new_silver = self.positions.get('silver', 0)
                new_total_trades = len([o for o in self.orders if 'direction' in o])
                position_actually_changed = (
                    (prev_silver == 0 and new_silver != 0) or  # 从无仓到有仓
                    (new_total_trades > prev_total_trades)      # 订单数增加（新开仓）
                )
                
                if position_actually_changed:
                    logger.info(f"🛡️ 开仓状态变化，发送通知 | prev_silver={prev_silver:.4f} -> new_silver={new_silver:.4f}")
                    notify_user_415057(
                        f"🚀 【开仓通知】{direction}\n"
                        f"SILVER: 做空 {silver_qty:.4f} @ ${silver_price:.4f}\n"
                        f"GOLD: 做多 {gold_qty:.4f} @ ${gold_price:.4f}\n"
                        f"📊 Spread: {spread:.6f} | Z-score: {zscore:.4f}\n"
                        f"💰 当前盈亏: ${self.get_pnl(prices)['total_pnl']:.4f}\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    logger.info(f"🛡️ 跳过重复开仓通知 | prev_silver={prev_silver:.4f}, new_silver={new_silver:.4f}")
                
                # 🔥 开仓后立即保存状态
                save_state(self.positions, self.entry_prices, self.realized_pnl, self.capital, self.orders)
                
            elif direction == 'LONG_SILVER':
                # 做多 Silver, 做空 Gold
                silver_qty = abs(self.positions.get('target_silver', 1000))
                gold_qty = abs(self.positions.get('target_gold', -1000))
                
                # 执行 Silver 多头
                self.execute_order('BUY', 'silver', silver_qty, silver_price)
                # 执行 Gold 空头
                self.execute_order('SELL', 'gold', gold_qty, gold_price)
                
                logger.info(f"开仓 | {direction} | SILVER: {silver_qty} | GOLD: {gold_qty}")
                
                # 🐯 防重复: 只在持仓实际变化时通知
                new_silver = self.positions.get('silver', 0)
                new_total_trades = len([o for o in self.orders if 'direction' in o])
                position_actually_changed = (
                    (prev_silver == 0 and new_silver != 0) or  # 从无仓到有仓
                    (new_total_trades > prev_total_trades)      # 订单数增加（新开仓）
                )
                
                if position_actually_changed:
                    logger.info(f"🛡️ 开仓状态变化，发送通知 | prev_silver={prev_silver:.4f} -> new_silver={new_silver:.4f}")
                    notify_user_415057(
                        f"🚀 【开仓通知】{direction}\n"
                        f"SILVER: 做多 {silver_qty:.4f} @ ${silver_price:.4f}\n"
                        f"GOLD: 做空 {gold_qty:.4f} @ ${gold_price:.4f}\n"
                        f"📊 Spread: {spread:.6f} | Z-score: {zscore:.4f}\n"
                        f"💰 当前盈亏: ${self.get_pnl(prices)['total_pnl']:.4f}\n"
                        f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                    )
                else:
                    logger.info(f"🛡️ 跳过重复开仓通知 | prev_silver={prev_silver:.4f}, new_silver={new_silver:.4f}")
                
                # 🔥 开仓后立即保存状态
                save_state(self.positions, self.entry_prices, self.realized_pnl, self.capital, self.orders)
            
            return True
            
        except Exception as e:
            logger.error(f"开仓失败: {e}")
            return False
    
    def close_position(self, prices: dict, spread: float = 0.0, zscore: float = 0.0) -> bool:
        """
        平仓
        
        Args:
            prices: {'silver': float, 'gold': float}
            spread: 当前 spread 值（用于回溯分析）
            zscore: 当前 z-score 值（用于回溯分析）
        
        Returns:
            是否成功
        """
        try:
            silver_pos = self.positions.get('silver', 0)
            gold_pos = self.positions.get('gold', 0)
            silver_price = prices.get('silver', 0)
            gold_price = prices.get('gold', 0)
            
            # 🐯 防重复通知: 记录开仓前订单数
            prev_total_trades = len([o for o in self.orders if 'direction' in o])
            had_position_before = (silver_pos != 0 or gold_pos != 0)
            
            if silver_pos > 0:
                # 平 Silver 多头
                self.execute_order('SELL', 'silver', abs(silver_pos), silver_price)
            elif silver_pos < 0:
                # 平 Silver 空头
                self.execute_order('BUY', 'silver', abs(silver_pos), silver_price)
            
            if gold_pos > 0:
                # 平 Gold 多头
                self.execute_order('SELL', 'gold', abs(gold_pos), gold_price)
            elif gold_pos < 0:
                # 平 Gold 空头
                self.execute_order('BUY', 'gold', abs(gold_pos), gold_price)
            
            logger.info(f"平仓 | SILVER: {silver_pos:.4f} | GOLD: {gold_pos:.4f}")
            
            # 🐯 防重复: 只在有持仓且平仓后持仓减少时才通知
            new_silver_pos = self.positions.get('silver', 0)
            new_gold_pos = self.positions.get('gold', 0)
            position_actually_changed = (
                had_position_before and  # 平仓前有持仓
                (new_silver_pos == 0 and new_gold_pos == 0)  # 平仓后无持仓
            )
            
            if position_actually_changed:
                logger.info(f"🛡️ 平仓状态变化，发送通知")
                direction = "做空" if silver_pos < 0 else "做多"
                
                # 获取平仓前计算的盈亏
                pnl_info = self.get_pnl(prices)
                realized = pnl_info['realized_pnl']
                unrealized = pnl_info['unrealized_pnl']
                
                notify_user_415057(
                    f"🔔 【平仓通知】\n"
                    f"SILVER: 平{direction} {abs(silver_pos):.4f} @ ${silver_price:.4f}\n"
                    f"GOLD: 平仓 {gold_pos:.4f} @ ${gold_price:.4f}\n"
                    f"📊 Spread: {spread:.6f} | Z-score: {zscore:.4f}\n"
                    f"已实现盈亏: ${realized:.4f}\n"
                    f"未实现盈亏: ${unrealized:.4f}\n"
                    f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                )
            else:
                logger.info(f"🛡️ 跳过重复平仓通知 | had_position={had_position_before}, new_silver={new_silver_pos:.4f}, new_gold={new_gold_pos:.4f}")
            
            # 🔥 平仓后立即保存状态
            save_state(self.positions, self.entry_prices, self.realized_pnl, self.capital, self.orders)
            
            return True
            
        except Exception as e:
            logger.error(f"平仓失败: {e}")
            return False
    
    def _calculate_pnl(self, prices: dict):
        """计算并记录盈亏"""
        # 简化计算 (实际应该基于成交记录)
        pass
    
    def get_positions(self) -> dict:
        """获取当前持仓"""
        return self.positions.copy()
    
    def get_positions_value(self, prices: dict) -> float:
        """计算持仓市值"""
        silver_val = self.positions.get('silver', 0) * prices.get('silver', 0)
        gold_val = self.positions.get('gold', 0) * prices.get('gold', 0)
        return silver_val + gold_val
    
    def get_pnl(self, prices: dict) -> dict:
        """
        计算盈亏情况
        
        Returns:
            dict: {
                'realized_pnl': 已实现盈亏,
                'unrealized_pnl': 未实现盈亏,
                'total_pnl': 总盈亏,
                'position_value': 持仓市值
            }
        """
        silver_price = prices.get('silver', 0)
        gold_price = prices.get('gold', 0)
        
        # 计算未实现盈亏
        unrealized = 0.0
        
        # Silver 未实现盈亏
        silver_pos = self.positions.get('silver', 0)
        silver_entry = self.entry_prices.get('silver', {}).get('price', 0)
        if silver_pos != 0 and silver_entry > 0:
            if silver_pos > 0:
                # 多头: (当前价 - 入场价) * 数量
                unrealized += (silver_price - silver_entry) * silver_pos
            else:
                # 空头: (入场价 - 当前价) * 数量
                unrealized += (silver_entry - silver_price) * abs(silver_pos)
        
        # Gold 未实现盈亏
        gold_pos = self.positions.get('gold', 0)
        gold_entry = self.entry_prices.get('gold', {}).get('price', 0)
        if gold_pos != 0 and gold_entry > 0:
            if gold_pos > 0:
                unrealized += (gold_price - gold_entry) * gold_pos
            else:
                unrealized += (gold_entry - gold_price) * abs(gold_pos)
        
        self.unrealized_pnl = unrealized
        
        # 计算持仓市值 (基于当前价格)
        position_value = self.get_positions_value(prices)
        
        return {
            'realized_pnl': self.realized_pnl,
            'unrealized_pnl': self.unrealized_pnl,
            'total_pnl': self.realized_pnl + self.unrealized_pnl,
            'position_value': position_value,
            'capital': self.capital,
            'return_pct': ((self.capital + self.realized_pnl + self.unrealized_pnl) - self.initial_capital) / self.initial_capital * 100
        }
    
    def reset_pnl(self):
        """重置盈亏记录 (可选，用于新周期)"""
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
    
    def check_position_balance(self) -> dict:
        """
        检查仓位平衡 (防止只下一边)
        
        Returns:
            {'balanced': bool, 'imbalance': float, 'silver': float, 'gold': float}
        """
        silver = self.positions.get('silver', 0)
        gold = self.positions.get('gold', 0)
        
        # 计算不平衡度
        total = abs(silver) + abs(gold)
        if total == 0:
            return {'balanced': True, 'imbalance': 0, 'silver': silver, 'gold': gold}
        
        imbalance = abs(abs(silver) - abs(gold)) / total
        
        return {
            'balanced': imbalance < config.MAX_POSITION_IMBALANCE,
            'imbalance': imbalance,
            'silver': silver,
            'gold': gold
        }
    
    def set_target_positions(self, silver: float, gold: float):
        """设置目标仓位 (用于计算开仓数量)"""
        self.positions['target_silver'] = silver
        self.positions['target_gold'] = gold
    
    def sync_positions(self, real_positions: dict):
        """
        同步真实持仓 (实盘模式从API获取)
        
        Args:
            real_positions: 从API获取的真实持仓
        """
        self.positions.update(real_positions)
        logger.info(f"持仓同步 | SILVER: {self.positions.get('silver', 0):.4f} | GOLD: {self.positions.get('gold', 0):.4f}")
