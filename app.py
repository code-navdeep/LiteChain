"""
LiteChain - Advanced Options Analytics Platform
Simplified Dhan-Only Application
"""

import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime
import time
import os
import logging
from typing import Dict, List, Optional, Any, Tuple

# Import integrated Dhan analytics engine
from integrated import DhanOptionsAnalytics

# Import visualization only
from visualization import OptionsVisualization, format_gex_millions

# Import credential management
from credentials import check_credentials_or_setup, render_credential_setup, CredentialManager

# Minimal logging - only critical errors
logging.basicConfig(level=logging.CRITICAL)
logger = logging.getLogger(__name__)

# ============================================================================
# CSV DATA LOADING FUNCTIONS
# ============================================================================

@st.cache_data
def load_trading_assets():
    """Load trading assets data from CSV and cache it."""
    try:
        df = pd.read_csv('assets.csv')
        return df
    except Exception as e:
        st.error("Failed to load assets.csv file")
        return pd.DataFrame()

def get_segments_from_csv(df):
    """Get unique segments from merged data."""
    if df.empty:
        return []
    
    # Create segment display name mapping
    segment_display_map = {
        1: 'Index',
        2: 'Equity', 
        3: 'Commodity'
    }
    
    unique_segments = df['segment_id'].unique()
    segments = []
    for seg_id in sorted(unique_segments):
        display_name = segment_display_map.get(seg_id, f'Segment {seg_id}')
        segments.append({'id': seg_id, 'display_name': display_name})
    
    return segments

def get_assets_for_segment_from_csv(df, segment_id):
    """Get assets for specific segment."""
    if df.empty:
        return []
    assets = df[df['segment_id'] == segment_id][['asset_id', 'display_name', 'lot_size']].sort_values('display_name')
    return [{'id': row['asset_id'], 'display_name': row['display_name'], 'lot_size': row['lot_size']} for _, row in assets.iterrows()]

def get_lot_size_from_csv(df, asset_id, segment_id):
    """Get lot size for asset. Asset IDs repeat across segments (13 is both NIFTY and ABB), so match both."""
    if df.empty:
        return 75
    result = df[(df['asset_id'] == asset_id) & (df['segment_id'] == segment_id)]['lot_size']
    return int(result.iloc[0]) if not result.empty else 75

# Page configuration
st.set_page_config(
    page_title="LiteChain - Options Analytics",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================================
# SESSION STATE INITIALIZATION
# ============================================================================

def initialize_session_state():
    """Initialize all session state variables for Dhan-only application."""
    defaults = {
        # Data storage
        'analytics_report': None,  # Current analytics report
        
        # Dhan client
        'dhan_client': None,
        'visualization_engine': None,
        
        # Credentials
        'dhan_client_id': '',
        'dhan_access_token': '',
        
        # Asset Selection Settings
        'available_segments': [],
        'selected_segment': 'Select...',
        'selected_segment_id': None,
        'available_assets': [],
        'selected_asset': 'Select...',
        'selected_asset_id': None,
        'available_expiries': [],
        'selected_expiry': 'Select...',
        
        # Strike range setting
        'strike_range': 16,
        
        # View mode setting
        'selected_view_mode': 'Select...',
        
        # Auto-refresh settings
        'selected_refresh_interval': 'Select...',
        'refresh_interval_seconds': None,
        'last_refresh_time': 0,
        'refresh_in_progress': False,
        
        # Black-Scholes Parameters
        'bs_volatility': 0.10,
        'bs_risk_free_rate': 0.07
    }
    
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value
    
    # Initialize visualization engine only
    if st.session_state.visualization_engine is None:
        st.session_state.visualization_engine = OptionsVisualization()

# ============================================================================
# UNIFIED DATA MANAGEMENT
# ============================================================================

def get_analytics_report():
    """Get the complete analytics report."""
    return st.session_state.get('analytics_report', {})

def is_data_available():
    """Check if valid data is available."""
    report = get_analytics_report()
    return bool(report and 'enhanced_dataframe' in report and not report['enhanced_dataframe'].empty)

# ============================================================================
# CONSOLIDATED UI COMPONENTS (formerly components.py)
# ============================================================================

def show_no_data_warning(source_name: str, instructions: str) -> None:
    """Show warning when no data is available."""
    st.warning(f"📊 No {source_name} Data Available")
    st.info(instructions)


# ============================================================================
# CONSOLIDATED OPTION CHAIN TABLE BUILDER (formerly option_chain.py)
# ============================================================================


def calculate_strike_level_metrics(df: pd.DataFrame, analytics_report: Dict = None) -> Dict[float, Dict[str, float]]:
    """Calculate strike-level metrics for left-only and right-only columns."""
    if df.empty:
        return {}
    
    strike_metrics = {}
    strikes = df['strike'].unique()
    
    for strike in strikes:
        call_data = df[(df['strike'] == strike) & (df['option_type'] == 'CE')]
        put_data = df[(df['strike'] == strike) & (df['option_type'] == 'PE')]
        
        # Use raw values for PCR calculations (ratios)
        call_oi_raw = call_data['oi_raw'].iloc[0] if not call_data.empty and 'oi_raw' in call_data.columns else 0
        put_oi_raw = put_data['oi_raw'].iloc[0] if not put_data.empty and 'oi_raw' in put_data.columns else 0
        call_volume_raw = call_data['volume_raw'].iloc[0] if not call_data.empty and 'volume_raw' in call_data.columns else 0
        put_volume_raw = put_data['volume_raw'].iloc[0] if not put_data.empty and 'volume_raw' in put_data.columns else 0
        
        # Get GEX from analytics report - use display values
        strike_gex_display = 0
        if analytics_report:
            gex_by_strike = analytics_report.get('gex_analysis', {}).get('gex_by_strike', {})
            strike_gex_display = gex_by_strike.get(strike, 0)  # Already in millions from backend
        
        
        # Get straddle OI display value
        straddle_oi_display = call_data['straddle_oi_display'].iloc[0] if not call_data.empty and 'straddle_oi_display' in call_data.columns else 0
        
        # Put/call ratios at this strike; no ratio ('-') when the call side is zero
        pcr_oi = f'{put_oi_raw / call_oi_raw:.2f}' if call_oi_raw > 0 else '-'
        pcr_volume = f'{put_volume_raw / call_volume_raw:.2f}' if call_volume_raw > 0 else '-'

        # Calculate metrics using display values
        strike_metrics[strike] = {
            'pcr_combined': '-' if pcr_oi == '-' and pcr_volume == '-' else f'{pcr_oi}<br>({pcr_volume})',
            'straddle_oi_display': straddle_oi_display,
            'gex_display': strike_gex_display
        }
    
    return strike_metrics

def _no_negative_zero(text: str) -> str:
    """A figure that rounds to zero is shown without a minus sign: '-0.000' -> '0.000'."""
    return text[1:] if text.startswith('-') and float(text) == 0 else text

def format_strike(strike: float) -> str:
    """Strike with up to two decimals, trailing zeros dropped: 26000 -> '26000', 7.5 -> '7.5'."""
    return f'{float(strike):.2f}'.rstrip('0').rstrip('.')

def format_indian_number(num: float) -> str:
    """Format number in Indian comma system (12,34,567)"""
    if pd.isna(num) or num == 0:
        return "0"
    
    num = int(num)
    if num < 0:
        return "-" + format_indian_number(abs(num))
    
    s = str(num)
    if len(s) <= 3:
        return s
    
    # Indian format: last 3 digits, then groups of 2
    last_three = s[-3:]
    remaining = s[:-3]
    
    # Group remaining digits in pairs from right
    groups = []
    while remaining:
        if len(remaining) >= 2:
            groups.append(remaining[-2:])
            remaining = remaining[:-2]
        else:
            groups.append(remaining)
            remaining = ""
    
    groups.reverse()
    return ",".join(groups) + "," + last_three


def calculate_max_values_for_percentages(df: pd.DataFrame, strike_metrics: Dict = None) -> Dict[str, float]:
    """Calculate maximum values for percentage calculations with separate call/put max values and top rankings."""
    max_values = {}
    
    # Separate call and put dataframes
    calls_df = df[df['option_type'] == 'CE']
    puts_df = df[df['option_type'] == 'PE']
    
    # Calculate separate max values for calls and puts using RAW values for percentages
    if 'oi_raw' in df.columns:
        max_values['oi_call'] = calls_df['oi_raw'].max() if not calls_df.empty else 0
        max_values['oi_put'] = puts_df['oi_raw'].max() if not puts_df.empty else 0
        
        # Calculate top 3 OI values for ranking using DISPLAY values
        max_values['oi_call_top3'] = calls_df['oi_display'].nlargest(3).tolist() if not calls_df.empty else []
        max_values['oi_put_top3'] = puts_df['oi_display'].nlargest(3).tolist() if not puts_df.empty else []
    
    if 'volume_raw' in df.columns:
        max_values['volume_call'] = calls_df['volume_raw'].max() if not calls_df.empty else 0
        max_values['volume_put'] = puts_df['volume_raw'].max() if not puts_df.empty else 0
        
        # Calculate top 3 Volume values for ranking using DISPLAY values
        max_values['volume_call_top3'] = calls_df['volume_display'].nlargest(3).tolist() if not calls_df.empty else []
        max_values['volume_put_top3'] = puts_df['volume_display'].nlargest(3).tolist() if not puts_df.empty else []
    
    if 'vex_raw' in df.columns:
        max_values['volatility_exposure_call'] = calls_df['vex_raw'].max() if not calls_df.empty else 0
        max_values['volatility_exposure_put'] = puts_df['vex_raw'].max() if not puts_df.empty else 0
        
        # Calculate top 3 VEX values for ranking using DISPLAY values
        max_values['volatility_exposure_call_top3'] = calls_df['vex_display'].nlargest(3).tolist() if not calls_df.empty else []
        max_values['volatility_exposure_put_top3'] = puts_df['vex_display'].nlargest(3).tolist() if not puts_df.empty else []
    
    if 'oi_change_raw' in df.columns:
        max_values['oi_change_call'] = calls_df['oi_change_raw'].abs().max() if not calls_df.empty else 0
        max_values['oi_change_put'] = puts_df['oi_change_raw'].abs().max() if not puts_df.empty else 0
        
        # Calculate top 2 positive and bottom 2 negative OI changes for ranking using DISPLAY values
        if not calls_df.empty:
            call_positive = calls_df[calls_df['oi_change_display'] > 0]['oi_change_display'].nlargest(2).tolist()
            call_negative = calls_df[calls_df['oi_change_display'] < 0]['oi_change_display'].nsmallest(2).tolist()
            max_values['oi_change_call_top2_positive'] = call_positive
            max_values['oi_change_call_bottom2_negative'] = call_negative
        
        if not puts_df.empty:
            put_positive = puts_df[puts_df['oi_change_display'] > 0]['oi_change_display'].nlargest(2).tolist()
            put_negative = puts_df[puts_df['oi_change_display'] < 0]['oi_change_display'].nsmallest(2).tolist()
            max_values['oi_change_put_top2_positive'] = put_positive
            max_values['oi_change_put_bottom2_negative'] = put_negative
    
    # Calculate max values from strike_metrics for GEX and Strd OI using display values
    if strike_metrics:
        gex_values = [metrics.get('gex_display', 0) for metrics in strike_metrics.values()]
        if gex_values:
            # Largest strike in either direction: the base for the GEX shares
            max_values['gamma_exposure'] = max(abs(gex) for gex in gex_values)
            
            # Find GEX extremes for highlighting
            positive_gex_values = [gex for gex in gex_values if gex > 0]
            negative_gex_values = [gex for gex in gex_values if gex < 0]
            
            if positive_gex_values:
                max_values['gamma_exposure_highest_positive'] = max(positive_gex_values)
            if negative_gex_values:
                max_values['gamma_exposure_lowest_negative'] = min(negative_gex_values)
        
        strd_oi_values = [metrics.get('straddle_oi_display', 0) for metrics in strike_metrics.values()]
        if strd_oi_values:
            max_values['straddle_oi'] = max(strd_oi_values)
            
            # Calculate top 3 Straddle OI values for ranking
            max_values['straddle_oi_top3'] = sorted(strd_oi_values, reverse=True)[:3]
    
    return max_values

def get_value_rank_class(value: float, column_id: str, max_values: Dict, is_call: bool) -> str:
    """Determine CSS class based on value ranking (top 3 for OI/Volume, extreme values for OI Change)."""
    if column_id in ['oi_display', 'volume_display'] and max_values:
        # Map display columns to their ranking keys
        base_column = column_id.replace('_display', '')
        top3_key = f"{base_column}_{'call' if is_call else 'put'}_top3"
        if top3_key not in max_values:
            return ""
        
        top3_values = max_values[top3_key]
        if len(top3_values) == 0:
            return ""
        
        # Check ranking
        if len(top3_values) >= 1 and value == top3_values[0]:
            return "rank-1"
        elif len(top3_values) >= 2 and value == top3_values[1]:
            return "rank-2"  
        elif len(top3_values) >= 3 and value == top3_values[2]:
                return "rank-3"
    
    elif column_id == 'vex_display' and max_values:
        # Map vex_display back to volatility_exposure for ranking key
        top3_key = f"volatility_exposure_{'call' if is_call else 'put'}_top3"
        if top3_key not in max_values:
            return ""
        
        top3_values = max_values[top3_key]
        if len(top3_values) == 0:
            return ""
        
        # Check ranking
        if len(top3_values) >= 1 and value == top3_values[0]:
            return "rank-1"
        elif len(top3_values) >= 2 and value == top3_values[1]:
            return "rank-2"  
        elif len(top3_values) >= 3 and value == top3_values[2]:
            return "rank-3"
    
    elif column_id == 'oi_change_display' and max_values:
        side = 'call' if is_call else 'put'
        
        # Check positive extremes
        top2_positive_key = f"oi_change_{side}_top2_positive"
        if top2_positive_key in max_values:
            positive_values = max_values[top2_positive_key]
            if len(positive_values) >= 1 and value == positive_values[0]:
                return "oi-change-highest-positive"
            elif len(positive_values) >= 2 and value == positive_values[1]:
                return "oi-change-second-highest-positive"
        
        # Check negative extremes
        bottom2_negative_key = f"oi_change_{side}_bottom2_negative"
        if bottom2_negative_key in max_values:
            negative_values = max_values[bottom2_negative_key]
            if len(negative_values) >= 1 and value == negative_values[0]:
                return "oi-change-lowest-negative"
            elif len(negative_values) >= 2 and value == negative_values[1]:
                return "oi-change-second-lowest-negative"
    
    elif column_id == 'gex_display' and max_values:
        # Check GEX extremes
        if 'gamma_exposure_highest_positive' in max_values and value == max_values['gamma_exposure_highest_positive']:
            return "gex-highest-positive"
        elif 'gamma_exposure_lowest_negative' in max_values and value == max_values['gamma_exposure_lowest_negative']:
            return "gex-lowest-negative"
    
    elif column_id == 'straddle_oi_display' and max_values:
        # Check straddle OI ranking (top 3)
        if 'straddle_oi_top3' in max_values:
            top3_values = max_values['straddle_oi_top3']
            if len(top3_values) >= 1 and value == top3_values[0]:
                return "rank-1"
            elif len(top3_values) >= 2 and value == top3_values[1]:
                return "rank-2"
            elif len(top3_values) >= 3 and value == top3_values[2]:
                return "rank-3"
    
    return ""

def format_numeric_value(value: float, column_id: str, max_values: Dict[str, float] = None,
                        is_call: bool = True, lot_size: int = 75) -> str:
    """Format numeric values - display-ready values only, no conversions."""
    if pd.isna(value):
        return '-'
    
    # Handle numpy types and regular Python types
    if isinstance(value, (int, float, np.integer, np.floating)):
        base_formatted = ""
        percentage_text = ""
        
        if column_id in ['oi_display', 'volume_display']:
            # Value already converted to lots by backend
            base_formatted = format_indian_number(int(value))
            # Add percentage using RAW values for calculation
            base_column = column_id.replace('_display', '')
            max_key = f"{base_column}_{'call' if is_call else 'put'}"
            if max_values and max_key in max_values and max_values[max_key] > 0:
                # Convert display value back to raw for percentage calculation
                raw_value = value * lot_size
                percentage = (raw_value / max_values[max_key]) * 100
                percentage_text = f'<br>({percentage:.0f}%)'
        elif column_id == 'oi_change_display':
            # Value already converted to lots by backend, preserve sign. The sign is taken from
            # the whole number of lots shown, so a fall of under one lot reads +0, never -0.
            whole_lots = int(value)
            if whole_lots >= 0:
                formatted_val = format_indian_number(whole_lots)
                base_formatted = f'<span style="color:#059669">+{formatted_val}</span>'
            else:
                formatted_val = format_indian_number(abs(whole_lots))
                base_formatted = f'<span style="color:#dc2626">-{formatted_val}</span>'
            # Add percentage for OI Change using RAW values (not lot-converted)
            max_key = f"oi_change_{'call' if is_call else 'put'}"
            if max_values and max_key in max_values and max_values[max_key] > 0:
                # Convert display value back to raw for percentage calculation; whole percent
                # first, so a fall under half a percent reads +0%, never -0%
                raw_value = value * lot_size
                percentage = round((raw_value / max_values[max_key]) * 100)
                if percentage >= 0:
                    percentage_text = f'<br><span style="color:#059669">(+{percentage:.0f}%)</span>'
                else:
                    percentage_text = f'<br><span style="color:#dc2626">({percentage:.0f}%)</span>'
        elif column_id == 'last_price':
            base_formatted = f'{value:.2f}' if value > 0 else '-'
        elif column_id == 'bs_price':
            base_formatted = f'{value:.2f}' if value > 0 else '-'
        elif column_id == 'gex_display':
            # GEX is in millions (see estimate_gamma_exposure in integrated.py)
            base_formatted = format_gex_millions(value) if abs(value) > 0 else '-'
            # Share of the largest strike in either direction (so within -100%..100%);
            # round() gives a whole number, so a tiny negative share shows as 0%, not -0%;
            # no share under a "-" (no GEX)
            if abs(value) > 0 and max_values and 'gamma_exposure' in max_values and max_values['gamma_exposure'] > 0:
                percentage = round((value / max_values['gamma_exposure']) * 100)
                percentage_text = f'<br>({percentage}%)'
        elif column_id == 'vex_display':
            base_formatted = f'{(value/1000):.1f}K' if abs(value) > 0 else '-'
            # Add percentage for VEX using RAW values (none under a "-": no VEX, no share)
            max_key = f"volatility_exposure_{'call' if is_call else 'put'}"
            if abs(value) > 0 and max_values and max_key in max_values and max_values[max_key] > 0:
                # Convert display value back to raw for percentage calculation
                raw_value = value * lot_size
                percentage = (raw_value / max_values[max_key]) * 100
                percentage_text = f'<br>({percentage:.0f}%)'
        elif column_id == 'straddle_oi_display':
            # Value already converted to lots by backend
            base_formatted = format_indian_number(int(value)) if value > 0 else '-'
            # Add percentage for Straddle OI (none under a "-": no open interest, no share)
            if value > 0 and max_values and 'straddle_oi' in max_values and max_values['straddle_oi'] > 0:
                percentage = (value / max_values['straddle_oi']) * 100
                percentage_text = f'<br>({percentage:.0f}%)'
        elif column_id == 'iv':
            base_formatted = f'{value:.2f}'
        else:
            base_formatted = f'{value:.2f}'
        
        return base_formatted + percentage_text
    
    return str(value)

def load_css_styles() -> str:
    """Load CSS from external file in root directory."""
    css_path = os.path.join(os.path.dirname(__file__), "styles.css")
    try:
        with open(css_path, 'r') as f:
            css_content = f.read()
            # Add padding reduction for data cells
            padding_override = """
            /* Reduce padding for data cells by ~20% */
            .option-table td:not(.underlying-row-data):not(.totals-row td):not(.strike-column) {
                padding: 6px 8px !important;
            }
            .option-table .call-column,
            .option-table .put-column,
            .option-table .left-only-column,
            .option-table .right-only-column {
                padding: 6px 8px !important;
            }
            /* Keep original padding for headers, underlying row, and totals */
            .option-table th,
            .option-table .underlying-row-data,
            .option-table .totals-row td {
                /* Original padding preserved */
            }
            """
            return f"<style>\n{css_content}\n{padding_override}\n</style>"
    except FileNotFoundError:
        st.warning("CSS file not found. Using minimal inline styles with reduced padding.")
        return """<style>
        .option-table { border-collapse: collapse; width: 100%; }
        .option-table td:not(.underlying-row-data):not(.totals-row td) {
            padding: 6px 8px !important;
        }
        </style>"""

def build_unified_markets_table(df: pd.DataFrame, underlying_price: float = 0, 
                               max_pain_strike: float = 0, analytics_report: Dict = None, lot_size: int = 75) -> str:
    """Build unified HTML table with hardcoded column layout."""
    if df.empty:
        return "<p>No data available for option chain table</p>"
    
    # Prepare data
    calls_df = df[df['option_type'] == 'CE'].sort_values('strike')
    puts_df = df[df['option_type'] == 'PE'].sort_values('strike')
    strikes = sorted(df['strike'].unique())
    
    # Calculate strike-level metrics first
    strike_metrics = calculate_strike_level_metrics(df, analytics_report)
    
    # Calculate maximum values for percentage calculations (including strike metrics)
    max_values = calculate_max_values_for_percentages(df, strike_metrics)
    
    # HARDCODED COLUMN LAYOUT
    # Symmetric: LTP, Volume, OI, OI Change, IV, BS Price, VEX
    symmetric_display_columns = ['last_price', 'volume_display', 'oi_display', 'oi_change_display', 'iv', 'bs_price', 'vex_display']
    
    # Left-Only: GEX, PCR Combined
    left_only_columns = ['gex_display', 'pcr_combined']
    
    # Right-Only: Strd OI
    right_only_columns = ['straddle_oi_display']
    
    # Filter columns that exist in dataframe
    symmetric_display_columns = [col for col in symmetric_display_columns if col in df.columns]
    
    # Calculate totals using display values - NO CONVERSION NEEDED
    calls_totals = {
        'oi_display': int(calls_df['oi_display'].sum()) if 'oi_display' in calls_df.columns and not calls_df.empty else 0,
        'oi_change_display': int(calls_df['oi_change_display'].sum()) if 'oi_change_display' in calls_df.columns and not calls_df.empty else 0,
        'volume_display': int(calls_df['volume_display'].sum()) if 'volume_display' in calls_df.columns and not calls_df.empty else 0
    }
    
    puts_totals = {
        'oi_display': int(puts_df['oi_display'].sum()) if 'oi_display' in puts_df.columns and not puts_df.empty else 0,
        'oi_change_display': int(puts_df['oi_change_display'].sum()) if 'oi_change_display' in puts_df.columns and not puts_df.empty else 0,
        'volume_display': int(puts_df['volume_display'].sum()) if 'volume_display' in puts_df.columns and not puts_df.empty else 0
    }
    
    # Prepare strikes with underlying price insertion
    enhanced_strikes = prepare_enhanced_strikes(strikes, underlying_price)
    
    # Start building HTML
    css = load_css_styles()
    
    html = css + f'<div class="option-table-container">'
    html += '<table class="option-table"><thead><tr>'
    
    # Build header
    html += build_table_header(left_only_columns, symmetric_display_columns, 
                              right_only_columns)
    html += '</tr></thead><tbody>'
    
    # Build data rows
    html += build_table_data_rows(enhanced_strikes, calls_df, puts_df, 
                                 left_only_columns, symmetric_display_columns, 
                                 right_only_columns, 
                                 strike_metrics, max_pain_strike, max_values, lot_size)
    
    # Build totals row
    html += build_table_totals_row(left_only_columns, symmetric_display_columns,
                                  right_only_columns, calls_totals, puts_totals,
                                  strike_metrics, lot_size)
    
    html += '</tbody></table></div>'
    
    return html

def prepare_enhanced_strikes(strikes: List[float], underlying_price: float) -> List[Tuple[str, float]]:
    """Prepare strikes list with underlying price insertion."""
    enhanced_strikes = []
    underlying_inserted = False
    
    for i, strike in enumerate(strikes):
        # Insert underlying price row if it falls between strikes, or directly above a
        # strike it equals exactly
        if not underlying_inserted and underlying_price > 0:
            if i == 0 and underlying_price <= strike:
                enhanced_strikes.append(('underlying', underlying_price))
                underlying_inserted = True
            elif i > 0 and strikes[i-1] < underlying_price <= strike:
                enhanced_strikes.append(('underlying', underlying_price))
                underlying_inserted = True
        
        enhanced_strikes.append(('strike', strike))
    
    # Insert at end if not inserted and underlying is above all strikes
    if not underlying_inserted and underlying_price > 0 and strikes and underlying_price > strikes[-1]:
        enhanced_strikes.append(('underlying', underlying_price))
    
    return enhanced_strikes

def build_table_header(left_only_columns: List[str], symmetric_display_columns: List[str], 
                      right_only_columns: List[str]) -> str:
    """Build header row with hardcoded column labels."""
    # Hardcoded column labels
    column_labels = {
        'last_price': 'LTP',
        'bs_price': 'BS Price', 
        'volume_display': 'Volume',
        'oi_display': 'OI',
        'oi_change_display': 'OI Chg',
        'iv': 'IV',
        'vex_display': 'VEX',
        'gex_display': 'GEX (OI)',
        'pcr_combined': 'PCR (OI/Vol)',
        'straddle_oi_display': 'Strd OI'
    }
    
    html = ""
    
    # Left-only headers
    for col_id in left_only_columns:
        label = column_labels.get(col_id, col_id.upper())
        html += f'<th class="left-only-header">{label}</th>'
    
    # Call headers (symmetric, reversed for symmetry)
    for col_id in reversed(symmetric_display_columns):
        label = column_labels.get(col_id, col_id.upper())
        html += f'<th class="call-column">{label}</th>'
    
    # Strike header
    html += '<th class="strike-column">STRIKE</th>'
    
    # Put headers (symmetric)
    for col_id in symmetric_display_columns:
        label = column_labels.get(col_id, col_id.upper())
        html += f'<th class="put-column">{label}</th>'
    
    # Right-only headers
    for col_id in right_only_columns:
        label = column_labels.get(col_id, col_id.upper())
        html += f'<th class="right-only-header">{label}</th>'
    
    return html

def build_table_data_rows(enhanced_strikes: List[Tuple[str, float]], 
                         calls_df: pd.DataFrame, puts_df: pd.DataFrame,
                         left_only_columns: List[str], symmetric_display_columns: List[str], 
                         right_only_columns: List[str], 
                         strike_metrics: Dict, max_pain_strike: float,
                         max_values: Dict[str, float], lot_size: int) -> str:
    """Build data rows for option chain table."""
    html = ""
    
    for row_type, strike_value in enhanced_strikes:
        if row_type == 'underlying':
            # Underlying price row
            html += '<tr class="underlying-row">'
            
            # Left-only columns (empty)
            for _ in left_only_columns:
                html += '<td class="underlying-row-data"></td>'
            
            # Call columns (empty)
            for _ in symmetric_display_columns:
                html += '<td class="underlying-row-data"></td>'
            
            # Strike column with underlying price
            html += f'<td class="strike-column">{strike_value:,.2f}</td>'
            
            # Put columns (empty)
            for _ in symmetric_display_columns:
                html += '<td class="underlying-row-data"></td>'
            
            # Right-only columns (empty)
            for _ in right_only_columns:
                html += '<td class="underlying-row-data"></td>'
            
            html += '</tr>'
            
        else:
            # Regular strike row
            strike = strike_value
            is_max_pain = (max_pain_strike > 0 and abs(float(strike) - float(max_pain_strike)) < 0.1)
            html += f'<tr>'
            
            # Left-only columns
            for col_id in left_only_columns:
                rank_class = ""
                if strike in strike_metrics:
                    value = strike_metrics[strike].get(col_id, 0)
                    rank_class = get_value_rank_class(value, col_id, max_values, is_call=True)
                
                css_classes = f"left-only-column {rank_class}".strip()
                html += f'<td class="{css_classes}">'
                
                if strike in strike_metrics:
                    value = strike_metrics[strike].get(col_id, 0)
                    if col_id == 'pcr_combined':
                        html += value
                    elif col_id == 'gex_display':
                        html += format_numeric_value(value, col_id, max_values)
                    else:
                        html += f'{value:.2f}' if value > 0 else '-'
                else:
                    html += '-'
                html += '</td>'
            
            # Call data (reversed)
            call_data = calls_df[calls_df['strike'] == strike]
            for col_id in reversed(symmetric_display_columns):
                rank_class = ""
                if not call_data.empty and col_id in call_data.columns:
                    value = call_data[col_id].iloc[0]
                    rank_class = get_value_rank_class(value, col_id, max_values, is_call=True)

                css_classes = f"call-column {rank_class}".strip()
                html += f'<td class="{css_classes}">'

                if not call_data.empty and col_id in call_data.columns:
                    html += format_numeric_value(value, col_id, max_values, is_call=True, lot_size=lot_size)
                else:
                    html += '-'
                html += '</td>'
            
            # Strike column
            if is_max_pain:
                html += f'<td class="strike-column max-pain-strike">{format_strike(strike)}</td>'
            else:
                html += f'<td class="strike-column">{format_strike(strike)}</td>'
            
            # Put data
            put_data = puts_df[puts_df['strike'] == strike]
            for col_id in symmetric_display_columns:
                rank_class = ""
                if not put_data.empty and col_id in put_data.columns:
                    value = put_data[col_id].iloc[0]
                    rank_class = get_value_rank_class(value, col_id, max_values, is_call=False)

                css_classes = f"put-column {rank_class}".strip()
                html += f'<td class="{css_classes}">'

                if not put_data.empty and col_id in put_data.columns:
                    html += format_numeric_value(value, col_id, max_values, is_call=False, lot_size=lot_size)
                else:
                    html += '-'
                html += '</td>'
            
            # Right-only columns
            for col_id in right_only_columns:
                rank_class = ""
                if strike in strike_metrics and col_id == 'straddle_oi_display':
                    value = strike_metrics[strike].get(col_id, 0)
                    rank_class = get_value_rank_class(value, col_id, max_values, is_call=True)
                
                css_classes = f"right-only-column {rank_class}".strip()
                html += f'<td class="{css_classes}">'
                
                if strike in strike_metrics:
                    value = strike_metrics[strike].get(col_id, 0)
                    if col_id == 'straddle_oi_display':
                        html += format_numeric_value(value, col_id, max_values, lot_size=lot_size)
                    else:
                        html += f'{value:.2f}' if value > 0 else '-'
                else:
                    html += '-'
                html += '</td>'
            
            html += '</tr>'
    
    return html

def build_table_totals_row(left_only_columns: List[str], symmetric_display_columns: List[str], 
                          right_only_columns: List[str], calls_totals: Dict, puts_totals: Dict, 
                          strike_metrics: Dict, lot_size: int) -> str:
    """Build totals row for option chain table. Totals carry no "share of the largest strike"
    percentage (max_values=None), which is meaningless for a total."""
    html = '<tr class="totals-row">'
    
    # Left-only totals
    for col_id in left_only_columns:
        html += '<td class="left-only-column">'
        if col_id == 'gex_display':
            # Calculate total GEX from strike_metrics
            total_gex = sum(metrics.get('gex_display', 0) for metrics in strike_metrics.values())
            html += format_numeric_value(total_gex, col_id, None)
        elif col_id == 'pcr_combined':
            # Put/call ratios of the totals; no ratio ('-') when the call total is zero
            pcr_oi_result = f'{puts_totals["oi_display"] / calls_totals["oi_display"]:.2f}' if calls_totals["oi_display"] > 0 else '-'
            pcr_volume_result = f'{puts_totals["volume_display"] / calls_totals["volume_display"]:.2f}' if calls_totals["volume_display"] > 0 else '-'
            html += '-' if pcr_oi_result == '-' and pcr_volume_result == '-' else f'{pcr_oi_result}<br>({pcr_volume_result})'
        else:
            html += '-'
        html += '</td>'
    
    # Call totals (reversed)
    for col_id in reversed(symmetric_display_columns):
        html += '<td class="call-column">'
        if col_id == 'oi_display':
            html += format_numeric_value(calls_totals["oi_display"], col_id, None, is_call=True, lot_size=lot_size)
        elif col_id == 'oi_change_display':
            html += format_numeric_value(calls_totals['oi_change_display'], col_id, None, is_call=True, lot_size=lot_size)
        elif col_id == 'volume_display':
            html += format_numeric_value(calls_totals["volume_display"], col_id, None, is_call=True, lot_size=lot_size)
        else:
            html += '-'
        html += '</td>'
    
    # Strike column - show PE(OI) - CE(OI) with calculated difference (already in lots)
    oi_difference = int(puts_totals["oi_display"] - calls_totals["oi_display"])
    html += f'<td class="strike-column">OI Diff<br>{format_indian_number(oi_difference)}</td>'
    
    # Put totals
    for col_id in symmetric_display_columns:
        html += '<td class="put-column">'
        if col_id == 'oi_display':
            html += format_numeric_value(puts_totals["oi_display"], col_id, None, is_call=False, lot_size=lot_size)
        elif col_id == 'oi_change_display':
            html += format_numeric_value(puts_totals['oi_change_display'], col_id, None, is_call=False, lot_size=lot_size)
        elif col_id == 'volume_display':
            html += format_numeric_value(puts_totals["volume_display"], col_id, None, is_call=False, lot_size=lot_size)
        else:
            html += '-'
        html += '</td>'
    
    # Right-only totals
    for col_id in right_only_columns:
        html += '<td class="right-only-column">'
        if col_id == 'straddle_oi_display':
            total_straddle_oi_display = sum(metrics.get('straddle_oi_display', 0) for metrics in strike_metrics.values())
            # Value already in lots, just format
            html += format_indian_number(int(total_straddle_oi_display)) if total_straddle_oi_display > 0 else '-'
        else:
            html += '-'
        html += '</td>'
    
    html += '</tr>'
    return html


# ============================================================================
# DATA PROVIDER FUNCTIONS
# ============================================================================

def get_current_lot_size() -> int:
    """Get lot size for currently selected asset."""
    try:
        asset_id = st.session_state.get('selected_asset_id')
        if asset_id:
            df = load_trading_assets()
            lot_size = get_lot_size_from_csv(df, asset_id, st.session_state.get('selected_segment_id'))
            return lot_size
        
        return 75
    except Exception as e:
        logger.error(f"Error getting lot size: {e}")
        return 75

def load_dhan_credentials() -> Dict[str, str]:
    """Load Dhan credentials: those typed in for this session, else .streamlit/secrets.toml."""
    credential_manager = CredentialManager()
    return credential_manager.get_credentials()

def initialize_dhan_client(client_id: str, access_token: str, lot_size: int = 75) -> Optional[DhanOptionsAnalytics]:
    """Initialize Dhan analytics client with credentials and lot size."""
    try:
        if not client_id or not access_token:
            return None
            
        client = DhanOptionsAnalytics(
            client_id=client_id, 
            access_token=access_token,
            lot_size=lot_size
        )
        st.session_state.dhan_client = client
        st.session_state.dhan_client_id = client_id
        st.session_state.dhan_access_token = access_token
        
        return client
    except Exception as e:
        st.error(f"Failed to initialize Dhan client: {e}")
        return None

def fetch_dhan_data() -> bool:
    """Fetch data from Dhan using integrated analytics engine with pre-filtering."""
    try:
        client = st.session_state.dhan_client
        
        if not client:
            st.error("Dhan client not initialized. Please check connection.")
            return False
        
        # Validate required selections
        if (st.session_state.selected_expiry == 'Select...' or 
            st.session_state.selected_asset_id is None or
            st.session_state.selected_segment_id is None):
            st.error("Please select segment, asset, and expiry before fetching data.")
            return False
        
        with st.spinner("Fetching data from Dhan..."):
            # Get segment mapping
            segment_map = {1: 'IDX_I', 2: 'NSE_EQ', 3: 'MCX_COMM'}
            segment_code = segment_map.get(st.session_state.selected_segment_id, 'IDX_I')
            
            # Auto-detect Black-Scholes configuration
            bs_config = get_auto_bs_config()
            
            # Use integrated analytics method with pre-filtering
            report = client.get_option_chain_with_analytics(
                expiry=st.session_state.selected_expiry,
                underlying_scrip=st.session_state.selected_asset_id,
                underlying_seg=segment_code,
                include_bs=True,
                bs_config=bs_config,
                strike_range=st.session_state.strike_range  # Pass strike range for pre-filtering
            )
            
            if report and 'error' not in report and 'enhanced_dataframe' in report:
                # Store complete analytics report (already filtered and analyzed)
                st.session_state.analytics_report = report
                
                df_count = len(report['enhanced_dataframe'])
                logger.info(f"Successfully processed {df_count} filtered records from Dhan")
                return True
            else:
                error_msg = report.get('error', 'Unknown error') if report else 'No data received'
                st.error(f"Failed to fetch data: {error_msg}")
                return False
                
    except Exception as e:
        logger.error(f"Error fetching data from Dhan: {e}")
        st.error(f"Failed to fetch data: {e}")
        return False

# ============================================================================
# SIDEBAR CONTROLS
# ============================================================================

def render_sidebar():
    """Render Dhan-only sidebar with progressive revelation."""
    # Markets Panel (Collapsible) - Asset selection only
    with st.sidebar.expander("Markets", expanded=True):
        render_dhan_dropdowns()
    
    # Settings Panel - Credentials management
    with st.sidebar.expander("⚙️ Settings", expanded=False):
        render_settings_panel()

def render_dhan_dropdowns():
    """Render Dhan-specific cascading dropdowns."""
    # Initialize Dhan client first
    initialize_dhan_if_needed()
    
    # Segment selection
    render_segment_dropdown()
    
    # Asset selection (only after segment)
    if st.session_state.selected_segment != 'Select...':
        render_asset_dropdown()
    
    # Expiry dropdown (only after asset selection)
    if should_show_expiry_dropdown():
        render_expiry_dropdown()
    
    # View mode, strike range, BS params, and fetch button (only after expiry selection)
    if should_show_final_controls():
        render_view_mode_selector()
        render_strike_range_selector()
        render_refresh_interval_selector()
        render_blackscholes_in_markets()
        render_fetch_button()

def initialize_dhan_if_needed():
    """Initialize Dhan client if not already done."""
    if not st.session_state.dhan_client:
        credentials = load_dhan_credentials()
        if credentials['client_id'] and credentials['access_token']:
            # Get lot size for selected asset
            lot_size = get_current_lot_size()
            with st.spinner("Connecting to Dhan..."):
                if initialize_dhan_client(credentials['client_id'], credentials['access_token'], lot_size):
                    st.success("✅ Connected")
                    logger.info("Successfully connected")
                else:
                    st.error("❌ Connection Failed")
                    logger.error("Failed to connect to Dhan")
        else:
            st.warning("⚠️ Credentials missing")
            logger.warning("Credentials not found in configuration")
    else:
        st.success("✅ Ready")

def render_segment_dropdown():
    """Render segment selection dropdown for Dhan markets."""
    # Load segments on demand
    if not st.session_state.available_segments:
        df = load_trading_assets()
        st.session_state.available_segments = get_segments_from_csv(df)
    
    segment_options = ['Select...'] + [seg['display_name'] for seg in st.session_state.available_segments]
    
    current_index = 0
    if st.session_state.selected_segment in segment_options:
        current_index = segment_options.index(st.session_state.selected_segment)
    
    selected_segment = st.selectbox(
        "Segment:",
        options=segment_options,
        index=current_index,
        key="segment_dropdown"
    )
    
    # Handle segment change
    if selected_segment != st.session_state.selected_segment:
        logger.info(f"Segment changed to {selected_segment}")
        st.session_state.selected_segment = selected_segment
        reset_downstream_selections('segment')
        
        if selected_segment != 'Select...':
            # Extract segment ID from selection
            segment_data = next((seg for seg in st.session_state.available_segments 
                               if seg['display_name'] == selected_segment), None)
            if segment_data:
                st.session_state.selected_segment_id = segment_data['id']
                logger.info(f"Selected segment ID: {segment_data['id']}")

def render_asset_dropdown():
    """Render asset selection dropdown."""
    # Load assets for selected segment
    if st.session_state.selected_segment_id and not st.session_state.available_assets:
        df = load_trading_assets()
        st.session_state.available_assets = get_assets_for_segment_from_csv(df, st.session_state.selected_segment_id)
    
    if not st.session_state.available_assets:
        st.warning("No assets available for selected segment")
        return
    
    asset_options = ['Select...'] + [asset['display_name'] for asset in st.session_state.available_assets]
    
    current_index = 0
    if st.session_state.selected_asset in asset_options:
        current_index = asset_options.index(st.session_state.selected_asset)
    
    selected_asset = st.selectbox(
        "Asset:",
        options=asset_options,
        index=current_index,
        key="asset_dropdown"
    )
    
    # Handle asset change
    if selected_asset != st.session_state.selected_asset:
        logger.info(f"Asset changed to {selected_asset}")
        st.session_state.selected_asset = selected_asset
        reset_downstream_selections('asset')
        
        if selected_asset != 'Select...':
            # Extract asset ID from selection
            asset_data = next((asset for asset in st.session_state.available_assets 
                             if asset['display_name'] == selected_asset), None)
            if asset_data:
                st.session_state.selected_asset_id = asset_data['id']
                logger.info(f"Selected asset ID: {asset_data['id']}")
                
                # Reinitialize Dhan client with correct lot size for new asset
                if st.session_state.dhan_client:
                    credentials = load_dhan_credentials()
                    if credentials['client_id'] and credentials['access_token']:
                        lot_size = get_current_lot_size()
                        logger.info(f"Reinitializing Dhan client with lot size: {lot_size}")
                        initialize_dhan_client(credentials['client_id'], credentials['access_token'], lot_size)

def render_expiry_dropdown():
    """Render expiry selection dropdown for Dhan assets."""
    # Load expiries on demand
    if not st.session_state.available_expiries:
        load_expiries_for_selected_asset()
    
    if not st.session_state.available_expiries:
        st.warning("No expiry dates available")
        return
    
    expiry_options = ['Select...'] + st.session_state.available_expiries
    
    current_index = 0
    if st.session_state.selected_expiry in expiry_options:
        current_index = expiry_options.index(st.session_state.selected_expiry)
    
    selected_expiry = st.selectbox(
        "Expiry:",
        options=expiry_options,
        index=current_index,
        key="expiry_dropdown"
    )
    
    # Handle expiry change
    if selected_expiry != st.session_state.selected_expiry:
        logger.info(f"Expiry changed to {selected_expiry}")
        st.session_state.selected_expiry = selected_expiry
        st.session_state.analytics_report = None  # figures shown belong to the previous expiry

def render_view_mode_selector():
    """Render view mode selection."""
    view_mode_options = ['Select...', 'Chain', 'Charts']
    
    current_index = 0
    if st.session_state.get('selected_view_mode', 'Select...') in view_mode_options:
        current_index = view_mode_options.index(st.session_state.get('selected_view_mode', 'Select...'))
    
    selected_view = st.selectbox(
        "View:",
        options=view_mode_options,
        index=current_index,
        key="view_mode_dropdown"
    )
    
    st.session_state.selected_view_mode = selected_view

def render_strike_range_selector():
    """Render strike range selection."""
    strike_range_options = {
        "±8 Strikes": 8,
        "±10 Strikes": 10,
        "±12 Strikes": 12,
        "±16 Strikes": 16,
        "±32 Strikes": 32,
        "All Strikes": None
    }
    
    # Get current selection
    current_range = st.session_state.get('strike_range', 16)
    current_key = "±16 Strikes"  # Default
    for key, value in strike_range_options.items():
        if value == current_range:
            current_key = key
            break
    
    selected_range = st.selectbox(
        "Strike Range:",
        options=list(strike_range_options.keys()),
        index=list(strike_range_options.keys()).index(current_key),
        key="strike_range_dropdown"
    )
    
    st.session_state.strike_range = strike_range_options[selected_range]

def render_refresh_interval_selector():
    """Render refresh interval selection - only for Chain view."""
    view_mode = st.session_state.get('selected_view_mode', 'Select...')
    
    if view_mode != 'Chain':
        return
    
    refresh_interval_options = {
        "Select...": None,
        "3s": 3.5,
        "5s": 5.0,
        "30s": 30.0,
        "5m": 300.0,
        "15m": 900.0
    }
    
    current_index = 0
    if st.session_state.get('selected_refresh_interval', 'Select...') in refresh_interval_options:
        current_index = list(refresh_interval_options.keys()).index(
            st.session_state.get('selected_refresh_interval', 'Select...')
        )
    
    selected_interval = st.selectbox(
        "Auto Refresh:",
        options=list(refresh_interval_options.keys()),
        index=current_index,
        key="refresh_interval_dropdown"
    )
    
    st.session_state.selected_refresh_interval = selected_interval
    st.session_state.refresh_interval_seconds = refresh_interval_options[selected_interval]

# Data refresh dropdown removed - use fetch button instead

def render_blackscholes_in_markets():
    """Render simplified Black-Scholes controls in Markets panel."""
    col1, col2 = st.columns(2)
    
    with col1:
        volatility_pct = st.number_input(
            "Volatility",
            min_value=1.0,
            max_value=100.0,
            value=st.session_state.get('bs_volatility', 0.10) * 100,
            step=1.0,
            key="bs_vol_markets"
        )
        st.session_state.bs_volatility = volatility_pct / 100.0
    
    with col2:
        rate_pct = st.number_input(
            "Risk-Free Rate",
            min_value=0.1,
            max_value=20.0,
            value=st.session_state.get('bs_risk_free_rate', 0.07) * 100,
            step=0.1,
            key="bs_rate_markets"
        )
        st.session_state.bs_risk_free_rate = rate_pct / 100.0

def render_fetch_button():
    """Render Dhan data fetch button."""
    button_text = "Fetch Data"
    button_help = "Fetch option chain data"
    
    if st.button(button_text, type="primary", width="stretch", help=button_help):
        fetch_data_for_provider()

def should_show_expiry_dropdown() -> bool:
    """Determine if expiry dropdown should be shown."""
    return (st.session_state.selected_segment != 'Select...' and 
            st.session_state.selected_asset != 'Select...')

def should_show_final_controls() -> bool:
    """Determine if final controls (strike range, BS params, fetch) should be shown."""
    return st.session_state.selected_expiry != 'Select...'

def reset_downstream_selections(level: str):
    """Reset downstream selections when upstream changes, and drop the fetched figures,
    which belong to the previous choice (until Fetch Data is pressed again)."""
    st.session_state.analytics_report = None
    if level == 'segment':
        st.session_state.selected_asset = 'Select...'
        st.session_state.selected_asset_id = None
        st.session_state.available_assets = []
        st.session_state.selected_expiry = 'Select...'
        st.session_state.available_expiries = []
        
    elif level == 'asset':
        st.session_state.selected_expiry = 'Select...'
        st.session_state.available_expiries = []

def load_expiries_for_selected_asset():
    """Load expiry dates for currently selected Dhan asset."""
    try:
        asset_id = st.session_state.selected_asset_id
        
        if not asset_id or asset_id is None:
            logger.debug("No asset selected for expiry loading")
            return
        
        client = st.session_state.dhan_client
        if not client:
            logger.warning("No client available for expiry loading")
            st.sidebar.warning("⚠️ Not connected")
            return
        
        with st.spinner("Loading expiry dates..."):
            segment_map = {1: 'IDX_I', 2: 'NSE_EQ', 3: 'MCX_COMM'}
            segment_code = segment_map.get(st.session_state.selected_segment_id, 'IDX_I')
            expiries = client.get_expiry_list(asset_id, segment_code)
            
            # Validate expiry data
            if expiries and isinstance(expiries, list) and len(expiries) > 0:
                # Filter out invalid dates
                valid_expiries = []
                for expiry in expiries:
                    try:
                        # Validate date format
                        datetime.strptime(expiry, '%Y-%m-%d')
                        valid_expiries.append(expiry)
                    except ValueError:
                        logger.warning(f"Invalid expiry date format: {expiry}")
                
                if valid_expiries:
                    st.session_state.available_expiries = valid_expiries
                    logger.info(f"Loaded {len(valid_expiries)} valid expiry dates for Dhan asset {asset_id}")
                    
                    # Debug info
                    if st.session_state.get('debug_mode', False):
                        st.sidebar.success(f"✅ {len(valid_expiries)} expiries loaded")
                else:
                    # The expiry box in the Markets panel says "No expiry dates available"
                    logger.warning(f"No valid expiries found for Dhan asset {asset_id}")
            else:
                # The expiry box in the Markets panel says "No expiry dates available"
                logger.warning(f"No expiries returned from Dhan for asset {asset_id}")

    except Exception as e:
        logger.error(f"Error loading expiries: {e}")
        st.sidebar.error(f"❌ Failed to load expiry dates")
        
        # Debug error details
        if st.session_state.get('debug_mode', False):
            st.sidebar.caption(f"Error: {str(e)[:100]}...")

def get_auto_bs_config() -> Dict[str, Any]:
    """Auto-detect Black-Scholes configuration for Dhan markets."""
    # Detect market from segment
    segment_id = st.session_state.get('selected_segment_id', 1)
    if segment_id == 3:  # MCX_COMM
        market = 'MCX'
    else:  # NSE_EQ or IDX_I
        market = 'NSE'

    return {
        'volatility': st.session_state.get('bs_volatility', 0.10),
        'risk_free_rate': st.session_state.get('bs_risk_free_rate', 0.07),
        'market': market
    }

def fetch_data_for_provider():
    """Fetch data using Dhan and refresh UI."""
    try:
        success = fetch_dhan_data()
        
        if success:
            st.sidebar.success("✅ Data fetched successfully")
            # Fresh data fetched - trigger complete UI refresh
            st.rerun()
        else:
            st.sidebar.error("❌ Failed to fetch data")
            
    except Exception as e:
        logger.error(f"Error fetching data: {e}")
        st.sidebar.error(f"Error: {str(e)}")

def render_settings_panel():
    """Render settings panel with credential management."""
    try:
        credential_manager = CredentialManager()
        
        # Show current credential status
        if credential_manager.credentials_exist():
            st.success("🔑 API Keys: Configured")
            
            if st.button("🔄 Update API Keys", key="update_creds_sidebar"):
                st.session_state.show_credential_form = True
                st.rerun()
                
            if st.button("🗑️ Clear API Keys", key="clear_creds_sidebar"):
                success, message = credential_manager.clear_credentials()
                if success:
                    st.success("Credentials cleared")
                    st.rerun()
                else:
                    st.error(f"Error: {message}")
        else:
            st.warning("🔑 API Keys: Not configured")
            if st.button("⚙️ Configure API Keys", key="config_creds_sidebar"):
                st.session_state.show_credential_form = True
                st.rerun()
        
        # Debug mode toggle
        debug_mode = st.checkbox("Debug Mode", 
                                value=st.session_state.get('debug_mode', False),
                                key="debug_toggle")
        st.session_state.debug_mode = debug_mode
        
        # App info
        with st.expander("📱 App Info", expanded=False):
            st.caption("LiteChain Options Analytics v1.0")
            st.caption("Built for Dhan API")
            st.caption("Desktop-ready with credential management")
            
    except Exception as e:
        logger.error(f"Error in settings panel: {e}")
        st.error("Settings panel error")

# Black-Scholes controls moved to Markets panel


# ============================================================================
# AUTO-REFRESH LOGIC
# ============================================================================

# ============================================================================
# MAIN UI TABS
# ============================================================================

def render_single_viewport():
    """Render single viewport with conditional content based on view mode."""
    # Check if credential form should be shown
    if st.session_state.get('show_credential_form', False):
        st.title("🔐 Update API Credentials")
        render_credential_setup()
        return
    
    view_mode = st.session_state.get('selected_view_mode', 'Select...')
    
    if view_mode == 'Select...':
        st.info("Please select a view mode from the sidebar to display content.")
        return
    
    # Conditional rendering - only selected view executes
    if view_mode == 'Chain':
        render_option_chain_display()
    elif view_mode == 'Charts':
        render_charts_display()

def render_option_chain_display():
    """Render option chain display without tab wrapper."""
    try:
        # Check if data is available
        if not is_data_available():
            show_no_data_warning(
                "",
                "Please select asset and fetch data in the sidebar."
            )
            return
        
        # Get analytics report (single source of truth)
        analytics_report = get_analytics_report()
        df = analytics_report['enhanced_dataframe']  # Direct access
        
        # Calculate required variables for table building
        underlying_price = df['underlying_price'].iloc[0] if 'underlying_price' in df.columns and not df.empty else 0
        
        # Get max pain from pre-calculated analytics report
        max_pain_strike = analytics_report.get('max_pain_strike', 0)
        
        # Get lot_size from active client
        lot_size = getattr(st.session_state.dhan_client, 'lot_size', 75) if st.session_state.dhan_client else 75
        
        # Build and display HTML table with correct lot_size
        html = build_unified_markets_table(
            df=df,
            underlying_price=underlying_price,
            max_pain_strike=max_pain_strike,
            analytics_report=analytics_report,
            lot_size=lot_size
        )
        
        if html:
            st.markdown(html, unsafe_allow_html=True)
        else:
            st.error("Failed to generate option chain table.")
            
    except Exception as e:
        logger.error(f"Error in option chain display: {e}")
        st.error(f"Option chain display error: {str(e)}")
        if st.session_state.get('debug_mode', False):
            st.exception(e)

def render_charts_display():
    """Render charts display without tab wrapper."""
    try:
        # Check if data is available
        if not is_data_available():
            show_no_data_warning(
                "",
                "Please fetch data first to view charts."
            )
            return
        
        # Get analytics report
        analytics_report = get_analytics_report()
        
        if analytics_report and 'enhanced_dataframe' in analytics_report:
            # VEX and GEX metrics at top
            gex = analytics_report.get('gex_analysis', {})
            vex = analytics_report.get('vex_analysis', {})
            
            if gex and vex:
                st.subheader("📊 Market Structure Analysis")
                
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.write(f"**Total GEX:** {format_gex_millions(gex.get('total_gex', 0))}")
                    st.write(f"**Call GEX:** {format_gex_millions(gex.get('call_gex', 0))}")
                    st.write(f"**Put GEX:** {format_gex_millions(gex.get('put_gex', 0))}")
                
                with col2:
                    st.write(f"**Total VEX:** {(vex.get('total_vex', 0)/1000):.1f}K")
                    st.write(f"**Call VEX:** {(vex.get('call_vex', 0)/1000):.1f}K")
                    st.write(f"**Put VEX:** {(vex.get('put_vex', 0)/1000):.1f}K")
                    st.write(f"**VEX Ratio (C/P):** {vex.get('vex_ratio', 0):.3f}")
                
                with col3:
                    # VEX Skew analysis
                    vex_skew = vex.get('vex_skew', 0)
                    st.write(f"**VEX Skew:** {_no_negative_zero(f'{vex_skew:.3f}')}")
                
                st.markdown("---")
            
            # Volatility metrics section
            vol = analytics_report.get('volatility_metrics', {})
            if vol:
                st.subheader("📈 Volatility Metrics")
                col1, col2, col3 = st.columns(3)
                
                with col1:
                    st.write(f"**Average IV:** {vol.get('avg_iv', 0):.2f}%")
                    st.write(f"**ATM IV:** {vol.get('atm_iv', 0):.2f}%")
                
                with col2:
                    st.write(f"**Call Avg IV:** {vol.get('call_avg_iv', 0):.2f}%")
                    st.write(f"**Put Avg IV:** {vol.get('put_avg_iv', 0):.2f}%")
                
                with col3:
                    st.write(f"**IV Skew (Put-Call):** {_no_negative_zero(format(vol.get('iv_skew', 0), '.2f'))}%")
                    st.write(f"**IV Range:** {vol.get('iv_range', 0):.2f}%")
            
            st.markdown("---")
            
            # Chart rendering: Direct call to visualization engine
            st.session_state.visualization_engine.create_comprehensive_dashboard(analytics_report)
        else:
            show_no_data_warning(
                "Dhan",
                "Please fetch data from Dhan first to view charts."
            )
            
    except Exception as e:
        logger.error(f"Error in charts display: {e}")
        st.error(f"Charts display error: {str(e)}")
        if st.session_state.get('debug_mode', False):
            st.exception(e)

# ============================================================================
# MAIN APPLICATION
# ============================================================================

def main():
    """Main application entry point with performance monitoring."""
    start_time = time.time()
    
    # Check credentials first - show setup if needed
    if not check_credentials_or_setup():
        return  # Exit early if credentials not configured
    
    # Initialize
    initialize_session_state()
    # CSS is loaded automatically in build_unified_markets_table()
    
    # Initialize CSV data loading - ONLY ONCE
    if 'csv_data_initialized' not in st.session_state:
        try:
            df = load_trading_assets()
            if not df.empty:
                st.session_state.csv_data_initialized = True
                logger.info("CSV data initialized successfully")
            else:
                st.session_state.csv_data_initialized = False
                st.error("Failed to load assets.csv file.")
        except Exception as e:
            logger.error(f"Failed to initialize CSV data: {e}")
            st.error("Failed to load asset configuration. Please check assets.csv file.")
            st.session_state.csv_data_initialized = False
    
    # Render sidebar
    render_sidebar()
    
    # Performance indicator (only show if debug mode)
    if st.session_state.get('debug_mode', False):
        initialization_time = time.time() - start_time
        st.caption(f"🚀 Initialized in {initialization_time:.2f}s")
    
    # Single viewport with conditional rendering
    render_single_viewport()
    
    # Auto-refresh logic for Chain view only (after main content)
    handle_auto_refresh()
    
    # Timer to keep auto-refresh active
    setup_auto_refresh_timer()

def handle_auto_refresh():
    """Handle auto-refresh logic for Chain view only using Streamlit's fragment approach."""
    try:
        # Only auto-refresh for Chain view
        view_mode = st.session_state.get('selected_view_mode', 'Select...')
        if view_mode != 'Chain':
            return
        
        # Check if refresh interval is set
        refresh_seconds = st.session_state.get('refresh_interval_seconds')
        if not refresh_seconds:
            return
        
        # Check if data is available and all selections are made
        if not should_auto_refresh():
            return
        
        # Use time-based refresh without continuous loops
        current_time = time.time()
        last_refresh = st.session_state.get('last_refresh_time', 0)
        
        # Initialize timing on first run
        if last_refresh == 0:
            st.session_state.last_refresh_time = current_time
            return
        
        time_since_last = current_time - last_refresh
        remaining_time = max(0, refresh_seconds - time_since_last)
        
        # Show status in sidebar
        if remaining_time > 0:
            st.sidebar.caption(f"🔄 Next refresh in {int(remaining_time)}s")
        
        # Only refresh when time is up and not already in progress
        if time_since_last >= refresh_seconds and not st.session_state.get('refresh_in_progress', False):
            st.session_state.refresh_in_progress = True
            st.sidebar.caption("🔄 Refreshing data...")
            
            # Trigger data fetch
            success = fetch_dhan_data()
            
            # Reset timing
            st.session_state.last_refresh_time = current_time
            st.session_state.refresh_in_progress = False
            
            if success:
                # Use st.rerun() only once after successful refresh
                st.rerun()
            
    except Exception as e:
        logger.error(f"Error in auto-refresh: {e}")
        st.session_state.refresh_in_progress = False

def should_auto_refresh() -> bool:
    """Check if conditions are met for auto-refresh."""
    return (
        st.session_state.get('selected_expiry', 'Select...') != 'Select...' and
        st.session_state.get('selected_asset_id') is not None and
        st.session_state.get('selected_segment_id') is not None and
        st.session_state.get('dhan_client') is not None
    )

def setup_auto_refresh_timer():
    """Keep auto-refresh timer active for Chain view."""
    view_mode = st.session_state.get('selected_view_mode', 'Select...')
    refresh_seconds = st.session_state.get('refresh_interval_seconds')
    
    if view_mode == 'Chain' and refresh_seconds and should_auto_refresh():
        time.sleep(1)  # Wait 1 second
        st.rerun()  # Trigger next check

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Critical application error: {e}")
        st.error("🚨 Critical application error. Please refresh the page.")
        st.exception(e)
        