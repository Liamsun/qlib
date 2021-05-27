import copy
import warnings
import pandas as pd
from typing import Union

from ...utils import init_instance_by_config
from ...utils.resam import parse_freq


from .order import Order
from .exchange import Exchange
from .utils import TradeCalendarManager


class BaseExecutor:
    """Base executor for trading"""

    def __init__(
        self,
        time_per_step: str,
        start_time: Union[str, pd.Timestamp] = None,
        end_time: Union[str, pd.Timestamp] = None,
        generate_report: bool = False,
        verbose: bool = False,
        track_data: bool = False,
        common_infra: dict = {},
        **kwargs,
    ):
        """
        Parameters
        ----------
        time_per_step : str
            trade time per trading step, used for genreate trade calendar
        generate_report : bool, optional
            whether to generate report, by default False
        verbose : bool, optional
            whether to print trading info, by default False
        track_data : bool, optional
            whether to generate trade_decision, will be used when making data for multi-level training
            - If `self.track_data` is true, when making data for training, the input `trade_decision` of `execute` will be generated by `collect_data`
            - Else,  `trade_decision` will not be generated
        common_infra : dict, optional:
            common infrastructure for backtesting, may including:
            - trade_account : Account, optional
                trade account for trading
            - trade_exchange : Exchange, optional
                exchange that provides market info

        """
        self.time_per_step = time_per_step
        self.generate_report = generate_report
        self.verbose = verbose
        self.track_data = track_data
        self.reset(start_time=start_time, end_time=end_time, track_data=track_data, common_infra=common_infra)

    def reset_common_infra(self, common_infra):
        """
        reset infrastructure for trading
            - reset trade_account
        """
        if not hasattr(self, "common_infra"):
            self.common_infra = common_infra
        else:
            self.common_infra.update(common_infra)

        if "trade_account" in common_infra:
            self.trade_account = copy.copy(common_infra.get("trade_account"))
            self.trade_account.reset(freq=self.time_per_step, init_report=True)

    def reset(self, track_data: bool = None, common_infra: dict = None, **kwargs):
        """
        - reset `start_time` and `end_time`, used in trade calendar
        - reset `track_data`, used when making data for multi-level training
        - reset `common_infra`, used to reset `trade_account`, `trade_exchange`, .etc
        """

        if track_data is not None:
            self.track_data = track_data

        if "start_time" in kwargs or "end_time" in kwargs:
            start_time = kwargs.get("start_time")
            end_time = kwargs.get("end_time")
            self.calendar = TradeCalendarManager(freq=self.time_per_step, start_time=start_time, end_time=end_time)

        if common_infra is not None:
            self.reset_common_infra(common_infra)

    def get_level_infra(self):
        return {"calendar": self.calendar}

    def finished(self):
        return self.calendar.finished()

    def execute(self, trade_decision):
        """execute the trade decision and return the executed result

        Parameters
        ----------
        trade_decision : object

        Returns
        ----------
        execute_result : List[object]
            the executed result for trade decison
        """
        raise NotImplementedError("execute is not implemented!")

    def collect_data(self, trade_decision):
        if self.track_data:
            yield trade_decision
        return self.execute(trade_decision)

    def get_trade_account(self):
        raise NotImplementedError("get_trade_account is not implemented!")

    def get_report(self):
        raise NotImplementedError("get_report is not implemented!")


class SplitExecutor(BaseExecutor):
    from ...strategy.base import BaseStrategy

    def __init__(
        self,
        time_per_step: str,
        inner_executor: Union[BaseExecutor, dict],
        inner_strategy: Union[BaseStrategy, dict],
        start_time: Union[str, pd.Timestamp] = None,
        end_time: Union[str, pd.Timestamp] = None,
        trade_exchange: Exchange = None,
        generate_report: bool = False,
        verbose: bool = False,
        track_data: bool = False,
        common_infra: dict = {},
        **kwargs,
    ):
        """
        Parameters
        ----------
        inner_executor : BaseExecutor
            trading env in each trading bar.
        inner_strategy : BaseStrategy
            trading strategy in each trading bar
        trade_exchange : Exchange
            exchange that provides market info, used to generate report
            - If generate_report is None, trade_exchange will be ignored
            - Else If `trade_exchange` is None, self.trade_exchange will be set with common_infra
        """
        self.inner_executor = init_instance_by_config(
            inner_executor, common_infra=common_infra, accept_types=BaseExecutor
        )
        self.inner_strategy = init_instance_by_config(
            inner_strategy, common_infra=common_infra, accept_types=self.BaseStrategy
        )

        super(SplitExecutor, self).__init__(
            time_per_step=time_per_step,
            start_time=start_time,
            end_time=end_time,
            generate_report=generate_report,
            verbose=verbose,
            track_data=track_data,
            common_infra=common_infra,
            **kwargs,
        )

        if generate_report and trade_exchange is not None:
            self.trade_exchange = trade_exchange

    def reset_common_infra(self, common_infra):
        """
        reset infrastructure for trading
            - reset trade_exchange
            - reset inner_strategyand inner_executor common infra
        """
        super(SplitExecutor, self).reset_common_infra(common_infra)

        if self.generate_report and "trade_exchange" in common_infra:
            self.trade_exchange = common_infra.get("trade_exchange")

        self.inner_executor.reset_common_infra(common_infra)
        self.inner_strategy.reset_common_infra(common_infra)

    def _init_sub_trading(self, trade_decision):
        trade_index = self.calendar.get_trade_index()
        trade_start_time, trade_end_time = self.calendar.get_calendar_time(trade_index)
        self.inner_executor.reset(start_time=trade_start_time, end_time=trade_end_time)
        sub_level_infra = self.inner_executor.get_level_infra()
        self.inner_strategy.reset(level_infra=sub_level_infra, outer_trade_decision=trade_decision)

    def _update_trade_account(self):
        trade_index = self.calendar.get_trade_index()
        trade_start_time, trade_end_time = self.calendar.get_calendar_time(trade_index)
        self.trade_account.update_bar_count()
        if self.generate_report:
            self.trade_account.update_bar_report(
                trade_start_time=trade_start_time,
                trade_end_time=trade_end_time,
                trade_exchange=self.trade_exchange,
            )

    def execute(self, trade_decision):
        self.calendar.step()
        self._init_sub_trading(trade_decision)
        execute_result = []
        _inner_execute_result = None
        while not self.inner_executor.finished():
            _inner_trade_decision = self.inner_strategy.generate_trade_decision(_inner_execute_result)
            _inner_execute_result = self.inner_executor.execute(trade_decision=_inner_trade_decision)
            execute_result.extend(_inner_execute_result)
        if hasattr(self, "trade_account"):
            self._update_trade_account()

        return execute_result

    def collect_data(self, trade_decision):
        if self.track_data:
            yield trade_decision
        self.calendar.step()
        self._init_sub_trading(trade_decision)
        execute_result = []
        _inner_execute_result = None
        while not self.inner_executor.finished():
            _inner_trade_decision = self.inner_strategy.generate_trade_decision(_inner_execute_result)
            _inner_execute_result = yield from self.inner_executor.collect_data(trade_decision=_inner_trade_decision)
            execute_result.extend(_inner_execute_result)
        if hasattr(self, "trade_account"):
            self._update_trade_account()

        return execute_result

    def get_report(self):
        sub_env_report_dict = self.inner_executor.get_report()
        if self.generate_report:
            _report = self.trade_account.report.generate_report_dataframe()
            _positions = self.trade_account.get_positions()
            _count, _freq = parse_freq(self.time_per_step)
            sub_env_report_dict.update({f"{_count}{_freq}": (_report, _positions)})
        return sub_env_report_dict


class SimulatorExecutor(BaseExecutor):
    def __init__(
        self,
        time_per_step: str,
        start_time: Union[str, pd.Timestamp] = None,
        end_time: Union[str, pd.Timestamp] = None,
        trade_exchange: Exchange = None,
        generate_report: bool = False,
        verbose: bool = False,
        track_data: bool = False,
        common_infra: dict = {},
        **kwargs,
    ):
        """
        Parameters
        ----------
        trade_exchange : Exchange
            exchange that provides market info, used to deal order and generate report
            - If `trade_exchange` is None, self.trade_exchange will be set with common_infra
        """
        super(SimulatorExecutor, self).__init__(
            time_per_step=time_per_step,
            start_time=start_time,
            end_time=end_time,
            generate_report=generate_report,
            verbose=verbose,
            track_data=track_data,
            common_infra=common_infra,
            **kwargs,
        )
        if trade_exchange is not None:
            self.trade_exchange = trade_exchange

    def reset_common_infra(self, common_infra):
        """
        reset infrastructure for trading
            - reset trade_exchange
        """
        super(SimulatorExecutor, self).reset_common_infra(common_infra)
        if "trade_exchange" in common_infra:
            self.trade_exchange = common_infra.get("trade_exchange")

    def execute(self, trade_decision):
        self.calendar.step()
        trade_index = self.calendar.get_trade_index()
        trade_start_time, trade_end_time = self.calendar.get_calendar_time(trade_index)
        execute_result = []
        for order in trade_decision:
            if self.trade_exchange.check_order(order) is True:
                # execute the order
                trade_val, trade_cost, trade_price = self.trade_exchange.deal_order(
                    order, trade_account=self.trade_account
                )
                execute_result.append((order, trade_val, trade_cost, trade_price))
                if self.verbose:
                    if order.direction == Order.SELL:  # sell
                        print(
                            "[I {:%Y-%m-%d}]: sell {}, price {:.2f}, amount {}, deal_amount {}, factor {}, value {:.2f}.".format(
                                trade_start_time,
                                order.stock_id,
                                trade_price,
                                order.amount,
                                order.deal_amount,
                                order.factor,
                                trade_val,
                            )
                        )
                    else:
                        print(
                            "[I {:%Y-%m-%d}]: buy {}, price {:.2f}, amount {}, deal_amount {}, factor {}, value {:.2f}.".format(
                                trade_start_time,
                                order.stock_id,
                                trade_price,
                                order.amount,
                                order.deal_amount,
                                order.factor,
                                trade_val,
                            )
                        )

            else:
                if self.verbose:
                    print("[W {:%Y-%m-%d}]: {} wrong.".format(trade_start_time, order.stock_id))
                # do nothing
                pass

        self.trade_account.update_bar_count()

        if self.generate_report:
            self.trade_account.update_bar_report(
                trade_start_time=trade_start_time,
                trade_end_time=trade_end_time,
                trade_exchange=self.trade_exchange,
            )

        return execute_result

    def get_report(self):
        if self.generate_report:
            _report = self.trade_account.report.generate_report_dataframe()
            _positions = self.trade_account.get_positions()
            _count, _freq = parse_freq(self.time_per_step)
            return {f"{_count}{_freq}": (_report, _positions)}
        else:
            return {}
