from __future__ import annotations

"""
Credits earned by the bot: trade profit (journal MarketSell: sale minus the price paid) minus the costs on the way
(refuel, repair, ammo), counted only while an assist runs. Session = since EDAP was started, total = all sessions
(saved in configs/earnings.json).
"""

import json
import os
import threading
import time
from datetime import datetime

from EDlogger import logger

EARNINGS_FILE = './configs/earnings.json'
COST_EVENTS = {'RefuelAll': 'Cost', 'RefuelPartial': 'Cost', 'RepairAll': 'Cost', 'Repair': 'Cost',
               'BuyAmmo': 'Cost', 'RestockVehicle': 'Cost', 'Resurrect': 'Cost'}


def _ts(ev: dict) -> float | None:
    try:
        return datetime.fromisoformat(ev['timestamp'].replace('Z', '+00:00')).timestamp()
    except Exception:
        return None


class EarningsTracker:
    def __init__(self, active_cb=None, filename: str = EARNINGS_FILE):
        self.filename = filename
        self.active_cb = active_cb or (lambda: True)
        self.lock = threading.Lock()
        self.session_start = time.time()
        self.session_profit = 0  # trade profit
        self.session_costs = 0
        self.session_sales = 0  # number of sales
        self.session_tons = 0
        self.last_trade = ''  # e.g. '+12.3 M cr: 752 t Gold'
        self.trade_events = 0  # every MarketBuy/MarketSell (also manual ones), for the 'no trade' detection
        self.total = {'profit': 0, 'costs': 0, 'sales': 0, 'tons': 0, 'last_ts': 0.0, 'since': ''}
        self._load()

    def _load(self):
        try:
            with open(self.filename, 'r', encoding='utf-8') as f:
                self.total.update(json.load(f))
        except FileNotFoundError:
            self.total['since'] = datetime.now().strftime('%Y-%m-%d')
        except Exception as e:
            logger.warning(f"earnings: {self.filename}: {e}")
        # Events older than the start of EDAP are never counted (journal read again from the start)
        self.total['last_ts'] = max(float(self.total.get('last_ts') or 0), self.session_start - 5)

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.filename), exist_ok=True)
            tmp = self.filename + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.total, f, indent=2)
            os.replace(tmp, self.filename)
        except Exception as e:
            logger.warning(f"earnings: saving {self.filename}: {e}")

    def on_event(self, ev: dict):
        """ Journal callback (every parsed event). """
        name = ev.get('event')
        if name not in ('MarketSell', 'MarketBuy', 'Died') and name not in COST_EVENTS:
            return
        ts = _ts(ev)
        with self.lock:
            if ts is None or ts <= float(self.total.get('last_ts') or 0):
                return  # already counted / before EDAP started
            if name in ('MarketBuy', 'MarketSell'):
                self.trade_events += 1
            try:
                if not self.active_cb():
                    self.total['last_ts'] = ts
                    return  # a manual trade, not the bot
            except Exception:
                pass
            if name == 'MarketBuy':
                # Paid for cargo that is not sold yet: lost if the ship is destroyed
                self.total['open_purchase'] = int(self.total.get('open_purchase') or 0) + int(ev.get('TotalCost') or 0)
            elif name == 'Died':
                lost = int(self.total.get('open_purchase') or 0)
                self.total['open_purchase'] = 0
                self.session_costs += lost
                self.total['costs'] = int(self.total.get('costs') or 0) + lost
                self.last_trade = f"ship destroyed, cargo lost: -{fmt_cr(lost)} cr"
                logger.info(f"Earnings: ship destroyed, cargo worth {lost:,} cr lost")
            elif name == 'MarketSell':
                count = int(ev.get('Count') or 0)
                sale = int(ev.get('TotalSale') or 0)
                paid = int(ev.get('AvgPricePaid') or 0) * count
                profit = sale - paid if paid > 0 else 0  # unknown purchase price (e.g. mined): no profit counted
                self.total['open_purchase'] = max(0, int(self.total.get('open_purchase') or 0) - paid)
                self.session_profit += profit
                self.session_sales += 1
                self.session_tons += count
                self.total['profit'] = int(self.total.get('profit') or 0) + profit
                self.total['sales'] = int(self.total.get('sales') or 0) + 1
                self.total['tons'] = int(self.total.get('tons') or 0) + count
                item = ev.get('Type_Localised') or str(ev.get('Type') or '').title()
                self.last_trade = f"{fmt_cr(profit, sign=True)} cr: {count} t {item}"
                logger.info(f"Earnings: sold {count} t {item} for {sale:,} cr, profit {profit:,} cr "
                            f"(session {self.session_profit:,} cr)")
            else:
                cost = int(ev.get(COST_EVENTS[name]) or 0)
                if name == 'Resurrect':
                    self.last_trade = f"rebuy: -{fmt_cr(cost)} cr" + (f" ({self.last_trade})" if 'destroyed' in
                                                                       self.last_trade else "")
                self.session_costs += cost
                self.total['costs'] = int(self.total.get('costs') or 0) + cost
            self.total['last_ts'] = ts
            self._save()

    # --- display -------------------------------------------------------------------------------------------------
    def session_net(self) -> int:
        return self.session_profit - self.session_costs

    def total_net(self) -> int:
        return int(self.total.get('profit') or 0) - int(self.total.get('costs') or 0)

    def per_hour(self) -> float:
        hours = (time.time() - self.session_start) / 3600.0
        return self.session_net() / hours if hours > 0.05 else 0.0

    def reset_total(self):
        with self.lock:
            self.total.update({'profit': 0, 'costs': 0, 'sales': 0, 'tons': 0,
                               'since': datetime.now().strftime('%Y-%m-%d')})
            self._save()


def fmt_cr(value: float, sign: bool = False) -> str:
    v = float(value or 0)
    s = '+' if sign and v > 0 else ''
    a = abs(v)
    if a >= 1e9:
        return f"{s}{v / 1e9:.2f} B"
    if a >= 1e6:
        return f"{s}{v / 1e6:.2f} M"
    if a >= 1e3:
        return f"{s}{v / 1e3:.0f} k"
    return f"{s}{v:.0f}"
