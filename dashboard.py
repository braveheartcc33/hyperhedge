"""
仪表盘 - 实时显示交易状态
"""
import os
import sys
from datetime import datetime
from typing import Optional

# 简单的跨平台终端控制
if sys.platform == "win32":
    import msvcrt
    def clear_screen():
        os.system('cls')
else:
    def clear_screen():
        os.system('clear')


class Dashboard:
    """交易仪表盘"""
    
    def __init__(self, data_manager, strategy, trading_engine, risk_manager):
        self.data_manager = data_manager
        self.strategy = strategy
        self.trading_engine = trading_engine
        self.risk_manager = risk_manager
        
        # 状态缓存
        self.last_update = None
    
    def render(self):
        """渲染仪表盘"""
        clear_screen()
        
        # 获取数据
        prices = self.data_manager.get_latest_prices()
        positions = self.trading_engine.get_positions()
        strategy_status = self.strategy.get_status()
        risk_status = self.risk_manager.get_status()
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # === 标题 ===
        print("=" * 60)
        print(f"  🐯 HyperHedge Silver/Gold 配对交易仪表盘")
        print(f"  ⏰ {now}")
        print("=" * 60)
        
        # === 市场数据 ===
        print("\n📊 市场数据")
        print("-" * 40)
        silver_price = prices.get('silver', 0)
        gold_price = prices.get('gold', 0)
        print(f"  Silver (S):     ${silver_price:,.4f}" if silver_price else "  Silver (S):     --")
        print(f"  Gold (PAXG):    ${gold_price:,.4f}" if gold_price else "  Gold (PAXG):    --")
        
        if silver_price and gold_price:
            spread = silver_price - gold_price
            print(f"  价差 (S-PAXG): ${spread:,.4f}")
        
        # === 策略状态 ===
        print("\n🎯 策略状态")
        print("-" * 40)
        zscore = strategy_status.get('zscore', 0)
        print(f"  Z-Score:        {zscore:.4f}")
        print(f"  最后信号:       {strategy_status.get('last_signal', 'NONE')}")
        print(f"  入场阈值 Short: {strategy_status.get('entry_short')}")
        print(f"  入场阈值 Long:  {strategy_status.get('entry_long')}")
        print(f"  出场阈值:       ±{strategy_status.get('exit_thresh')}")
        
        # === 持仓状态 ===
        print("\n💼 持仓状态")
        print("-" * 40)
        mode = "模拟盘" if self.trading_engine.simulation_mode else "实盘"
        print(f"  交易模式:      {mode}")
        
        silver_pos = positions.get('silver', 0)
        gold_pos = positions.get('gold', 0)
        
        silver_dir = "🔴 空头" if silver_pos < 0 else ("🟢 多头" if silver_pos > 0 else "⚪ 空仓")
        gold_dir = "🔴 空头" if gold_pos < 0 else ("🟢 多头" if gold_pos > 0 else "⚪ 空仓")
        
        print(f"  Silver:        {silver_pos:>10.4f}  {silver_dir}")
        print(f"  Gold:          {gold_pos:>10.4f}  {gold_dir}")
        
        # 盈亏信息
        if silver_price and gold_price:
            pnl = self.trading_engine.get_pnl(prices)
            print(f"\n  📈 盈亏情况")
            print(f"  已实现盈亏:    ${pnl['realized_pnl']:>10.4f}")
            print(f"  未实现盈亏:    ${pnl['unrealized_pnl']:>10.4f}")
            print(f"  ─────────────────────────────")
            print(f"  总盈亏:        ${pnl['total_pnl']:>10.4f}")
            print(f"  收益率:        {pnl['return_pct']:>10.2f}%")
            print(f"  持仓市值:      ${pnl['position_value']:>10.2f}")
            print(f"  账户资金:      ${pnl['capital']:>10.2f}")
        
        # === 风控状态 ===
        print("\n🛡️ 风控状态")
        print("-" * 40)
        
        conn = "✅ 已连接" if risk_status.get('connected') else "❌ 未连接"
        print(f"  网络连接:      {conn}")
        print(f"  连续错误:      {risk_status.get('consecutive_errors')}")
        
        balanced = "✅ 平衡" if risk_status.get('position_balanced') else "⚠️ 不平衡"
        print(f"  仓位平衡:      {balanced}")
        print(f"  不平衡度:      {risk_status.get('position_imbalance', 0):.4f}")
        
        # === 最近信号 ===
        print("\n📜 最近信号")
        print("-" * 40)
        last_orders = self.trading_engine.orders[-5:] if self.trading_engine.orders else []
        
        if last_orders:
            for order in reversed(last_orders):
                ts = order.get('timestamp', '')[:19]
                direction = order.get('direction', '')
                symbol = order.get('symbol', '')
                qty = order.get('qty', 0)
                price = order.get('price', 0)
                print(f"  {ts} | {direction:4s} {symbol:6s} | Qty: {qty:8.4f} | Price: ${price:,.4f}")
        else:
            print("  (暂无交易记录)")
        
        print("\n" + "=" * 60)
        print("  按 Ctrl+C 退出")
        print("=" * 60)
        
        self.last_update = datetime.now()
    
    def render_simple(self) -> str:
        """简洁版渲染 (返回字符串)"""
        prices = self.data_manager.get_latest_prices()
        positions = self.trading_engine.get_positions()
        strategy_status = self.strategy.get_status()
        
        lines = []
        lines.append("=" * 50)
        lines.append(f"HyperHedge | {datetime.now().strftime('%H:%M:%S')}")
        lines.append("=" * 50)
        
        silver = prices.get('silver', 0)
        gold = prices.get('gold', 0)
        lines.append(f"SILVER: ${silver:,.4f} | GOLD: ${gold:,.4f}")
        
        zscore = strategy_status.get('zscore', 0)
        signal = strategy_status.get('last_signal', 'NONE')
        lines.append(f"Z-Score: {zscore:.4f} | Signal: {signal}")
        
        silver_pos = positions.get('silver', 0)
        gold_pos = positions.get('gold', 0)
        lines.append(f"Positions: SILVER={silver_pos:.4f}, GOLD={gold_pos:.4f}")
        
        # 添加盈亏信息
        if silver and gold:
            pnl = self.trading_engine.get_pnl(prices)
            lines.append(f"PnL: 已实现=${pnl['realized_pnl']:.4f} | 未实现=${pnl['unrealized_pnl']:.4f} | 总计=${pnl['total_pnl']:.4f} ({pnl['return_pct']:.2f}%)")
        
        return "\n".join(lines)
    
    def get_status_summary(self) -> dict:
        """获取状态摘要"""
        prices = self.data_manager.get_latest_prices()
        
        return {
            'timestamp': datetime.now().isoformat(),
            'silver_price': prices.get('silver'),
            'gold_price': prices.get('gold'),
            'spread': prices.get('silver', 0) - prices.get('gold', 0),
            'zscore': self.strategy.zscore,
            'last_signal': self.strategy.last_signal,
            'position_silver': self.trading_engine.positions.get('silver', 0),
            'position_gold': self.trading_engine.positions.get('gold', 0),
            'connected': self.risk_manager.is_connected,
            'simulation_mode': self.trading_engine.simulation_mode
        }
