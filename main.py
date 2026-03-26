"""
HyperHedge 主程序 - Silver/Gold 配对交易模拟
"""
import json
import os
import signal
import sys
import time
import subprocess
from datetime import datetime, timedelta

import pandas as pd
import config
from logger import logger, trade_logger
from data_manager import DataManager
from strategy import PairTradingStrategy
from trading import TradingEngine
from risk_manager import RiskManager
from dashboard import Dashboard


def notify_user_415057(message: str):
    """通知用户 415057 (通过 OpenClaw message 工具)"""
    try:
        cmd = [
            "openclaw", "message", "send",
            "--target", "ou_64ae37522693b5bbf0002f06bfdebfe3",
            "--channel", "feishu",
            "--message", message
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode == 0:
            logger.info(f"✅ 已通知用户: {message[:30]}...")
        else:
            logger.warning(f"⚠️ 通知失败: {result.stderr}")
    except Exception as e:
        logger.error(f"⚠️ 发送通知异常: {e}")


class HyperHedge:
    """HyperHedge 交易系统主类"""
    
    def __init__(self):
        # 初始化各模块
        logger.info("=" * 50)
        logger.info("HyperHedge 配对交易系统启动")
        logger.info("=" * 50)
        
        self.data_manager = DataManager()
        self.strategy = PairTradingStrategy()
        self.trading_engine = TradingEngine()
        self.risk_manager = RiskManager(self.data_manager, self.trading_engine)
        self.dashboard = Dashboard(
            self.data_manager, 
            self.strategy, 
            self.trading_engine, 
            self.risk_manager
        )
        
        # 运行状态
        self.running = False
        self.iteration = 0
        self.total_trades: int = 0  # 累计开仓次数（实际交易轮次）
        
        # 🐯 防重复通知: 记录上次汇报的轮次，确保每60轮只汇报一次
        self._last_reported_iteration: int = 0
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # 设置告警回调
        self.risk_manager.set_alert_callback(self._on_alert)
        
        # 状态文件路径
        self.state_file = 'state.json'
        
        logger.info(f"模式: {'模拟盘' if config.SIMULATION_MODE else '实盘'}")
        logger.info(f"交易对: {config.SYMBOL_SILVER} / {config.SYMBOL_GOLD}")
        logger.info(f"周期: {config.INTERVAL}")
    
    def save_state(self, filepath: str = None) -> bool:
        """
        保存当前状态到文件
        
        Args:
            filepath: 状态文件路径
        
        Returns:
            是否保存成功
        """
        if filepath is None:
            filepath = self.state_file
        
        try:
            state = {
                'position': {
                    'silver': self.trading_engine.positions.get('silver', 0),
                    'gold': self.trading_engine.positions.get('gold', 0)
                },
                'entry_prices': self.trading_engine.entry_prices,  # 🐯 修复: 持久化入场价格（计算已实现盈亏的关键）
                'realized_pnl': self.trading_engine.realized_pnl,  # 🐯 修复: 持久化已实现盈亏
                'entry_zscore': self.strategy.entry_zscore,
                'entry_direction': self.strategy.entry_direction,
                'iteration': self.iteration,
                'last_close_iteration': self.strategy.last_close_iteration,  # 🐯 冷却期记录
                'total_trades': self.total_trades,  # 累计开仓次数
                'timestamp': datetime.now().isoformat()
            }
            with open(filepath, 'w') as f:
                json.dump(state, f, indent=2)
            logger.debug(f"状态已保存: {filepath}")
            return True
        except Exception as e:
            logger.error(f"保存状态失败: {e}")
            return False
    
    def load_state(self, filepath: str = None) -> dict:
        """
        从文件加载状态
        
        Args:
            filepath: 状态文件路径
        
        Returns:
            状态字典，如果文件不存在则返回 None
        """
        if filepath is None:
            filepath = self.state_file
        
        if os.path.exists(filepath):
            try:
                with open(filepath) as f:
                    state = json.load(f)
                logger.info(f"✓ 已加载状态: {filepath}")
                logger.info(f"  - 持仓: SILVER={state.get('position', {}).get('silver', 0):.4f}, GOLD={state.get('position', {}).get('gold', 0):.4f}")
                logger.info(f"  - 入场Z-score: {state.get('entry_zscore')}")
                logger.info(f"  - 入场方向: {state.get('entry_direction')}")
                logger.info(f"  - 迭代次数: {state.get('iteration')}")
                logger.info(f"  - 保存时间: {state.get('timestamp')}")
                return state
            except Exception as e:
                logger.error(f"加载状态失败: {e}")
                return None
        return None
    
    def check_and_fill_gaps(self) -> list:
        """
        检查数据完整性并补全缺失的K线数据
        
        Returns:
            缺失时间段列表 [(start, end), ...]
        """
        if self.data_manager.silver_data.empty or self.data_manager.gold_data.empty:
            logger.warning("数据为空，无法检查完整性")
            return []
        
        # 检查 Silver 数据
        silver_timestamps = self.data_manager.silver_data['timestamp'].sort_values()
        silver_gaps = self._find_time_gaps(silver_timestamps)
        
        # 检查 Gold 数据
        gold_timestamps = self.data_manager.gold_data['timestamp'].sort_values()
        gold_gaps = self._find_time_gaps(gold_timestamps)
        
        all_gaps = silver_gaps + gold_gaps
        
        if all_gaps:
            logger.warning(f"检测到 {len(all_gaps)} 个数据缺失时间段:")
            for gap_start, gap_end in all_gaps:
                logger.warning(f"  - {gap_start} -> {gap_end}")
            
            # 补全数据
            self._fill_gaps(all_gaps)
        else:
            logger.info("✓ 数据完整性检查通过，无缺失时间段")
        
        return all_gaps
    
    def _find_time_gaps(self, timestamps) -> list:
        """
        查找时间序列中的断点
        
        Args:
            timestamps: 排序后的时间戳 Series
        
        Returns:
            缺失时间段列表 [(start, end), ...]
        """
        gaps = []
        interval_minutes = 15  # 15分钟K线
        
        for i in range(1, len(timestamps)):
            prev_ts = timestamps.iloc[i-1]
            curr_ts = timestamps.iloc[i]
            expected_diff = timedelta(minutes=interval_minutes)
            
            if curr_ts - prev_ts > expected_diff:
                # 存在缺失
                gap_start = prev_ts + expected_diff
                gap_end = curr_ts
                gaps.append((gap_start, gap_end))
        
        return gaps
    
    def _fill_gaps(self, gaps: list):
        """
        从API补全缺失的K线数据
        
        Args:
            gaps: 缺失时间段列表 [(start, end), ...]
        """
        logger.info("开始补全缺失数据...")
        
        for gap_start, gap_end in gaps:
            logger.info(f"补全数据: {gap_start} -> {gap_end}")
            
            try:
                # 计算需要获取的数据量 (每15分钟一根K线)
                total_minutes = int((gap_end - gap_start).total_seconds() / 60)
                num_bars = total_minutes // 15
                
                if num_bars <= 0 or num_bars > 1000:  # 限制单次请求数量
                    logger.warning(f"跳过过大间隙: {num_bars} 根K线")
                    continue
                
                # 获取 Silver 数据
                silver_df = self.data_manager.fetch_realtime_klines(
                    config.SYMBOL_SILVER, 
                    config.INTERVAL,
                    limit=num_bars
                )
                
                # 获取 Gold 数据
                gold_df = self.data_manager.fetch_realtime_klines(
                    config.SYMBOL_GOLD, 
                    config.INTERVAL,
                    limit=num_bars
                )
                
                # 合并到现有数据 - 直接合并所有去重，不限制时间段
                if not silver_df.empty:
                    combined = pd.concat([self.data_manager.silver_data, silver_df])
                    combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
                    combined = combined.sort_values('timestamp').reset_index(drop=True)
                    # 更新数据
                    self.data_manager.silver_data = combined
                    logger.info(f"  Silver 补全: 共 {len(self.data_manager.silver_data)} 条")
                
                if not gold_df.empty:
                    combined = pd.concat([self.data_manager.gold_data, gold_df])
                    combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
                    combined = combined.sort_values('timestamp').reset_index(drop=True)
                    self.data_manager.gold_data = combined
                    logger.info(f"  Gold 补全: 共 {len(self.data_manager.gold_data)} 条")
                        
            except Exception as e:
                logger.error(f"补全数据失败: {e}")
        
        # 保存补全后的数据
        self.data_manager.save_data()
        logger.info("✓ 数据补全完成")
    
    def restore_position_state(self, state: dict):
        """
        恢复仓位状态
        
        Args:
            state: 状态字典
        """
        if state is None:
            logger.info("无状态可恢复，从头开始")
            return
        
        position = state.get('position', {})
        
        # 恢复策略状态
        self.strategy.entry_zscore = state.get('entry_zscore')
        self.strategy.entry_direction = state.get('entry_direction')
        # 🐯 恢复冷却期记录
        self.strategy.last_close_iteration = state.get('last_close_iteration')
        # 🐯 Bug修复: 恢复后不标记为刚开过仓，允许继续正常交易
        self.strategy.just_opened_this_iteration = False
        
        # 恢复持仓
        self.trading_engine.positions['silver'] = position.get('silver', 0)
        self.trading_engine.positions['gold'] = position.get('gold', 0)
        
        # 恢复入场价格 (get_pnl 需要用到)
        # 🐯 Fix: 如果 state 缺少 entry_prices，使用当前交易引擎的默认值（避免覆盖为空的 {}）
        saved_entry_prices = state.get('entry_prices', None)
        if saved_entry_prices is not None and saved_entry_prices:
            self.trading_engine.entry_prices = saved_entry_prices
        else:
            logger.warning("⚠️ state.json 缺少 entry_prices，使用当前默认值（可能影响 PnL 计算）")
        
        # 恢复已实现盈亏 (FIX: 之前漏掉，导致汇报显示 $0)
        saved_realized_pnl = state.get('realized_pnl', None)
        if saved_realized_pnl is not None:
            self.trading_engine.realized_pnl = saved_realized_pnl
        else:
            logger.warning("⚠️ state.json 缺少 realized_pnl，初始化为 0.0")
        
        # 恢复迭代次数
        self.iteration = state.get('iteration', 0)
        # 恢复累计开仓次数
        self.total_trades = state.get('total_trades', 0)
        
        logger.info(f"✓ 仓位状态已恢复")
        logger.info(f"  - SILVER: {self.trading_engine.positions['silver']:.4f}")
        logger.info(f"  - GOLD: {self.trading_engine.positions['gold']:.4f}")
        logger.info(f"  - 已实现盈亏: ${self.trading_engine.realized_pnl:.4f}")
        logger.info(f"  - 继续从第 {self.iteration + 1} 轮开始运行")
        logger.info(f"  - 累计开仓: {self.total_trades} 次")
    
    def _signal_handler(self, signum, frame):
        """信号处理"""
        logger.info("收到退出信号，正在关闭...")
        self.running = False
    
    def _on_alert(self, message: str):
        """告警回调"""
        logger.error(f"⚠️ 告警: {message}")
        # 可以添加: 发送邮件/短信/钉钉告警
    
    def initialize(self, resume: bool = True) -> bool:
        """
        初始化 - 获取初始数据
        
        Args:
            resume: 是否尝试恢复状态（断点续跑模式）
        
        Returns:
            是否初始化成功
        """
        logger.info("正在初始化数据...")
        
        # 断点续跑模式
        if resume:
            # 1. 先检查并补全缺失的K线数据（基于现有历史数据）
            # 注意：要在更新数据之前检查，否则API会先补全数据
            gaps = self.check_and_fill_gaps()
            
            # 2. 尝试加载之前的状态
            state = self.load_state()
            if state:
                # 3. 恢复仓位状态
                self.restore_position_state(state)
            else:
                logger.info("未找到历史状态，从头开始运行")
        
        # 4. 更新数据（获取最新K线）
        success = self.data_manager.update_data()
        
        if not success:
            logger.error("数据初始化失败，5秒后重试...")
            time.sleep(5)
            success = self.data_manager.update_data()
        
        if not success or not self.data_manager.is_data_ready():
            logger.error("数据初始化失败，请检查网络连接")
            return False
        
        logger.info(
            f"数据初始化完成 | SILVER: {len(self.data_manager.silver_data)} | "
            f"GOLD: {len(self.data_manager.gold_data)}"
        )
        
        return True
    
    def run_once(self) -> bool:
        """
        执行一次交易循环
        
        Returns:
            是否成功执行
        """
        self.iteration += 1
        logger.debug(f"=== 第 {self.iteration} 轮 ===")
        
        # 1. 更新数据
        if not self.data_manager.update_data():
            logger.warning("数据更新失败，使用缓存数据")
        
        # 2. 检查数据是否足够
        if not self.data_manager.is_data_ready(config.LOOKBACK + 10):
            logger.warning("数据不足，等待更多数据...")
            return False
        
        # 3. 获取价格
        prices = self.data_manager.get_latest_prices()
        
        # 输出实时价格到日志 (供面板读取)
        if 'silver' in prices and 'gold' in prices:
            logger.info(f"实时价格 | xyz:SILVER: ${prices['silver']:.4f} | xyz:GOLD: ${prices['gold']:.4f}")
        
        # 4. 计算 Z-score
        spread_series = self.data_manager.get_spread_series()
        zscore_series = self.strategy.calculate_zscore(spread_series)
        
        if zscore_series.empty:
            logger.warning("Z-score 计算失败")
            return False
        
        current_zscore = zscore_series.iloc[-1]
        
        # 获取当前spread
        current_spread = spread_series.iloc[-1] if not spread_series.empty else 0
        
        # 5. 获取当前持仓
        current_positions = self.trading_engine.get_positions()
        
        # 6. 生成信号（不打印，只计算）
        # 🐯 传入当前轮次，用于冷却期判断
        signal, reason = self.strategy.generate_signal(current_zscore, current_positions, prices, current_spread, self.iteration)
        
        # 7. 每次都显示当前状态
        logger.info(f"状态 | Z-score: {current_zscore:.4f} | Spread: {current_spread:.6f} | 信号: {signal}")
        
        # 8. 计算并显示盈亏
        pnl_info = self.trading_engine.get_pnl(prices)
        logger.info(
            f"盈亏 | 已实现: ${pnl_info['realized_pnl']:.4f} | "
            f"未实现: ${pnl_info['unrealized_pnl']:.4f} | "
            f"总计: ${pnl_info['total_pnl']:.4f} | "
            f"收益率: {pnl_info['return_pct']:.2f}%"
        )
        
        # 8. 只在有开仓信号时执行交易
        if signal in ['SHORT_SILVER', 'LONG_SILVER']:
            logger.info(f"⚠️ 执行交易: {signal}")
            target_sizes = self.strategy.get_position_size(signal, self.trading_engine.capital, prices)
            self.trading_engine.set_target_positions(
                target_sizes['silver'],
                target_sizes['gold']
            )
            self.trading_engine.open_position(signal, prices, spread=current_spread, zscore=current_zscore)
            self.total_trades += 1  # 累计开仓次数
            # 🐯 Bug修复: 开仓后立即标记，防止本轮内再次触发（如 20:44:47 开仓后 20:44:50 不再触发）
            self.strategy.just_opened_this_iteration = True
            
        elif signal == 'CLOSE_ALL':
            logger.info(f"⚠️ 执行平仓: {signal}")
            self.trading_engine.close_position(prices, spread=current_spread, zscore=current_zscore)
        
        # 8. 风控检查
        self.risk_manager.check_position_alignment()
        
        # 9. 定期保存数据
        if self.iteration % config.SAVE_INTERVAL == 0:
            self.data_manager.save_data()
        
        # 10. 定期保存状态（用于断点续跑）
        if self.iteration % config.SAVE_INTERVAL == 0:
            self.save_state()
        
        # 11. 定期记录盈亏 (每10轮记录一次到交易日志)
        if self.iteration % 10 == 0:
            pnl_info = self.trading_engine.get_pnl(prices)
            trade_logger.log_pnl(pnl_info)
        
        # 12. 每小时汇报一次状态给用户 (每60轮 = 60分钟)
        # 🐯 防重复: 用 _last_reported_iteration 确保每60轮只汇报一次
        if (self.iteration > 0 and self.iteration % 60 == 0
                and self.iteration != self._last_reported_iteration):
            pnl_info = self.trading_engine.get_pnl(prices)
            current_positions = self.trading_engine.get_positions()
            has_position = current_positions['silver'] != 0 or current_positions['gold'] != 0
            # 计算运行时间 (每轮60秒)
            run_minutes = self.iteration
            run_hours = run_minutes // 60
            run_secs = run_minutes % 60
            if run_hours > 0:
                run_time_str = f"{run_hours}小时{run_secs}分钟"
            else:
                run_time_str = f"{run_secs}分钟"
            
            position_status = "🟢 有持仓" if has_position else "⚪ 无持仓"
            report_msg = (
                f"📊 【HyperHedge 定期汇报】\n"
                f"⏱️ 已运行: {run_time_str} (心跳 {self.iteration})\n"
                f"📈 开仓次数: {self.total_trades} 次\n"
                f"💰 总盈亏: ${pnl_info['total_pnl']:.4f}\n"
                f"   已实现: ${pnl_info['realized_pnl']:.4f}\n"
                f"   未实现: ${pnl_info['unrealized_pnl']:.4f}\n"
                f"   收益率: {pnl_info['return_pct']:.2f}%\n"
                f"📉 当前状态: {position_status} | Z: {current_zscore:.2f} | Spread: {current_spread:.4f}\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            notify_user_415057(report_msg)
            self._last_reported_iteration = self.iteration  # 🐯 记录已汇报的轮次
        
        return True
    
    def run(self, interval: int = 60):
        """
        运行交易循环
        
        Args:
            interval: 循环间隔(秒)
        """
        self.running = True
        
        # 初始化
        if not self.initialize():
            logger.error("初始化失败，程序退出")
            return
        
        logger.info(f"开始交易循环 (间隔: {interval}秒)")
        
        while self.running:
            try:
                # 执行一次循环
                self.run_once()
                
                # 显示仪表盘
                self.dashboard.render()
                
                # 等待下一次
                for _ in range(interval):
                    if not self.running:
                        break
                    time.sleep(1)
                    
            except KeyboardInterrupt:
                logger.info("用户中断")
                break
            except Exception as e:
                logger.error(f"循环异常: {e}", exc_info=True)
                time.sleep(5)
        
        # 退出前保存数据
        self.cleanup()
    
    def run_dashboard_only(self):
        """仅运行仪表盘模式 (不交易)"""
        self.running = True
        
        if not self.initialize():
            logger.error("初始化失败")
            return
        
        logger.info("仪表盘模式运行 (按 Ctrl+C 退出)")
        
        while self.running:
            try:
                self.data_manager.update_data()
                self.dashboard.render()
                time.sleep(config.DASHBOARD_REFRESH)
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"仪表盘异常: {e}")
                time.sleep(5)
    
    def cleanup(self):
        """清理资源"""
        logger.info("正在保存数据...")
        self.data_manager.save_data()
        # 保存状态用于断点续跑
        self.save_state()
        logger.info("HyperHedge 已停止")
    
    def test_connection(self) -> bool:
        """测试网络连接"""
        try:
            df = self.data_manager.fetch_realtime_klines(config.SYMBOL_SILVER, limit=1)
            if not df.empty:
                logger.info("✓ API 连接测试成功")
                return True
        except Exception as e:
            logger.error(f"✗ API 连接测试失败: {e}")
        return False


def main():
    """主入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description='HyperHedge 配对交易系统')
    parser.add_argument('--mode', choices=['trade', 'dashboard', 'test'], 
                       default='trade', help='运行模式')
    parser.add_argument('--interval', type=int, default=60,
                       help='交易循环间隔(秒)')
    parser.add_argument('--real', action='store_true',
                       help='启用实盘模式 (默认模拟盘)')
    
    args = parser.parse_args()
    
    # 修改配置
    if args.real:
        config.SIMULATION_MODE = False
        logger.info("⚠️ 实盘模式已启用")
    
    # 创建实例
    app = HyperHedge()
    
    # 根据模式运行
    if args.mode == 'trade':
        app.run(interval=args.interval)
    elif args.mode == 'dashboard':
        app.run_dashboard_only()
    elif args.mode == 'test':
        app.test_connection()


if __name__ == '__main__':
    main()
