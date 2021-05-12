# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from .account import Account
from .exchange import Exchange
from .executor import BaseExecutor
from .backtest import backtest as backtest_func


from ...strategy.base import BaseStrategy
from ...utils import init_instance_by_config
from ...log import get_module_logger
from ...config import C
from .faculty import common_faculty


logger = get_module_logger("backtest caller")


def get_exchange(
    exchange=None,
    freq="day",
    start_time=None,
    end_time=None,
    codes="all",
    subscribe_fields=[],
    open_cost=0.0015,
    close_cost=0.0025,
    min_cost=5.0,
    trade_unit=None,
    limit_threshold=None,
    deal_price=None,
):
    """get_exchange

    Parameters
    ----------

    # exchange related arguments
    exchange: Exchange().
    subscribe_fields: list
        subscribe fields.
    open_cost : float
        open transaction cost.
    close_cost : float
        close transaction cost.
    min_cost : float
        min transaction cost.
    trade_unit : int
        100 for China A.
    deal_price: str
        dealing price type: 'close', 'open', 'vwap'.
    limit_threshold : float
        limit move 0.1 (10%) for example, long and short with same limit.

    Returns
    -------
    :class: Exchange
    an initialized Exchange object
    """

    if trade_unit is None:
        trade_unit = C.trade_unit
    if limit_threshold is None:
        limit_threshold = C.limit_threshold
    if deal_price is None:
        deal_price = C.deal_price
    if exchange is None:
        logger.info("Create new exchange")
        # handle exception for deal_price
        if deal_price[0] != "$":
            deal_price = "$" + deal_price

        exchange = Exchange(
            freq=freq,
            start_time=start_time,
            end_time=end_time,
            codes=codes,
            deal_price=deal_price,
            subscribe_fields=subscribe_fields,
            limit_threshold=limit_threshold,
            open_cost=open_cost,
            close_cost=close_cost,
            trade_unit=trade_unit,
            min_cost=min_cost,
        )
        return exchange
    else:
        return init_instance_by_config(exchange, accept_types=Exchange)


def backtest(start_time, end_time, strategy, env, benchmark="SH000300", account=1e9, exchange_kwargs={}):

    trade_account = Account(
        init_cash=account,
        benchmark_config={
            "benchmark": benchmark,
            "start_time": start_time,
            "end_time": end_time,
        },
    )
    trade_exchange = get_exchange(**exchange_kwargs)

    common_faculty.update(
        trade_account=trade_account,
        trade_exchange=trade_exchange,
    )

    trade_strategy = init_instance_by_config(strategy, accept_types=BaseStrategy)
    trade_env = init_instance_by_config(env, accept_types=BaseExecutor)

    report_dict = backtest_func(start_time, end_time, trade_strategy, trade_env)

    return report_dict
