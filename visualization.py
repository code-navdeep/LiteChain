"""
Options Analytics Visualization Engine
Creates interactive charts using Altair
"""

import altair as alt
import pandas as pd
import streamlit as st
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Colour scheme: calls red, puts green, everywhere; GEX bars by sign
COLORS = {
    'call': '#FF4444',         # Call options (red)
    'put': '#00C851',          # Put options (green)
    'positive': '#00C851',     # Positive GEX (green)
    'negative': '#FF4444',     # Negative GEX (red)
    'warning': '#FF8800'       # Current-price line (orange)
}


def format_gex_millions(value: float) -> str:
    """GEX (already in millions of units of the underlying) as text: three decimals and 'M',
    with a tiny negative value shown as 0.000M rather than -0.000M. Used by the chart, the
    table and the summary, so every place shows the same figure."""
    text = f'{value:.3f}'
    if text == '-0.000':
        text = '0.000'
    return f'{text}M'


def _strike_gap(strikes) -> float:
    """Smallest distance between neighbouring strikes; sizes the bars on a numeric strike axis."""
    values = sorted(set(float(s) for s in strikes))
    gaps = [b - a for a, b in zip(values, values[1:]) if b > a]
    if gaps:
        return min(gaps)
    return values[0] * 0.01 if values and values[0] > 0 else 1.0


def _place_call_put_bars(chart_data_long: pd.DataFrame, call_label: str, strikes) -> pd.DataFrame:
    """Give each bar a start and end on the numeric strike axis: the call bar just left of its
    strike, the put bar just right of it, each 40% of the gap between strikes wide."""
    half = _strike_gap(strikes) * 0.4
    is_call = (chart_data_long['option_type'] == call_label).astype(float)
    chart_data_long['bar_start'] = chart_data_long['strike'] - half * is_call
    chart_data_long['bar_end'] = chart_data_long['strike'] + half * (1.0 - is_call)
    return chart_data_long


def _strike_axis(strikes) -> alt.Axis:
    """Numeric strike axis with its labels on strikes; the chart library shows as many as fit the width."""
    values = sorted(set(float(s) for s in strikes))
    return alt.Axis(values=values, format=',.2~f', labelAngle=-45)


def _moneyness(strike: float, price: float, is_call: bool) -> str:
    """At, in or out of the money: within 2% of the price is ATM; a call is ITM below the price,
    a put is ITM above it."""
    if abs(strike - price) < price * 0.02:
        return 'ATM'
    if is_call:
        return 'ITM' if strike < price else 'OTM'
    return 'ITM' if strike > price else 'OTM'


def _add_bar_moneyness(chart_data_long: pd.DataFrame, call_label: str, price: float) -> pd.DataFrame:
    """Moneyness for each bar, from its own option type (the call bar and the put bar at one strike differ)."""
    chart_data_long['moneyness'] = [
        _moneyness(s, price, t == call_label)
        for s, t in zip(chart_data_long['strike'], chart_data_long['option_type'])
    ]
    return chart_data_long


def _price_line(price: float, axis: str = 'x') -> alt.Chart:
    """Dashed current-price line on a numeric strike axis."""
    line = alt.Chart(pd.DataFrame({'price': [price]})).mark_rule(
        color=COLORS['warning'],
        strokeWidth=2,
        strokeDash=[5, 5]
    )
    if axis == 'x':
        return line.encode(x=alt.X('price:Q', title='Strike Price'))
    return line.encode(y=alt.Y('price:Q', title='Strike Price'))


class ChartDataManager:
    """Unified data manager for extracting chart data from analytics report."""

    def __init__(self, analytics_report: Dict[str, Any]):
        """Initialize with analytics report."""
        self.report = analytics_report
        self.df = analytics_report.get('enhanced_dataframe', pd.DataFrame())
        self.underlying_price = self.df['underlying_price'].iloc[0] if not self.df.empty and 'underlying_price' in self.df.columns else 0
        self.available_strikes = set(self.df['strike'].unique()) if not self.df.empty else set()

    def get_gex_data(self) -> pd.DataFrame:
        """Get GEX by strike (in millions), for the strikes shown."""
        try:
            gex_analysis = self.report.get('gex_analysis', {})
            if not gex_analysis or not self.available_strikes:
                return pd.DataFrame()

            gex_by_strike = gex_analysis.get('gex_by_strike', {})

            gex_data = []
            for strike, gex_value in gex_by_strike.items():
                if strike in self.available_strikes:  # Only filtered strikes
                    # Same format as the table and the summary: millions, three decimals
                    gex_formatted = format_gex_millions(gex_value) if abs(gex_value) > 0 else '0'

                    gex_data.append({
                        'strike': strike,
                        'gex': gex_value,
                        'gex_formatted': gex_formatted,
                        'distance_from_spot': abs(strike - self.underlying_price)
                    })

            df = pd.DataFrame(gex_data)
            if df.empty:
                return df

            # Each bar centred on its strike on the numeric axis
            half = _strike_gap(df['strike']) * 0.4
            df['bar_start'] = df['strike'] - half
            df['bar_end'] = df['strike'] + half
            return df
        except Exception as e:
            logger.error(f"Error extracting GEX data: {e}")
            return pd.DataFrame()

    def _call_put_by_strike(self, column: str, call_name: str, put_name: str) -> pd.DataFrame:
        """One row per strike with the call and put values of a column."""
        data = self.df.groupby(['strike', 'option_type'])[column].sum().reset_index()
        pivot = data.pivot(index='strike', columns='option_type', values=column).fillna(0).reset_index()
        return pd.DataFrame([{
            'strike': row['strike'],
            call_name: row.get('CE', 0),
            put_name: row.get('PE', 0)
        } for _, row in pivot.iterrows()])

    def get_oi_distribution_data(self) -> pd.DataFrame:
        """Get OI distribution data, in lots (as in the table)."""
        if self.df.empty or 'oi_display' not in self.df.columns:
            return pd.DataFrame()
        try:
            return self._call_put_by_strike('oi_display', 'Calls', 'Puts')
        except Exception as e:
            logger.error(f"Error extracting OI distribution data: {e}")
            return pd.DataFrame()

    def get_volume_distribution_data(self) -> pd.DataFrame:
        """Get volume distribution data, in lots (as in the table)."""
        if self.df.empty or 'volume_display' not in self.df.columns:
            return pd.DataFrame()
        try:
            return self._call_put_by_strike('volume_display', 'Calls', 'Puts')
        except Exception as e:
            logger.error(f"Error extracting volume distribution data: {e}")
            return pd.DataFrame()

    def get_oi_change_distribution_data(self) -> pd.DataFrame:
        """Get OI Change distribution data, in lots (as in the table)."""
        if self.df.empty or 'oi_change_display' not in self.df.columns:
            return pd.DataFrame()
        try:
            return self._call_put_by_strike('oi_change_display', 'Calls', 'Puts')
        except Exception as e:
            logger.error(f"Error extracting OI change distribution data: {e}")
            return pd.DataFrame()

    def get_iv_smile_data(self) -> pd.DataFrame:
        """Get IV smile data."""
        if self.df.empty or 'iv' not in self.df.columns:
            return pd.DataFrame()

        try:
            iv_data = self.df[self.df['iv'] > 0].copy()
            if iv_data.empty:
                return pd.DataFrame()

            result_data = []
            for _, row in iv_data.iterrows():
                result_data.append({
                    'strike': row['strike'],
                    'option_type': row['option_type'],
                    'iv': row['iv'],
                    'moneyness': _moneyness(row['strike'], self.underlying_price, row['option_type'] == 'CE')
                })

            return pd.DataFrame(result_data)
        except Exception as e:
            logger.error(f"Error extracting IV smile data: {e}")
            return pd.DataFrame()

    def get_greeks_data(self, greek_name: str) -> pd.DataFrame:
        """Get Greeks data."""
        if self.df.empty or greek_name.lower() not in self.df.columns:
            return pd.DataFrame()

        try:
            greek_data = self.df[self.df[greek_name.lower()] != 0].copy()
            if greek_data.empty:
                return pd.DataFrame()

            result_data = []
            for _, row in greek_data.iterrows():
                result_data.append({
                    'strike': row['strike'],
                    'option_type': row['option_type'],
                    'greek_value': row[greek_name.lower()],
                    'moneyness': _moneyness(row['strike'], self.underlying_price, row['option_type'] == 'CE')
                })

            return pd.DataFrame(result_data)
        except Exception as e:
            logger.error(f"Error extracting {greek_name} data: {e}")
            return pd.DataFrame()

    def get_support_resistance_data(self) -> pd.DataFrame:
        """The three call strikes with the most open interest (resistance) and the three put
        strikes with the most (support), with their open interest in lots (as in the table)."""
        sr_data = self.report.get('support_resistance', {})
        if not sr_data or self.df.empty:
            return pd.DataFrame()

        def lots(strike, option_type):
            row = self.df[(self.df['strike'] == strike) & (self.df['option_type'] == option_type)]
            return float(row['oi_display'].iloc[0]) if not row.empty and 'oi_display' in row.columns else 0.0

        levels_data = []
        for level_type, option_type, key in (('Resistance', 'CE', 'resistance_levels'), ('Support', 'PE', 'support_levels')):
            for i, level in enumerate(sr_data.get(key, [])[:5]):  # Top 5
                levels_data.append({
                    'strike': level,
                    'oi': lots(level, option_type),
                    'level_type': level_type,
                    'strength': 'Strong' if i < 2 else 'Moderate',
                    'distance_from_spot': abs(level - self.underlying_price) if self.underlying_price > 0 else 0
                })

        df = pd.DataFrame(levels_data)
        if df.empty:
            return df

        # Resistance bar just above its strike, support just below, on the numeric strike axis
        half = _strike_gap(self.available_strikes if len(self.available_strikes) > 1 else df['strike']) * 0.4
        is_resistance = (df['level_type'] == 'Resistance').astype(float)
        df['bar_start'] = df['strike'] - half * (1.0 - is_resistance)
        df['bar_end'] = df['strike'] + half * is_resistance
        df['zero'] = 0.0
        return df.sort_values('strike')

class OptionsVisualization:
    """
    Simple chart manager - no caching, fresh renders every time.
    """

    def create_gex_chart(self, analytics_report: Dict[str, Any]) -> Optional[alt.Chart]:
        """Create GEX visualization (values in millions)."""
        try:
            data_manager = ChartDataManager(analytics_report)
            chart_data = data_manager.get_gex_data()

            if chart_data.empty:
                return None

            gex_analysis = analytics_report.get('gex_analysis', {})

            # Base chart with zoom
            base = alt.Chart(chart_data).add_params(
                alt.selection_interval(bind='scales')
            )

            # GEX bars, centred on each strike
            gex_bars = base.mark_bar(
                opacity=0.8,
                stroke='white',
                strokeWidth=0.5
            ).encode(
                x=alt.X('bar_start:Q', title='Strike Price', scale=alt.Scale(zero=False),
                        axis=_strike_axis(chart_data['strike'])),
                x2='bar_end:Q',
                y=alt.Y('gex:Q', title='Gamma Exposure (Millions)', scale=alt.Scale(zero=True)),
                y2=alt.datum(0),
                color=alt.condition(
                    alt.datum.gex > 0,
                    alt.value(COLORS['positive']),
                    alt.value(COLORS['negative'])
                ),
                tooltip=[
                    alt.Tooltip('strike:O', title='Strike'),
                    alt.Tooltip('gex_formatted:N', title='GEX'),
                    alt.Tooltip('distance_from_spot:Q', title='Distance from Spot', format='.2f')
                ]
            )

            # Zero line
            zero_line = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(
                strokeWidth=1
            ).encode(y='y:Q')

            layered = gex_bars + zero_line
            if data_manager.underlying_price > 0:
                layered = layered + _price_line(data_manager.underlying_price)

            chart = layered.properties(
                width=400,
                height=400,
                title=alt.TitleParams(
                    text=f"Gamma Exposure by Strike | Total GEX: {format_gex_millions(gex_analysis.get('total_gex', 0))}",
                    fontSize=16,
                    anchor='start'
                )
            ).configure_view(
                strokeWidth=0
            )

            return chart

        except Exception as e:
            logger.error(f"Error creating GEX chart: {e}")
            return None

    def create_oi_distribution_chart(self, analytics_report: Dict[str, Any]) -> Optional[alt.Chart]:
        """Create Open Interest distribution visualization (in lots)."""
        try:
            data_manager = ChartDataManager(analytics_report)
            chart_data = data_manager.get_oi_distribution_data()

            if chart_data.empty:
                return None

            # One row per bar: strike, option type, value
            chart_data_long = pd.melt(
                chart_data,
                id_vars=['strike'],
                value_vars=['Calls', 'Puts'],
                var_name='option_type',
                value_name='oi'
            )
            chart_data_long = _place_call_put_bars(chart_data_long, 'Calls', chart_data['strike'])
            chart_data_long = _add_bar_moneyness(chart_data_long, 'Calls', data_manager.underlying_price)

            base = alt.Chart(chart_data_long).add_params(
                alt.selection_interval(bind='scales', encodings=['x'])
            )

            # Calls left of each strike, puts right of it
            oi_bars = base.mark_bar(
                opacity=0.8,
                stroke='white',
                strokeWidth=0.5
            ).encode(
                x=alt.X('bar_start:Q', title='Strike Price', scale=alt.Scale(zero=False),
                        axis=_strike_axis(chart_data['strike'])),
                x2='bar_end:Q',
                y=alt.Y('oi:Q', title='Open Interest (lots)', scale=alt.Scale(type='sqrt')),
                y2=alt.datum(0),
                color=alt.Color(
                    'option_type:N',
                    title='Option Type',
                    scale=alt.Scale(
                        domain=['Calls', 'Puts'],
                        range=[COLORS['call'], COLORS['put']]
                    ),
                    legend=alt.Legend(title="Option Type")
                ),
                tooltip=[
                    alt.Tooltip('strike:O', title='Strike'),
                    alt.Tooltip('oi:Q', title='Open Interest (lots)', format=',.0f'),
                    alt.Tooltip('option_type:N', title='Type'),
                    alt.Tooltip('moneyness:N', title='Moneyness')
                ]
            ).properties(
                width=800,
                height=400,
                title=alt.TitleParams(
                    text="Open Interest Distribution - Calls vs Puts",
                    fontSize=16,
                    anchor='start'
                )
            )

            layered = oi_bars
            if data_manager.underlying_price > 0:
                layered = layered + _price_line(data_manager.underlying_price)

            chart = layered.configure_view(
                strokeWidth=0
            )

            return chart

        except Exception as e:
            logger.error(f"Error creating OI distribution chart: {e}")
            return None

    def create_oi_change_distribution_chart(self, analytics_report: Dict[str, Any]) -> Optional[alt.Chart]:
        """Create OI Change distribution visualization (in lots)."""
        try:
            data_manager = ChartDataManager(analytics_report)
            chart_data = data_manager.get_oi_change_distribution_data()

            if chart_data.empty:
                return None

            # One row per bar: strike, option type, value
            chart_data_long = pd.melt(
                chart_data,
                id_vars=['strike'],
                value_vars=['Calls', 'Puts'],
                var_name='option_type',
                value_name='oi_change'
            )
            chart_data_long = _place_call_put_bars(chart_data_long, 'Calls', chart_data['strike'])
            chart_data_long = _add_bar_moneyness(chart_data_long, 'Calls', data_manager.underlying_price)
            chart_data_long['change_type'] = chart_data_long['oi_change'].apply(
                lambda x: 'Increase' if x > 0 else ('Decrease' if x < 0 else 'No Change')
            )

            base = alt.Chart(chart_data_long).add_params(
                alt.selection_interval(bind='scales', encodings=['x'])
            )

            # Calls left of each strike, puts right of it
            oi_change_bars = base.mark_bar(
                opacity=0.8,
                stroke='white',
                strokeWidth=0.5
            ).encode(
                x=alt.X('bar_start:Q', title='Strike Price', scale=alt.Scale(zero=False),
                        axis=_strike_axis(chart_data['strike'])),
                x2='bar_end:Q',
                y=alt.Y('oi_change:Q', title='OI Change (lots)', scale=alt.Scale(zero=True)),
                y2=alt.datum(0),
                color=alt.Color(
                    'option_type:N',
                    title='Option Type',
                    scale=alt.Scale(
                        domain=['Calls', 'Puts'],
                        range=[COLORS['call'], COLORS['put']]
                    ),
                    legend=alt.Legend(title="Option Type")
                ),
                tooltip=[
                    alt.Tooltip('strike:O', title='Strike'),
                    alt.Tooltip('oi_change:Q', title='OI Change (lots)', format='+,.0f'),
                    alt.Tooltip('option_type:N', title='Type'),
                    alt.Tooltip('change_type:N', title='Direction'),
                    alt.Tooltip('moneyness:N', title='Moneyness')
                ]
            ).properties(
                width=800,
                height=400,
                title=alt.TitleParams(
                    text="OI Change Distribution - New Positions vs Closures",
                    fontSize=16,
                    anchor='start'
                )
            )

            # Zero line for reference
            zero_line = alt.Chart(pd.DataFrame({'y': [0]})).mark_rule(
                strokeWidth=1,
                strokeDash=[2, 2]
            ).encode(y='y:Q')

            layered = oi_change_bars + zero_line
            if data_manager.underlying_price > 0:
                layered = layered + _price_line(data_manager.underlying_price)

            chart = layered.configure_view(
                strokeWidth=0
            )

            return chart

        except Exception as e:
            logger.error(f"Error creating OI change distribution chart: {e}")
            return None

    def create_volume_distribution_chart(self, analytics_report: Dict[str, Any]) -> Optional[alt.Chart]:
        """Create Volume distribution visualization (in lots)."""
        try:
            data_manager = ChartDataManager(analytics_report)
            chart_data = data_manager.get_volume_distribution_data()

            if chart_data.empty:
                return None

            # One row per bar: strike, option type, value
            chart_data_long = pd.melt(
                chart_data,
                id_vars=['strike'],
                value_vars=['Calls', 'Puts'],
                var_name='option_type',
                value_name='volume'
            )
            chart_data_long = _place_call_put_bars(chart_data_long, 'Calls', chart_data['strike'])
            chart_data_long = _add_bar_moneyness(chart_data_long, 'Calls', data_manager.underlying_price)

            base = alt.Chart(chart_data_long).add_params(
                alt.selection_interval(bind='scales', encodings=['x'])
            )

            # Calls left of each strike, puts right of it
            volume_bars = base.mark_bar(
                opacity=0.8,
                stroke='white',
                strokeWidth=0.5
            ).encode(
                x=alt.X('bar_start:Q', title='Strike Price', scale=alt.Scale(zero=False),
                        axis=_strike_axis(chart_data['strike'])),
                x2='bar_end:Q',
                y=alt.Y('volume:Q', title='Trading Volume (lots)', scale=alt.Scale(type='sqrt')),
                y2=alt.datum(0),
                color=alt.Color(
                    'option_type:N',
                    title='Option Type',
                    scale=alt.Scale(
                        domain=['Calls', 'Puts'],
                        range=[COLORS['call'], COLORS['put']]
                    ),
                    legend=alt.Legend(title="Option Type")
                ),
                tooltip=[
                    alt.Tooltip('strike:O', title='Strike'),
                    alt.Tooltip('volume:Q', title='Volume (lots)', format=',.0f'),
                    alt.Tooltip('option_type:N', title='Type'),
                    alt.Tooltip('moneyness:N', title='Moneyness')
                ]
            ).properties(
                width=800,
                height=400,
                title=alt.TitleParams(
                    text="Volume Distribution - Calls vs Puts",
                    fontSize=16,
                    anchor='start'
                )
            )

            layered = volume_bars
            if data_manager.underlying_price > 0:
                layered = layered + _price_line(data_manager.underlying_price)

            chart = layered.configure_view(
                strokeWidth=0
            )

            return chart

        except Exception as e:
            logger.error(f"Error creating volume distribution chart: {e}")
            return None

    def create_iv_smile_chart(self, analytics_report: Dict[str, Any]) -> Optional[alt.Chart]:
        """Create IV smile curve visualization."""
        try:
            data_manager = ChartDataManager(analytics_report)
            chart_data = data_manager.get_iv_smile_data()

            if chart_data.empty:
                return None

            base = alt.Chart(chart_data)

            # IV smile curves - separate lines for calls and puts
            iv_lines = base.mark_line(
                point=True,
                strokeWidth=3
            ).encode(
                x=alt.X('strike:Q', title='Strike Price'),
                y=alt.Y('iv:Q', title='Implied Volatility (%)', scale=alt.Scale(zero=False)),
                color=alt.Color(
                    'option_type:N',
                    title='Option Type',
                    scale=alt.Scale(
                        domain=['CE', 'PE'],
                        range=[COLORS['call'], COLORS['put']]
                    )
                ),
                tooltip=[
                    alt.Tooltip('strike:Q', title='Strike'),
                    alt.Tooltip('iv:Q', title='IV', format='.2f'),
                    alt.Tooltip('option_type:N', title='Type'),
                    alt.Tooltip('moneyness:N', title='Moneyness')
                ]
            ).properties(
                width=600,
                height=300,
                title=alt.TitleParams(
                    text="IV Smile Curve",
                    fontSize=16,
                    anchor='start'
                )
            )

            layered = iv_lines
            if data_manager.underlying_price > 0:
                layered = layered + _price_line(data_manager.underlying_price)

            chart = layered.configure_view(
                strokeWidth=0
            )

            return chart

        except Exception as e:
            logger.error(f"Error creating IV smile chart: {e}")
            return None

    def create_greek_distribution_chart(self, analytics_report: Dict[str, Any], greek_name: str) -> Optional[alt.Chart]:
        """Create Greek distribution visualization."""
        try:
            data_manager = ChartDataManager(analytics_report)
            chart_data = data_manager.get_greeks_data(greek_name)

            if chart_data.empty:
                return None

            base = alt.Chart(chart_data).add_params(
                alt.selection_interval(bind='scales', encodings=['x'])
            )

            # Tight X-axis domain from the data: 2% padding instead of Altair's 5%
            min_strike = chart_data['strike'].min()
            max_strike = chart_data['strike'].max()
            strike_padding = (max_strike - min_strike) * 0.02
            x_domain = [min_strike - strike_padding, max_strike + strike_padding]

            # Greek distribution scatter plot
            greek_scatter = base.mark_circle(
                size=100,
                opacity=0.8,
                stroke='white',
                strokeWidth=1
            ).encode(
                x=alt.X('strike:Q', title='Strike Price', scale=alt.Scale(domain=x_domain)),
                y=alt.Y('greek_value:Q', title=f'{greek_name.title()} Value', scale=alt.Scale(zero=False)),
                color=alt.Color(
                    'option_type:N',
                    title='Option Type',
                    scale=alt.Scale(
                        domain=['CE', 'PE'],
                        range=[COLORS['call'], COLORS['put']]
                    )
                ),
                tooltip=[
                    alt.Tooltip('strike:Q', title='Strike'),
                    alt.Tooltip('greek_value:Q', title=f'{greek_name.title()}', format='.4f'),
                    alt.Tooltip('option_type:N', title='Type'),
                    alt.Tooltip('moneyness:N', title='Moneyness')
                ]
            ).properties(
                width=350,
                height=300,
                title=alt.TitleParams(
                    text=f"{greek_name.title()} Distribution by Strike",
                    fontSize=14,
                    anchor='start'
                )
            )

            layered = greek_scatter
            if data_manager.underlying_price > 0:
                layered = layered + alt.Chart(pd.DataFrame({'price': [data_manager.underlying_price]})).mark_rule(
                    color=COLORS['warning'],
                    strokeWidth=2,
                    strokeDash=[5, 5]
                ).encode(
                    x=alt.X('price:Q', title='Strike Price', scale=alt.Scale(domain=x_domain))
                )

            chart = layered.configure_view(
                strokeWidth=0
            )

            return chart

        except Exception as e:
            logger.error(f"Error creating {greek_name} distribution chart: {e}")
            return None

    def create_support_resistance_chart(self, analytics_report: Dict[str, Any]) -> Optional[alt.Chart]:
        """Create support and resistance levels visualization (open interest in lots)."""
        try:
            data_manager = ChartDataManager(analytics_report)
            chart_data = data_manager.get_support_resistance_data()

            if chart_data.empty:
                return None

            # Horizontal bars on a numeric strike axis (vertical)
            base = alt.Chart(chart_data)

            sr_bars = base.mark_bar(
                opacity=0.8,
                stroke='white',
                strokeWidth=1
            ).encode(
                y=alt.Y('bar_start:Q', title='Strike Price', scale=alt.Scale(zero=False),
                        axis=alt.Axis(values=sorted(chart_data['strike'].unique()), format=',.2~f')),
                y2='bar_end:Q',
                x=alt.X('zero:Q', title='Open Interest (lots)', scale=alt.Scale(type='sqrt')),
                x2='oi:Q',
                color=alt.Color(
                    'level_type:N',
                    title='Level Type',
                    scale=alt.Scale(
                        domain=['Support', 'Resistance'],
                        range=[COLORS['put'], COLORS['call']]
                    )
                ),
                tooltip=[
                    alt.Tooltip('strike:O', title='Strike'),
                    alt.Tooltip('oi:Q', title='Open Interest (lots)', format=',.0f'),
                    alt.Tooltip('level_type:N', title='Type'),
                    alt.Tooltip('strength:N', title='Strength'),
                    alt.Tooltip('distance_from_spot:Q', title='Distance from Spot', format='.2f')
                ]
            ).properties(
                width=600,
                height=400,
                title=alt.TitleParams(
                    text="Support & Resistance Levels",
                    fontSize=16,
                    anchor='start'
                )
            )

            layered = sr_bars
            if data_manager.underlying_price > 0:
                layered = layered + _price_line(data_manager.underlying_price, axis='y')

            chart = layered.configure_view(
                strokeWidth=0
            )

            return chart

        except Exception as e:
            logger.error(f"Error creating support/resistance chart: {e}")
            return None

    def _display_chart(self, chart_type: str, chart_creator_func, analytics_report: Dict[str, Any]) -> None:
        """Simple chart display - create fresh every time."""
        try:
            with st.spinner(f"Creating {chart_type.replace('_', ' ').title()} chart..."):
                # Create fresh chart every time
                chart = chart_creator_func(analytics_report)

                if chart is not None:
                    st.altair_chart(chart, width="stretch")
                else:
                    st.warning(f"Unable to create {chart_type.replace('_', ' ').title()} chart.")

        except Exception as e:
            logger.error(f"Error displaying {chart_type} chart: {e}")
            st.error(f"Failed to display {chart_type} chart: {str(e)}")

    def create_comprehensive_dashboard(self, analytics_report: Dict[str, Any]) -> None:
        """
        Create the options analytics dashboard with all charts.

        Args:
            analytics_report: Analytics report from integrated.py
        """
        try:
            if not self._validate_analytics_report(analytics_report):
                st.error("Invalid or incomplete analytics data")
                return

            # Charts layout
            col1, col2 = st.columns(2)

            with col1:
                self._display_chart('gex', self.create_gex_chart, analytics_report)

            with col2:
                self._display_chart('iv_smile', self.create_iv_smile_chart, analytics_report)

            # Two-column layout for OI analysis
            col1, col2 = st.columns(2)

            with col1:
                self._display_chart('oi_distribution', self.create_oi_distribution_chart, analytics_report)

            with col2:
                self._display_chart('oi_change_distribution', self.create_oi_change_distribution_chart, analytics_report)

            # Second row: Volume and Support/Resistance
            col1, col2 = st.columns(2)

            with col1:
                self._display_chart('volume_distribution', self.create_volume_distribution_chart, analytics_report)

            with col2:
                self._display_chart('support_resistance', self.create_support_resistance_chart, analytics_report)

            # Greeks Distribution Charts (2x2 grid)
            col1, col2 = st.columns(2)

            with col1:
                # Delta and Gamma
                self._display_chart('delta_distribution',
                    lambda report: self.create_greek_distribution_chart(report, 'Delta'),
                    analytics_report)

                self._display_chart('gamma_distribution',
                    lambda report: self.create_greek_distribution_chart(report, 'Gamma'),
                    analytics_report)

            with col2:
                # Vega and Theta
                self._display_chart('vega_distribution',
                    lambda report: self.create_greek_distribution_chart(report, 'Vega'),
                    analytics_report)

                self._display_chart('theta_distribution',
                    lambda report: self.create_greek_distribution_chart(report, 'Theta'),
                    analytics_report)

        except Exception as e:
            logger.error(f"Error creating comprehensive dashboard: {e}")
            st.error(f"Dashboard creation failed: {str(e)}")

    def _validate_analytics_report(self, analytics_report: Dict[str, Any]) -> bool:
        """Validate analytics report has required structure."""
        if not analytics_report or analytics_report.get('error'):
            return False

        if 'enhanced_dataframe' not in analytics_report:
            logger.error("Missing required key in analytics report: enhanced_dataframe")
            return False

        # Check if DataFrame is valid
        df = analytics_report.get('enhanced_dataframe', pd.DataFrame())
        if df.empty:
            logger.warning("Enhanced dataframe is empty")
            return False

        # Check for required columns
        required_columns = ['strike', 'option_type', 'oi', 'volume']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            logger.error(f"Missing required columns in dataframe: {missing_columns}")
            return False

        return True
