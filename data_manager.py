"""
数据管理器 - 历史数据加载 + 实时K线获取
"""
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests
import pandas as pd
import numpy as np

import config
from logger import logger


class DataManager:
    """数据管理器"""
    
    def __init__(self):
        self.base_url = config.API_BASE_URL
        self.proxy = {"http": config.PROXY, "https": config.PROXY}
        self.data_dir = Path(__file__).parent / config.DATA_DIR
        self.data_dir.mkdir(exist_ok=True)
        
        # 内存中的数据
        self.silver_data: Optional[pd.DataFrame] = None
        self.gold_data: Optional[pd.DataFrame] = None
        
        # 加载历史数据
        self._load_history()
    
    def _load_history(self):
        """加载历史数据"""
        logger.info("正在加载历史数据...")
        
        silver_file = self.data_dir / "SILVER.csv"
        gold_file = self.data_dir / "GOLD.csv"
        
        if silver_file.exists():
            self.silver_data = pd.read_csv(silver_file, parse_dates=['timestamp'])
            logger.info(f"已加载 SILVER 历史数据: {len(self.silver_data)} 条")
        else:
            logger.warning(f"未找到 SILVER 历史文件: {silver_file}")
            self.silver_data = pd.DataFrame()
        
        if gold_file.exists():
            self.gold_data = pd.read_csv(gold_file, parse_dates=['timestamp'])
            logger.info(f"已加载 GOLD 历史数据: {len(self.gold_data)} 条")
        else:
            logger.warning(f"未找到 GOLD 历史文件: {gold_file}")
            self.gold_data = pd.DataFrame()
    
    def fetch_realtime_klines(self, symbol: str, interval: str = "15m", 
                               limit: int = 500) -> pd.DataFrame:
        """
        获取实时K线数据
        
        Args:
            symbol: 交易对代码 (S, PAXG)
            interval: K线周期 (1m, 5m, 15m, 1h, etc.)
            limit: 返回数量
        
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        try:
            # 计算时间范围 (毫秒)
            end_time = int(time.time() * 1000)
            start_time = end_time - (limit * 15 * 60 * 1000)  # 15分钟
            
            payload = {
                "type": "candleSnapshot",
                "req": {
                    "coin": symbol,
                    "interval": interval,
                    "startTime": start_time,
                    "endTime": end_time
                }
            }
            
            response = requests.post(
                self.base_url,
                json=payload,
                proxies=self.proxy,
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            if not data or len(data) == 0:
                logger.warning(f"未获取到 {symbol} 的K线数据")
                return pd.DataFrame()
            
            # 转换格式
            df = pd.DataFrame(data)
            df.columns = ['timestamp', 'end_time', 'symbol', 'interval', 
                        'open', 'close', 'high', 'low', 'volume', 'num_trades']
            
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]
            df = df.sort_values('timestamp').reset_index(drop=True)
            
            # 数值类型转换
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            return df
            
        except requests.exceptions.ProxyError as e:
            logger.error(f"代理连接失败: {e}")
            raise ConnectionError(f"代理连接失败: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败: {e}")
            raise ConnectionError(f"API请求失败: {e}")
        except Exception as e:
            logger.error(f"获取K线数据异常: {e}")
            raise
    
    def update_data(self) -> bool:
        """
        更新数据 (历史 + 实时)
        
        Returns:
            是否成功更新
        """
        try:
            # 获取实时数据
            silver_new = self.fetch_realtime_klines(config.SYMBOL_SILVER, config.INTERVAL)
            gold_new = self.fetch_realtime_klines(config.SYMBOL_GOLD, config.INTERVAL)
            
            if silver_new.empty or gold_new.empty:
                logger.warning("获取实时数据为空，跳过更新")
                return False
            
            # 合并历史 + 实时
            if not self.silver_data.empty:
                # 去重合并
                combined = pd.concat([self.silver_data, silver_new])
                combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
                combined = combined.sort_values('timestamp').reset_index(drop=True)
                self.silver_data = combined
            else:
                self.silver_data = silver_new
            
            if not self.gold_data.empty:
                combined = pd.concat([self.gold_data, gold_new])
                combined = combined.drop_duplicates(subset=['timestamp'], keep='last')
                combined = combined.sort_values('timestamp').reset_index(drop=True)
                self.gold_data = combined
            else:
                self.gold_data = gold_new
            
            logger.info(
                f"数据更新完成 | SILVER: {len(self.silver_data)} | "
                f"GOLD: {len(self.gold_data)}"
            )
            return True
            
        except ConnectionError as e:
            logger.error(f"网络错误，数据更新失败: {e}")
            return False
        except Exception as e:
            logger.error(f"数据更新异常: {e}")
            return False
    
    def save_data(self):
        """保存数据到CSV"""
        try:
            if not self.silver_data.empty:
                silver_file = self.data_dir / "SILVER.csv"
                self.silver_data.to_csv(silver_file, index=False)
                logger.debug(f"已保存 SILVER 数据: {len(self.silver_data)} 条")
            
            if not self.gold_data.empty:
                gold_file = self.data_dir / "GOLD.csv"
                self.gold_data.to_csv(gold_file, index=False)
                logger.debug(f"已保存 GOLD 数据: {len(self.gold_data)} 条")
                
        except Exception as e:
            logger.error(f"保存数据失败: {e}")
    
    def get_latest_prices(self) -> dict:
        """获取最新价格"""
        prices = {}
        
        if not self.silver_data.empty:
            prices['silver'] = self.silver_data['close'].iloc[-1]
            prices['silver_time'] = self.silver_data['timestamp'].iloc[-1]
        
        if not self.gold_data.empty:
            prices['gold'] = self.gold_data['close'].iloc[-1]
            prices['gold_time'] = self.gold_data['timestamp'].iloc[-1]
        
        return prices
    
    def get_spread_series(self) -> pd.Series:
        """获取价差序列 (Silver / Gold 比率)"""
        if self.silver_data.empty or self.gold_data.empty:
            return pd.Series()
        
        # 按时间对齐
        merged = pd.merge(
            self.silver_data[['timestamp', 'close']].rename(columns={'close': 'silver'}),
            self.gold_data[['timestamp', 'close']].rename(columns={'close': 'gold'}),
            on='timestamp', how='inner'
        )
        
        if merged.empty:
            return pd.Series()
        
        # Spread = Silver / Gold (价格比率)
        return merged['silver'] / merged['gold']
    
    def is_data_ready(self, min_bars: int = 50) -> bool:
        """检查数据是否足够进行策略计算"""
        if self.silver_data.empty or self.gold_data.empty:
            return False
        
        # 需要足够的数据计算Z-score
        min_len = min(len(self.silver_data), len(self.gold_data))
        return min_len >= min_bars
