"""
Integrated Dhan Options Analytics Engine
Fetches option chains from Dhan's API and works out the analytics the dashboard shows
"""

import pandas as pd
import numpy as np
import logging
import time
import math
from datetime import date, datetime, timedelta, timezone
import requests
from typing import Optional, Dict, List, Tuple
from scipy.stats import norm

# Minimal logging - only critical errors
logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

# India Standard Time is always 5 h 30 min ahead of UTC (India has no daylight saving),
# so it needs no time-zone database; the Docker container's own clock runs on UTC.
INDIA_TIME = timezone(timedelta(hours=5, minutes=30))


def _nth_sunday(year: int, month: int, n: int) -> date:
    """The n-th Sunday of a month."""
    first = date(year, month, 1)
    return first + timedelta(days=(6 - first.weekday()) % 7 + 7 * (n - 1))


def market_close(market: str, day: date) -> Tuple[int, int]:
    """Closing time (India time) of the market on a given day.
    NSE: 15:30. MCX (crude oil, natural gas, gold): 23:30 while the US is on daylight saving
    time (second Sunday of March to first Sunday of November), 23:55 otherwise."""
    if market == 'MCX':
        us_summer = _nth_sunday(day.year, 3, 2) <= day < _nth_sunday(day.year, 11, 1)
        return (23, 30) if us_summer else (23, 55)
    return (15, 30)

class DhanOptionsAnalytics:
    """
    Integrated Dhan client with built-in analytics engine.
    Optimized for single-provider use with direct data flow.
    """

    def __init__(self, client_id: str, access_token: str, lot_size=75):
        """
        Initialize Dhan client with credentials and analytics configuration.

        Args:
            client_id: Dhan client ID
            access_token: Dhan access token
            lot_size: Contract lot size for calculations
        """
        # Dhan API configuration
        self.client_id = client_id
        self.access_token = access_token
        self.base_url = "https://api.dhan.co/v2"

        # Analytics configuration
        self.lot_size = lot_size

        # Rate limiting
        self.base_rate_limit_delay = 3.0
        self.adaptive_delay = self.base_rate_limit_delay
        self.last_request_time = 0
        self.max_retries = 3

        # Request tracking
        self.request_stats = {
            'success_count': 0,
            'error_count': 0
        }

    def _adaptive_rate_limit(self):
        """Adaptive rate limiting based on API response patterns."""
        current_time = time.time()
        time_since_last_request = current_time - self.last_request_time

        if self.request_stats['error_count'] > 0:
            error_ratio = self.request_stats['error_count'] / max(1, self.request_stats['success_count'])
            self.adaptive_delay = min(10.0, self.base_rate_limit_delay * (1 + error_ratio))
        else:
            self.adaptive_delay = max(1.0, self.adaptive_delay * 0.9)

        if time_since_last_request < self.adaptive_delay:
            sleep_time = self.adaptive_delay - time_since_last_request
            time.sleep(sleep_time)

        self.last_request_time = time.time()

    def _make_api_request(self, endpoint: str, payload: Dict, retries: int = None) -> Optional[Dict]:
        """Make API request with proper error handling and retries."""
        if retries is None:
            retries = self.max_retries

        headers = {
            'access-token': self.access_token,
            'client-id': self.client_id,
            'Content-Type': 'application/json'
        }

        url = f"{self.base_url}{endpoint}"

        for attempt in range(retries + 1):
            try:
                self._adaptive_rate_limit()

                response = requests.post(url, headers=headers, json=payload, timeout=30)

                if response.status_code == 429:
                    self.adaptive_delay = min(10.0, self.adaptive_delay * 2)
                    self.request_stats['error_count'] += 1

                    if attempt < retries:
                        time.sleep(self.adaptive_delay)
                        continue
                    else:
                        raise requests.exceptions.RequestException("Rate limit exceeded")

                response.raise_for_status()
                result = response.json()

                self.request_stats['success_count'] += 1

                return result

            except requests.exceptions.RequestException as e:
                self.request_stats['error_count'] += 1

                logger.error(f"API request failed (attempt {attempt + 1}): {e}")

                if attempt < retries:
                    wait_time = (attempt + 1) * 2
                    time.sleep(wait_time)
                else:
                    logger.error(f"API request failed after {retries + 1} attempts: {endpoint}")
                    return None

        return None

    def validate_input(self, underlying_scrip: int, underlying_seg: str, expiry: str = None) -> Tuple[bool, str]:
        """Validate input parameters."""
        if not isinstance(underlying_scrip, int) or underlying_scrip <= 0:
            return False, f"Invalid asset ID: {underlying_scrip}"

        valid_segments = ['IDX_I', 'NSE_EQ', 'MCX_COMM', 'CME', 'CRYPTO']
        if underlying_seg not in valid_segments:
            return False, f"Invalid segment: {underlying_seg}. Must be one of {valid_segments}"

        if expiry:
            try:
                expiry_date = datetime.strptime(expiry, '%Y-%m-%d')
                if expiry_date.date() < datetime.now(INDIA_TIME).date():
                    return False, f"Expiry date {expiry} is in the past"
            except ValueError:
                return False, f"Invalid expiry date format: {expiry}. Use YYYY-MM-DD"

        return True, "Valid"

    def get_expiry_list(self, underlying_scrip: int = 13, underlying_seg: str = "IDX_I") -> List[str]:
        """Get list of available expiry dates."""
        is_valid, error_msg = self.validate_input(underlying_scrip, underlying_seg)
        if not is_valid:
            logger.error(f"Input validation failed: {error_msg}")
            return []

        try:
            payload = {
                "UnderlyingScrip": underlying_scrip,
                "UnderlyingSeg": underlying_seg
            }

            response = self._make_api_request("/optionchain/expirylist", payload)

            if response and response.get('status') == 'success':
                expiry_list = response.get('data', [])
                return expiry_list
            else:
                logger.error(f"Failed to get expiry list: {response}")
                return []

        except Exception as e:
            logger.error(f"Error getting expiry list: {e}")
            return []

    def fetch_option_chain(self, expiry: str = None, underlying_scrip: int = 13, underlying_seg: str = "IDX_I") -> Optional[Dict]:
        """Fetch option chain data with comprehensive error handling."""
        is_valid, error_msg = self.validate_input(underlying_scrip, underlying_seg, expiry)
        if not is_valid:
            logger.error(f"Input validation failed: {error_msg}")
            return None

        try:
            if not expiry:
                expiry_list = self.get_expiry_list(underlying_scrip, underlying_seg)
                if not expiry_list:
                    logger.error("No expiry dates available")
                    return None
                expiry = expiry_list[0]

            payload = {
                "UnderlyingScrip": underlying_scrip,
                "UnderlyingSeg": underlying_seg,
                "Expiry": expiry
            }

            response = self._make_api_request("/optionchain", payload)

            if response and response.get('data'):
                return response['data']
            else:
                logger.error(f"Failed to fetch option chain: {response}")
                return None

        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            return None

    def get_underlying_quote(self, underlying_scrip: int, underlying_seg: str) -> float:
        """Get real-time underlying price from Dhan Market Quote API."""
        try:
            # Map segment to API format
            segment_map = {
                'MCX_COMM': 'MCX_COMM',
                'NSE_EQ': 'NSE_EQ',
                'IDX_I': 'NSE_EQ'  # Index traded on NSE
            }

            api_segment = segment_map.get(underlying_seg, 'NSE_EQ')

            payload = {
                api_segment: [underlying_scrip]
            }

            logger.info(f"Fetching underlying quote for {underlying_scrip} in {api_segment}")
            response = self._make_api_request("/marketfeed/ltp", payload)

            if response and response.get('status') == 'success':
                data = response.get('data', {})
                segment_data = data.get(api_segment, {})
                asset_data = segment_data.get(str(underlying_scrip), {})

                if asset_data:
                    last_price = asset_data.get('last_price', 0)
                    logger.info(f"Retrieved real-time underlying price: {last_price} for asset {underlying_scrip}")
                    return float(last_price) if last_price else 0
                else:
                    logger.warning(f"No data found for asset {underlying_scrip} in quote response")
                    return 0
            else:
                logger.error(f"Failed to get underlying quote: {response}")
                return 0

        except Exception as e:
            logger.error(f"Error fetching underlying quote for {underlying_scrip}: {e}")
            return 0

    def _normalize_commodity_data(self, parsed_data: List[Dict], segment: str) -> List[Dict]:
        """Normalize commodity data to match standard format."""
        if segment != 'MCX_COMM':
            return parsed_data  # No changes for Index/Equity

        # Commodity normalization: Convert lots back to contracts for internal consistency
        for record in parsed_data:
            record['oi'] = record['oi'] * self.lot_size
            record['previous_oi'] = record['previous_oi'] * self.lot_size
            record['volume'] = record['volume'] * self.lot_size
            # Recalculate oi_change after normalization
            record['oi_change'] = record['oi'] - record['previous_oi']

            # Greeks are already per unit for commodity - no change needed

        logger.info(f"Normalized {len(parsed_data)} commodity records from lots to contracts")
        return parsed_data

    def parse_option_chain(self, option_chain_data: Dict, underlying_scrip: int = 13, underlying_seg: str = "IDX_I") -> pd.DataFrame:
        """Parse option chain data into pandas DataFrame."""
        if not option_chain_data:
            logger.warning("No option chain data to parse")
            return pd.DataFrame()

        try:
            underlying_price = option_chain_data.get('last_price', 0)

            # COMMODITY ENHANCEMENT: Get real-time underlying price from Market Quote API
            if underlying_seg == 'MCX_COMM':
                real_time_price = self.get_underlying_quote(underlying_scrip, underlying_seg)
                if real_time_price > 0:
                    original_price = underlying_price
                    underlying_price = real_time_price
                    logger.info(f"COMMODITY: Updated underlying_price from {original_price} (option chain) to {real_time_price} (real-time quote)")
                else:
                    logger.warning(f"COMMODITY: Failed to get real-time price, using option chain price: {underlying_price}")

            # DEBUG: Log underlying price extraction
            logger.info(f"Final underlying_price: {underlying_price} (type: {type(underlying_price)}) for segment {underlying_seg}")

            option_chain = option_chain_data.get('oc', {})

            if not option_chain:
                logger.warning("No option chain data in response")
                return pd.DataFrame()

            parsed_data = []

            for strike_str, strike_data in option_chain.items():
                try:
                    strike = float(strike_str)
                except (ValueError, TypeError):
                    logger.warning(f"Invalid strike price: {strike_str}")
                    continue

                # Process Call option
                if 'ce' in strike_data and strike_data['ce']:
                    ce_data = strike_data['ce']
                    greeks = ce_data.get('greeks', {})

                    current_oi = ce_data.get('oi', 0) or 0
                    previous_oi = ce_data.get('previous_oi', 0) or 0
                    oi_change = current_oi - previous_oi

                    parsed_data.append({
                        'strike': strike,
                        'option_type': 'CE',
                        'last_price': ce_data.get('last_price', 0) or 0,
                        'oi': current_oi,
                        'previous_oi': previous_oi,
                        'oi_change': oi_change,
                        'volume': ce_data.get('volume', 0) or 0,
                        'iv': ce_data.get('implied_volatility', 0) or 0,
                        'delta': greeks.get('delta', 0) or 0,
                        'gamma': greeks.get('gamma', 0) or 0,
                        'theta': greeks.get('theta', 0) or 0,
                        'vega': greeks.get('vega', 0) or 0,
                        'bid_price': ce_data.get('top_bid_price', 0) or 0,
                        'ask_price': ce_data.get('top_ask_price', 0) or 0,
                        'underlying_price': underlying_price,
                        'underlying_asset_id': underlying_scrip,
                        'segment_code': underlying_seg
                    })

                # Process Put option
                if 'pe' in strike_data and strike_data['pe']:
                    pe_data = strike_data['pe']
                    greeks = pe_data.get('greeks', {})

                    current_oi = pe_data.get('oi', 0) or 0
                    previous_oi = pe_data.get('previous_oi', 0) or 0
                    oi_change = current_oi - previous_oi

                    parsed_data.append({
                        'strike': strike,
                        'option_type': 'PE',
                        'last_price': pe_data.get('last_price', 0) or 0,
                        'oi': current_oi,
                        'previous_oi': previous_oi,
                        'oi_change': oi_change,
                        'volume': pe_data.get('volume', 0) or 0,
                        'iv': pe_data.get('implied_volatility', 0) or 0,
                        'delta': greeks.get('delta', 0) or 0,
                        'gamma': greeks.get('gamma', 0) or 0,
                        'theta': greeks.get('theta', 0) or 0,
                        'vega': greeks.get('vega', 0) or 0,
                        'bid_price': pe_data.get('top_bid_price', 0) or 0,
                        'ask_price': pe_data.get('top_ask_price', 0) or 0,
                        'underlying_price': underlying_price,
                        'underlying_asset_id': underlying_scrip,
                        'segment_code': underlying_seg
                    })

            if not parsed_data:
                logger.warning("No valid option data parsed")
                return pd.DataFrame()

            # NORMALIZATION LAYER: Handle commodity data differences
            parsed_data = self._normalize_commodity_data(parsed_data, underlying_seg)

            df = pd.DataFrame(parsed_data)
            logger.info(f"Parsed {len(df)} option records for asset {underlying_scrip}")

            return df

        except Exception as e:
            logger.error(f"Error parsing option chain: {e}")
            return pd.DataFrame()

    # ANALYTICS METHODS - Direct integration from core_metrics

    def calculate_max_pain(self, df):
        """Calculate max pain strike from option chain data."""
        if df.empty:
            return 0

        try:
            strikes = np.array(sorted(df['strike'].unique()))

            calls = df[df['option_type'] == 'CE']
            puts = df[df['option_type'] == 'PE']

            call_oi_map = dict(zip(calls['strike'], calls['oi']))
            put_oi_map = dict(zip(puts['strike'], puts['oi']))

            pain_values = []

            for test_strike in strikes:
                total_writer_payout = 0

                for strike in strikes:
                    if test_strike > strike:
                        oi = call_oi_map.get(strike, 0)
                        writer_payout = (test_strike - strike) * oi
                        total_writer_payout += writer_payout

                for strike in strikes:
                    if test_strike < strike:
                        oi = put_oi_map.get(strike, 0)
                        writer_payout = (strike - test_strike) * oi
                        total_writer_payout += writer_payout

                pain_values.append(total_writer_payout)

            if pain_values:
                min_pain_idx = np.argmin(pain_values)
                max_pain_strike = strikes[min_pain_idx]
                logger.info(f"Max Pain: {max_pain_strike} (min payout: {pain_values[min_pain_idx]:,.0f})")
                return float(max_pain_strike)

            return 0

        except Exception as e:
            logger.error(f"Error in max pain calculation: {e}")
            return 0

    def estimate_gamma_exposure(self, df):
        """Estimate gamma exposure with dealer perspective. Values are returned in millions."""
        if df.empty:
            return {}

        try:
            underlying_price = df['underlying_price'].iloc[0]
            if underlying_price <= 0:
                return {}

            df_calc = df.copy()

            df_calc['base_gex'] = (0.01 * underlying_price *
                                 df_calc['oi'] * df_calc['gamma'])

            df_calc['gamma_exposure'] = np.where(
                df_calc['option_type'] == 'CE',
                -df_calc['base_gex'],
                df_calc['base_gex']
            )

            call_gex = df_calc[df_calc['option_type'] == 'CE']['gamma_exposure'].sum()
            put_gex = df_calc[df_calc['option_type'] == 'PE']['gamma_exposure'].sum()
            total_gex = call_gex + put_gex

            gex_by_strike = df_calc.groupby('strike')['gamma_exposure'].sum().to_dict()

            SCALE_FACTOR = 1_000_000

            return {
                'total_gex': total_gex / SCALE_FACTOR,
                'call_gex': call_gex / SCALE_FACTOR,
                'put_gex': put_gex / SCALE_FACTOR,
                'gex_by_strike': {k: v / SCALE_FACTOR for k, v in gex_by_strike.items()}
            }

        except Exception as e:
            logger.error(f"Error in GEX calculation: {e}")
            return {}

    def estimate_volatility_exposure(self, df):
        """Estimate volatility exposure (VEX) with dealer perspective."""
        if df.empty:
            return {}

        try:
            underlying_price = df['underlying_price'].iloc[0]
            if underlying_price <= 0:
                return {}

            df_calc = df.copy()

            # VEX calculation: vega * oi / lot_size (simple, clean)
            df_calc['volatility_exposure'] = (df_calc['vega'] * df_calc['oi']) / self.lot_size

            # Separate call and put VEX for relative analysis
            calls = df_calc[df_calc['option_type'] == 'CE']
            puts = df_calc[df_calc['option_type'] == 'PE']

            call_vex = calls['volatility_exposure'].sum()
            put_vex = puts['volatility_exposure'].sum()
            total_vex = call_vex + put_vex

            # Relative VEX analysis
            vex_ratio = call_vex / max(put_vex, 1) if put_vex > 0 else 0
            vex_skew = (call_vex - put_vex) / max(total_vex, 1) if total_vex > 0 else 0

            return {
                'total_vex': round(total_vex, 2),
                'call_vex': round(call_vex, 2),
                'put_vex': round(put_vex, 2),
                'vex_ratio': round(vex_ratio, 3),
                'vex_skew': round(vex_skew, 3),
                'enhanced_dataframe': df_calc  # Pass the dataframe with VEX column
            }

        except Exception as e:
            logger.error(f"Error in VEX calculation: {e}")
            return {}

    def calculate_volatility_metrics(self, df):
        """Calculate volatility metrics."""
        if df.empty:
            return {}

        try:
            df_valid_iv = df[df['iv'] > 0].copy()

            if df_valid_iv.empty:
                logger.warning("No valid IV data found")
                return {}

            iv_series = df_valid_iv['iv']
            avg_iv = iv_series.mean()
            iv_range = iv_series.max() - iv_series.min()

            underlying_price = df['underlying_price'].iloc[0]
            if underlying_price > 0:
                df_valid_iv['strike_diff'] = abs(df_valid_iv['strike'] - underlying_price)
                atm_option = df_valid_iv.loc[df_valid_iv['strike_diff'].idxmin()]
                atm_iv = atm_option['iv']
            else:
                atm_iv = avg_iv

            calls_iv = df_valid_iv[df_valid_iv['option_type'] == 'CE']['iv']
            puts_iv = df_valid_iv[df_valid_iv['option_type'] == 'PE']['iv']

            call_avg_iv = calls_iv.mean() if not calls_iv.empty else 0
            put_avg_iv = puts_iv.mean() if not puts_iv.empty else 0
            iv_skew = put_avg_iv - call_avg_iv

            return {
                'avg_iv': round(avg_iv, 2),
                'atm_iv': round(atm_iv, 2),
                'call_avg_iv': round(call_avg_iv, 2),
                'put_avg_iv': round(put_avg_iv, 2),
                'iv_skew': round(iv_skew, 2),
                'iv_range': round(iv_range, 2)
            }

        except Exception as e:
            logger.error(f"Error calculating volatility metrics: {e}")
            return {}

    def prepare_display_dataframe(self, df):
        """Convert raw values to display-ready format for frontend consumption."""
        if df.empty:
            return df

        try:
            df_display = df.copy()

            # Convert all lot-based columns to display lots
            df_display['oi_display'] = df_display['oi'] / self.lot_size
            df_display['volume_display'] = df_display['volume'] / self.lot_size
            df_display['oi_change_display'] = df_display['oi_change'] / self.lot_size

            # VEX: Already converted to lots by backend, rename for clarity
            df_display['vex_display'] = df_display['volatility_exposure']

            # Keep raw values for percentage calculations (with _raw suffix)
            df_display['oi_raw'] = df_display['oi']
            df_display['volume_raw'] = df_display['volume']
            df_display['oi_change_raw'] = df_display['oi_change']
            df_display['vex_raw'] = df_display['volatility_exposure'] * self.lot_size  # Convert back to raw

            # Straddle OI display calculation (strike-level)
            strikes = df_display['strike'].unique()
            for strike in strikes:
                call_oi = df_display[(df_display['strike'] == strike) & (df_display['option_type'] == 'CE')]['oi']
                put_oi = df_display[(df_display['strike'] == strike) & (df_display['option_type'] == 'PE')]['oi']

                call_oi_val = call_oi.iloc[0] if not call_oi.empty else 0
                put_oi_val = put_oi.iloc[0] if not put_oi.empty else 0
                straddle_oi_display = (call_oi_val + put_oi_val) / self.lot_size

                # Set straddle values for both CE and PE at this strike
                df_display.loc[df_display['strike'] == strike, 'straddle_oi_display'] = straddle_oi_display

            logger.info(f"Prepared display dataframe with lot_size={self.lot_size}")
            return df_display

        except Exception as e:
            logger.error(f"Error preparing display dataframe: {e}")
            return df

    def calculate_support_resistance(self, df, top_n=3):
        """Calculate support/resistance levels based on OI."""
        if df.empty:
            return {}

        try:
            calls = df[df['option_type'] == 'CE']
            puts = df[df['option_type'] == 'PE']

            result = {}

            if not calls.empty:
                calls_oi = calls.nlargest(top_n, 'oi')
                result.update({
                    'resistance_levels': calls_oi['strike'].tolist(),
                    'resistance_oi': calls_oi['oi'].tolist()
                })

            if not puts.empty:
                puts_oi = puts.nlargest(top_n, 'oi')
                result.update({
                    'support_levels': puts_oi['strike'].tolist(),
                    'support_oi': puts_oi['oi'].tolist()
                })

            return result

        except Exception as e:
            logger.error(f"Error calculating support/resistance: {e}")
            return {}

    def calculate_time_to_expiry(self, expiry_date, market='NSE'):
        """Years (of 365 days) from now, in India time, to the market's close on the expiry date."""
        try:
            if isinstance(expiry_date, str):
                expiry_day = datetime.strptime(expiry_date, '%Y-%m-%d').date()
            elif isinstance(expiry_date, datetime):
                expiry_day = expiry_date.date()
            else:
                expiry_day = expiry_date

            hour, minute = market_close(market, expiry_day)
            expiry_moment = datetime(expiry_day.year, expiry_day.month, expiry_day.day,
                                     hour, minute, tzinfo=INDIA_TIME)
            seconds_left = (expiry_moment - datetime.now(INDIA_TIME)).total_seconds()
            return max(0.0, seconds_left / (365 * 24 * 3600))

        except Exception as e:
            logger.error(f"Error calculating time to expiry: {e}")
            return 0.0

    def black_scholes_price(self, S, K, T, r, sigma, option_type='call'):
        """Black-Scholes option pricing."""
        try:
            if T <= 0:
                if option_type.lower() == 'call':
                    return max(0, S - K)
                else:
                    return max(0, K - S)

            if sigma <= 0:
                discount_factor = math.exp(-r * T)
                if option_type.lower() == 'call':
                    return max(0, S - K * discount_factor)
                else:
                    return max(0, K * discount_factor - S)

            d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)

            if option_type.lower() == 'call':
                price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
            else:
                price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

            return max(0, price)

        except Exception as e:
            logger.error(f"Error calculating Black-Scholes price: {e}")
            return 0.0

    def black76_price(self, F, K, T, r, sigma, option_type='call'):
        """Black-76 price of an option on a futures price F (used for MCX, whose underlyings are futures)."""
        try:
            if T <= 0:
                if option_type.lower() == 'call':
                    return max(0, F - K)
                else:
                    return max(0, K - F)

            discount_factor = math.exp(-r * T)

            if sigma <= 0:
                if option_type.lower() == 'call':
                    return discount_factor * max(0, F - K)
                else:
                    return discount_factor * max(0, K - F)

            d1 = (math.log(F / K) + 0.5 * sigma**2 * T) / (sigma * math.sqrt(T))
            d2 = d1 - sigma * math.sqrt(T)

            if option_type.lower() == 'call':
                price = discount_factor * (F * norm.cdf(d1) - K * norm.cdf(d2))
            else:
                price = discount_factor * (K * norm.cdf(-d2) - F * norm.cdf(-d1))

            return max(0, price)

        except Exception as e:
            logger.error(f"Error calculating Black-76 price: {e}")
            return 0.0

    def calculate_black_scholes_prices(self, df, expiry_date, volatility=0.20, risk_free_rate=0.07, market='NSE'):
        """Theoretical prices for the options dataframe: Black-Scholes for NSE, Black-76 for MCX futures."""
        if df.empty:
            return df

        try:
            df_result = df.copy()

            time_to_expiry = self.calculate_time_to_expiry(expiry_date, market)
            underlying_price = df_result['underlying_price'].iloc[0] if 'underlying_price' in df_result.columns else 0

            if underlying_price <= 0:
                df_result['bs_price'] = 0.0
                return df_result

            price_model = self.black76_price if market == 'MCX' else self.black_scholes_price

            def calc_bs_price(row):
                strike = row['strike']
                option_type = 'call' if row['option_type'] == 'CE' else 'put'

                return price_model(
                    underlying_price, strike, time_to_expiry,
                    risk_free_rate, volatility, option_type
                )

            df_result['bs_price'] = df_result.apply(calc_bs_price, axis=1)

            logger.info(f"Calculated theoretical prices ({market}) with T={time_to_expiry:.6f}")
            return df_result

        except Exception as e:
            logger.error(f"Error calculating Black-Scholes prices: {e}")
            df['bs_price'] = 0.0
            return df

    def generate_comprehensive_report(self, df, expiry_date=None, bs_config=None):
        """
        Generate the options analytics report.

        Args:
            df: DataFrame with option chain data
            expiry_date: Expiry date for Black-Scholes calculations
            bs_config: Black-Scholes configuration dict

        Returns:
            Analytics report dict
        """
        if df.empty:
            return {'error': 'No data available'}

        try:
            max_pain = self.calculate_max_pain(df)
            df_enhanced = df

            if bs_config and expiry_date:
                df_enhanced = self.calculate_black_scholes_prices(
                    df_enhanced,
                    expiry_date=expiry_date,
                    volatility=bs_config.get('volatility', 0.20),
                    risk_free_rate=bs_config.get('risk_free_rate', 0.07),
                    market=bs_config.get('market', 'NSE')
                )

            support_resistance = self.calculate_support_resistance(df_enhanced)
            volatility_metrics = self.calculate_volatility_metrics(df_enhanced)
            gex_analysis = self.estimate_gamma_exposure(df_enhanced)
            vex_analysis = self.estimate_volatility_exposure(df_enhanced)

            # Use the dataframe with VEX from vex_analysis for consistency
            if vex_analysis and 'enhanced_dataframe' in vex_analysis:
                enhanced_dataframe = vex_analysis['enhanced_dataframe']
            else:
                enhanced_dataframe = df_enhanced

            # FINAL STEP: Prepare display-ready dataframe
            final_dataframe = self.prepare_display_dataframe(enhanced_dataframe)

            report = {
                'max_pain_strike': max_pain,
                'support_resistance': support_resistance,
                'volatility_metrics': volatility_metrics,
                'gex_analysis': gex_analysis,
                'vex_analysis': vex_analysis,
                'enhanced_dataframe': final_dataframe
            }

            return report

        except Exception as e:
            logger.error(f"Error generating comprehensive report: {e}")
            return {'error': str(e)}

    # UNIFIED WORKFLOW METHODS

    def get_option_chain_with_analytics(self, expiry: str = None, underlying_scrip: int = 13,
                                      underlying_seg: str = "IDX_I", include_bs=False,
                                      bs_config=None, strike_range=None) -> Dict:
        """
        Unified method to fetch option chain data and generate analytics in one call.

        Args:
            expiry: Expiry date in YYYY-MM-DD format
            underlying_scrip: Asset ID (default: 13 for Nifty)
            underlying_seg: Segment (default: "IDX_I" for Index)
            include_bs: Whether to include Black-Scholes pricing
            bs_config: Black-Scholes configuration dict
            strike_range: Number of strikes around ATM to include (None = all)

        Returns:
            Dictionary with option chain data and comprehensive analytics
        """
        try:
            # Fetch option chain data
            option_chain_data = self.fetch_option_chain(expiry, underlying_scrip, underlying_seg)
            if not option_chain_data:
                return {'error': 'Failed to fetch option chain data'}

            # Parse data
            df = self.parse_option_chain(option_chain_data, underlying_scrip, underlying_seg)
            if df.empty:
                return {'error': 'Failed to parse option chain data'}

            # Apply strike range filtering BEFORE analytics
            if strike_range and strike_range != 'All':
                df = self._apply_strike_filter(df, strike_range)
                if df.empty:
                    return {'error': 'No data after strike filtering'}

            # Generate comprehensive analytics on filtered data
            if include_bs and bs_config:
                report = self.generate_comprehensive_report(df, expiry, bs_config)
            else:
                report = self.generate_comprehensive_report(df, expiry)

            return report

        except Exception as e:
            logger.error(f"Error in unified workflow: {e}")
            return {'error': str(e)}

    def _apply_strike_filter(self, df: pd.DataFrame, strike_range: int) -> pd.DataFrame:
        """Apply strike range filtering to dataframe."""
        try:
            underlying_price = df['underlying_price'].iloc[0] if 'underlying_price' in df.columns else 0
            if underlying_price <= 0:
                return df

            # Calculate strike_size dynamically from the first two strikes
            strikes = sorted(df['strike'].unique())
            if len(strikes) < 2:
                strike_size = 50  # Default fallback
            else:
                strike_size = strikes[1] - strikes[0]

            # Calculate ATM strike using dynamic strike interval
            atm_strike = round(underlying_price / strike_size) * strike_size

            # Get strikes within range
            strikes = sorted(df['strike'].unique())
            atm_index = min(range(len(strikes)), key=lambda i: abs(strikes[i] - atm_strike))

            # Calculate range
            start_idx = max(0, atm_index - strike_range)
            end_idx = min(len(strikes), atm_index + strike_range + 1)

            selected_strikes = strikes[start_idx:end_idx]
            filtered_df = df[df['strike'].isin(selected_strikes)]

            logger.info(f"Filtered to {len(selected_strikes)} strikes around ATM {atm_strike}")
            return filtered_df

        except Exception as e:
            logger.error(f"Error applying strike filter: {e}")
            return df
