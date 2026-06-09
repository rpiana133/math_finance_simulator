import streamlit as st
import json
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

SCOPES = [
    'https://www.googleapis.com/auth/classroom.coursework.students',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid'
]

def get_redirect_uri():
    return st.secrets.get("REDIRECT_URI", "https://mathfinancesimulator.streamlit.app/")

def init_auth_state():
    if 'credentials' not in st.session_state:
        st.session_state.credentials = None
    if 'user_info' not in st.session_state:
        st.session_state.user_info = None

def get_client_config():
    return json.loads(st.secrets["GOOGLE_CLIENT_SECRET"])

def do_login():
    client_config = get_client_config()
    flow = Flow.from_client_config(
        client_config, scopes=SCOPES,
        redirect_uri=get_redirect_uri()
    )
    flow.autogenerate_code_verifier = False
    flow.code_verifier = None
    auth_url, _ = flow.authorization_url(prompt='consent', access_type='offline')
    st.markdown(f"### [🔗 Click Here to Sign in with Google Workspace]({auth_url})")

def handle_redirect():
    query_params = st.query_params
    if 'code' in query_params:
        client_config = get_client_config()
        flow = Flow.from_client_config(
            client_config, scopes=SCOPES,
            redirect_uri=get_redirect_uri()
        )
        flow.autogenerate_code_verifier = False
        flow.code_verifier = None
        flow.fetch_token(code=query_params['code'])
        st.session_state.credentials = flow.credentials

        user_info_service = build('oauth2', 'v2', credentials=flow.credentials)
        st.session_state.user_info = user_info_service.userinfo().get().execute()

        st.query_params.clear()
        st.rerun()

LEGAL_STYLES = """
<style>
.legal-page { max-width: 720px; margin: 0 auto; }
.legal-page h2 { color: #0f172a; font-size: 1.8rem; margin-top: 2rem; }
.legal-page h3 { color: #1e293b; font-size: 1.3rem; margin-top: 1.5rem; }
.legal-page p, .legal-page li { color: #334155; line-height: 1.7; }
.legal-page hr { margin: 2rem 0; border: none; border-top: 1px solid #cbd5e1; }
</style>
"""

def _render_privacy():
    st.markdown(LEGAL_STYLES, unsafe_allow_html=True)
    st.markdown('<div class="legal-page">', unsafe_allow_html=True)
    st.markdown("## 📈 Math Finance Simulator")
    st.markdown("### Privacy Policy")
    st.markdown("*Last updated: May 29, 2026*")
    st.markdown("**Information We Collect**")
    st.markdown("- **Google Account Information:** When you sign in with Google Workspace, we receive your name, email address, and profile picture. We use this only to identify you within the classroom simulator.")
    st.markdown("- **Portfolio Data:** Your simulated trades, holdings, cash balance, and alert settings are stored in Google Cloud Storage and associated with your email address.")
    st.markdown("**How We Use Your Information**")
    st.markdown("- To provide and maintain the stock market simulation")
    st.markdown("- To display your portfolio performance and classroom standings")
    st.markdown("- To persist your data across sessions")
    st.markdown("**Data Storage & Security**")
    st.markdown("Your data is stored in Google Cloud Storage (GCS) with encryption at rest. Access is restricted to the application service account and your classroom teacher.")
    st.markdown("**Data Retention**")
    st.markdown("Your data is retained for the duration of the course. Upon request by your teacher, your account and associated data will be deleted.")
    st.markdown("**Third-Party Services**")
    st.markdown("- **Google Workspace:** Authentication only")
    st.markdown("- **Google Cloud Storage:** Data persistence")
    st.markdown("- **Yahoo Finance (yfinance):** Real-time and historical stock price data")
    st.markdown("**Contact**")
    st.markdown("For questions about this policy, contact your classroom instructor or the system administrator at St. John's School Guam.")
    st.markdown("**Changes**")
    st.markdown("We may update this policy. Changes will be communicated through the application.")
    st.markdown('<hr>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

def _render_terms():
    st.markdown(LEGAL_STYLES, unsafe_allow_html=True)
    st.markdown('<div class="legal-page">', unsafe_allow_html=True)
    st.markdown("## 📈 Math Finance Simulator")
    st.markdown("### Terms of Service")
    st.markdown("*Last updated: May 29, 2026*")
    st.markdown("**Acceptance**")
    st.markdown("By using Math Finance Simulator, you agree to these terms. This is an educational simulation tool for classroom use only.")
    st.markdown("**Educational Purpose Only**")
    st.markdown("- This application is a **simulation** using delayed market data from Yahoo Finance.")
    st.markdown("- All trades are **fictional** — no real money is involved.")
    st.markdown("- The simulator is for educational purposes and does not constitute financial advice.")
    st.markdown("**User Responsibilities**")
    st.markdown("- Use your school-provided Google Workspace account")
    st.markdown("- Do not attempt to access other users' data")
    st.markdown("- Do not manipulate or exploit the simulation")
    st.markdown("- Follow your instructor's guidelines for classroom use")
    st.markdown("**No Real Trading**")
    st.markdown("Math Finance Simulator does not execute real stock trades, handle real money, or provide investment recommendations.")
    st.markdown("**Data Disclaimer**")
    st.markdown("Stock price data is provided by Yahoo Finance and may be delayed. We are not responsible for data inaccuracies or service interruptions.")
    st.markdown("**Limitation of Liability**")
    st.markdown("""This software is provided "as is" without warranty. The developers and St. John's School Guam are not liable for any losses arising from its use.""")
    st.markdown("**Termination**")
    st.markdown("Your instructor may revoke access at any time. Upon course completion, your account may be deactivated.")
    st.markdown("**Governing Law**")
    st.markdown("These terms are governed by the laws of Guam, United States.")
    st.markdown('<hr>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)

def handle_legal_pages():
    if "page" not in st.session_state:
        try:
            if "page" in st.query_params:
                st.session_state.page = st.query_params["page"]
                st.rerun()
        except Exception:
            pass

    if st.session_state.get("page") == "privacy":
        _render_privacy()
        if st.button("← Back to App"):
            del st.session_state.page
            st.query_params.clear()
            st.rerun()
        st.stop()
    elif st.session_state.get("page") == "terms":
        _render_terms()
        if st.button("← Back to App"):
            del st.session_state.page
            st.query_params.clear()
            st.rerun()
        st.stop()
