"""
Credential handling for LiteChain.
Dhan credentials are held in the app's memory for the current browser session (typed into the
setup screen), or read from .streamlit/secrets.toml. Nothing is written to disk by this module.
"""

import streamlit as st
import uuid
from typing import Dict, Tuple

class CredentialManager:
    """
    Credential manager: credentials typed into the app are held in the app's memory for the
    current browser session only, under a key unique to that session. If none are held, the
    Dhan section of .streamlit/secrets.toml is used. Nothing is written to disk.
    """
    
    def __init__(self):
        """Initialize with session-specific isolation."""
        # Create unique session ID for complete user isolation
        if 'session_id' not in st.session_state:
            st.session_state.session_id = str(uuid.uuid4())
        
        self.session_key = f"creds_{st.session_state.session_id}"
        
    def validate_credentials(self, client_id: str, access_token: str) -> Tuple[bool, str]:
        """
        Validate credential format (basic validation).
        
        Args:
            client_id: Client ID to validate
            access_token: Access token to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not client_id or len(client_id.strip()) < 5:
            return False, "Client ID must be at least 5 characters long"
        
        if not access_token or len(access_token.strip()) < 10:
            return False, "Access Token must be at least 10 characters long"
        
        # Basic format check for Dhan access token (JWT format)
        if not access_token.startswith('eyJ'):
            return False, "Access Token appears to be invalid format (should start with 'eyJ')"
        
        if access_token.count('.') != 2:
            return False, "Access Token appears to be invalid format (should have 2 dots)"
        
        return True, "Valid"
    
    def get_credentials(self) -> Dict[str, str]:
        """
        Get credentials: those typed in for this session first, else .streamlit/secrets.toml.

        Returns:
            Dict with client_id and access_token
        """
        # Credentials typed into the app for this session
        if self.session_key in st.session_state:
            creds = st.session_state[self.session_key]
            if creds.get('client_id') and creds.get('access_token'):
                return creds

        # Otherwise the [dhan] section of .streamlit/secrets.toml
        try:
            if hasattr(st, 'secrets') and 'dhan' in st.secrets:
                client_id = st.secrets.dhan.get('client_id', '')
                access_token = st.secrets.dhan.get('access_token', '')
                if client_id and access_token:
                    return {'client_id': client_id, 'access_token': access_token}
        except:
            pass
        
        return {'client_id': '', 'access_token': ''}
    
    def credentials_exist(self) -> bool:
        """Check if credentials are configured."""
        creds = self.get_credentials()
        return bool(creds['client_id'] and creds['access_token'])
    
    def save_credentials_to_session(self, client_id: str, access_token: str) -> Tuple[bool, str]:
        """
        Save credentials in the app's memory for this browser session only (not written to disk).
        
        Args:
            client_id: Dhan Client ID
            access_token: Dhan Access Token
            
        Returns:
            Tuple of (success, message)
        """
        try:
            # Validate first
            is_valid, error_msg = self.validate_credentials(client_id, access_token)
            if not is_valid:
                return False, error_msg
            
            # Store in session state only
            st.session_state[self.session_key] = {
                'client_id': client_id.strip(),
                'access_token': access_token.strip()
            }
            
            return True, "Credentials saved for this session."
                
        except Exception as e:
            return False, f"Error saving credentials: {str(e)}"
    
    def clear_credentials(self) -> Tuple[bool, str]:
        """
        Clear credentials from session state.
        
        Returns:
            Tuple of (success, message)
        """
        try:
            # Clear from session state
            if self.session_key in st.session_state:
                del st.session_state[self.session_key]
            
            # Clear related session data
            keys_to_clear = [
                'dhan_client', 'dhan_client_id', 'dhan_access_token',
                'analytics_report', 'available_segments', 'available_assets',
                'selected_segment', 'selected_asset', 'selected_expiry'
            ]
            
            for key in keys_to_clear:
                if key in st.session_state:
                    del st.session_state[key]
            
            return True, "Session cleared successfully!"
                
        except Exception as e:
            return False, f"Error clearing credentials: {str(e)}"
    
    def reset_session(self) -> None:
        """Complete session reset for new user."""
        # Generate new session ID
        st.session_state.session_id = str(uuid.uuid4())
        
        # Clear all session state except system keys
        system_keys = {'session_id'}
        keys_to_delete = [key for key in st.session_state.keys() if key not in system_keys]
        
        for key in keys_to_delete:
            del st.session_state[key]


def render_credential_setup():
    """
    Streamlit UI for entering, viewing (hidden) and clearing Dhan credentials.
    """
    credential_manager = CredentialManager()
    
    st.subheader("🔐 API Credentials Setup")
    
    # Check if credentials exist
    existing_creds = credential_manager.get_credentials()
    credentials_configured = credential_manager.credentials_exist()
    
    if credentials_configured:
        st.success("✅ Credentials configured")
        
        # Show masked credentials
        with st.expander("View Current Credentials", expanded=False):
            client_id = existing_creds['client_id']
            access_token = existing_creds['access_token']
            
            st.text_input(
                "Client ID", 
                value=f"{client_id[:4]}...{client_id[-4:]}" if len(client_id) > 8 else client_id,
                disabled=True
            )
            st.text_input(
                "Access Token",
                value="••••••••" if access_token else "",
                disabled=True
            )
        
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("🔄 Update Credentials", type="secondary"):
                st.session_state.show_credential_form = True
        with col2:
            if st.button("🗑️ Clear Session", type="secondary"):
                success, message = credential_manager.clear_credentials()
                if success:
                    st.success(message)
                    st.session_state.show_credential_form = False
                    st.rerun()
                else:
                    st.error(message)
        with col3:
            if st.button("🔄 New Session", type="secondary"):
                credential_manager.reset_session()
                st.success("New session started!")
                st.rerun()
    else:
        st.warning("⚠️ No credentials found. Please enter your Dhan API keys to use the application.")
        st.session_state.show_credential_form = True
    
    # Show credential input form
    if st.session_state.get('show_credential_form', False):
        st.markdown("---")
        st.subheader("Enter API Credentials")
        
        st.info("🔒 Your credentials are kept in this app's memory, on this computer, for this browser session only. They are not written to disk and are sent only to Dhan.")

        with st.form("credential_form"):
            st.markdown("""
            **How to get your Dhan API credentials:**
            1. Log in at [web.dhan.co](https://web.dhan.co)
            2. Open My Profile → Access DhanHQ APIs
            3. Choose Generate Access Token (Dhan says a token is valid for 24 hours)
            4. Copy the token, and your Dhan Client ID
            """)
            
            client_id = st.text_input(
                "Dhan Client ID", 
                value=existing_creds.get('client_id', ''),
                placeholder="Enter your Dhan Client ID",
                help="Your unique Dhan Client ID (usually 10-12 digits)"
            )
            
            access_token = st.text_input(
                "Dhan Access Token",
                value=existing_creds.get('access_token', ''),
                type="password",
                placeholder="Enter your Dhan Access Token (JWT format)",
                help="Your Dhan API Access Token (starts with 'eyJ'). Shown masked."
            )
            
            col1, col2 = st.columns(2)
            with col1:
                save_button = st.form_submit_button("💾 Save to Session", type="primary")
            with col2:
                cancel_button = st.form_submit_button("❌ Cancel")
            
            if save_button:
                if client_id and access_token:
                    with st.spinner("Saving credentials..."):
                        success, message = credential_manager.save_credentials_to_session(client_id, access_token)
                    
                    if success:
                        st.success(message)
                        st.session_state.show_credential_form = False
                        st.balloons()
                        st.rerun()
                    else:
                        st.error(message)
                else:
                    st.error("Please fill in both Client ID and Access Token")
            
            if cancel_button:
                st.session_state.show_credential_form = False
                st.rerun()


def check_credentials_or_setup() -> bool:
    """
    Check if credentials exist, if not show setup screen.
    
    Returns:
        True if credentials are available, False if setup needed
    """
    credential_manager = CredentialManager()
    
    if not credential_manager.credentials_exist():
        st.title("🔐 LiteChain - API Setup Required")
        st.markdown("""
        Welcome to LiteChain Options Analytics Platform!
        
        To get started, you need to enter your Dhan API credentials.
        They are kept in this app's memory for this browser session only and are not written to disk.
        """)
        
        render_credential_setup()
        return False
    
    return True