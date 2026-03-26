# -*- coding: utf-8 -*-
"""
AI Network Monitor - Production Ready Version with Enhanced UI
"""

import streamlit as st
import pandas as pd
import numpy as np
import joblib
import requests
import time
from datetime import datetime
import mysql.connector
from mysql.connector import Error
import plotly.graph_objects as go
import os

# -------------------------
# CONFIG
# -------------------------
st.set_page_config(
    page_title="AI Network Monitor",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# -------------------------
# CUSTOM CSS
# -------------------------
st.markdown("""
<style>
    /* Import Google Fonts */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    /* Global Styles */
    .stApp {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        font-family: 'Inter', sans-serif;
    }
    
    /* Main Container */
    .main-header {
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        backdrop-filter: blur(10px);
        border-radius: 20px;
        padding: 2rem;
        margin-bottom: 2rem;
        border: 1px solid rgba(255,255,255,0.2);
        box-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.37);
    }
    
    .title {
        font-size: 3rem;
        font-weight: 800;
        background: linear-gradient(135deg, #fff 0%, #e0e0e0 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
        text-align: center;
    }
    
    .subtitle {
        text-align: center;
        color: rgba(255,255,255,0.8);
        font-size: 1.1rem;
        margin-bottom: 0;
    }
    
    /* Status Cards */
    .status-card {
        background: rgba(255,255,255,0.95);
        backdrop-filter: blur(10px);
        border-radius: 20px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        border: 1px solid rgba(255,255,255,0.3);
        transition: transform 0.3s ease;
    }
    
    .status-card:hover {
        transform: translateY(-5px);
    }
    
    .status-online {
        background: linear-gradient(135deg, #00b09b, #96c93d);
        color: white;
    }
    
    .status-recent {
        background: linear-gradient(135deg, #f09819, #ff5858);
        color: white;
    }
    
    .status-stale {
        background: linear-gradient(135deg, #757f9a, #d7dde8);
        color: white;
    }
    
    .status-offline {
        background: linear-gradient(135deg, #c31432, #240b36);
        color: white;
    }
    
    /* Metric Cards */
    .metric-card {
        background: rgba(255,255,255,0.95);
        border-radius: 15px;
        padding: 1.5rem;
        text-align: center;
        transition: all 0.3s ease;
        border: 1px solid rgba(255,255,255,0.2);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    .metric-card:hover {
        transform: scale(1.02);
        box-shadow: 0 8px 25px rgba(0,0,0,0.15);
    }
    
    .metric-value {
        font-size: 2.5rem;
        font-weight: 800;
        color: #667eea;
        margin: 0.5rem 0;
    }
    
    .metric-label {
        font-size: 0.9rem;
        color: #666;
        text-transform: uppercase;
        letter-spacing: 1px;
        font-weight: 600;
    }
    
    .metric-unit {
        font-size: 0.8rem;
        color: #999;
    }
    
    /* Alert Cards */
    .alert-card {
        border-radius: 15px;
        padding: 1rem;
        margin: 1rem 0;
        animation: pulse 2s infinite;
    }
    
    @keyframes pulse {
        0% { transform: scale(1); }
        50% { transform: scale(1.02); }
        100% { transform: scale(1); }
    }
    
    .alert-success {
        background: linear-gradient(135deg, #84fab0 0%, #8fd3f4 100%);
        border-left: 5px solid #28a745;
    }
    
    .alert-danger {
        background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        border-left: 5px solid #dc3545;
    }
    
    .alert-warning {
        background: linear-gradient(135deg, #ffecd2 0%, #fcb69f 100%);
        border-left: 5px solid #ffc107;
    }
    
    /* Charts */
    .chart-container {
        background: rgba(255,255,255,0.95);
        border-radius: 20px;
        padding: 1.5rem;
        margin: 1rem 0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    /* Footer */
    .footer {
        text-align: center;
        padding: 2rem;
        color: rgba(255,255,255,0.7);
        font-size: 0.9rem;
        margin-top: 2rem;
    }
    
    /* Custom Streamlit Elements */
    .stMetric {
        background: rgba(255,255,255,0.95);
        border-radius: 15px;
        padding: 1rem;
    }
    
    /* Animations */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(20px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .fade-in {
        animation: fadeIn 0.5s ease-out;
    }
</style>
""", unsafe_allow_html=True)

# -------------------------
# CONSTANTS
# -------------------------
ONLINE_THRESHOLD_SECONDS = 60
STALE_THRESHOLD_SECONDS = 120
OFFLINE_THRESHOLD_SECONDS = 300

CHANNEL_ID = "3272879"
READ_API_KEY = "DVHBFJFGLFO80Y2N"

# -------------------------
# DATABASE CONNECTION (UPDATED)
# -------------------------
def get_db_connection():
    try:
        return mysql.connector.connect(
            host=os.getenv("DB_HOST", "localhost"),
            database=os.getenv("DB_NAME", "network_monitor"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", "@Danielson2000"),
            port=int(os.getenv("DB_PORT", 3306)),
            connection_timeout=5
        )
    except Error as e:
        return None

# -------------------------
# MODEL
# -------------------------
@st.cache_resource
def load_model():
    try:
        return joblib.load("network_congestion_model.pkl")
    except:
        st.warning("⚠ Model not found → Using demo logic")
        return None

model = load_model()

# -------------------------
# PREDICTION
# -------------------------
def predict_network(devices, latency, packet_loss, bandwidth):
    try:
        devices = float(devices)
        latency = float(latency)
        packet_loss = float(packet_loss)
        bandwidth = float(bandwidth)

        if model is None:
            return 1 if (latency > 100 or packet_loss > 2 or bandwidth < 50 or devices > 15) else 0

        return int(model.predict([[devices, latency, packet_loss, bandwidth]])[0])
    except:
        return 0

# -------------------------
# FETCH DATA (SAFE)
# -------------------------
@st.cache_data(ttl=5)
def fetch_data():
    try:
        url = f"http://api.thingspeak.com/channels/{CHANNEL_ID}/feeds.json?api_key={READ_API_KEY}&results=1"
        res = requests.get(url, timeout=5)
        res.raise_for_status()
        data = res.json()

        feed = data["feeds"][0]
        timestamp = datetime.strptime(feed["created_at"], '%Y-%m-%dT%H:%M:%SZ')
        now = datetime.utcnow()

        diff = (now - timestamp).total_seconds()

        if diff > OFFLINE_THRESHOLD_SECONDS:
            return 0,0,0,0,"offline",diff

        devices = int(feed["field1"] or 0)
        latency = float(feed["field2"] or 0)
        loss = float(feed["field3"] or 0)
        bw = float(feed["field4"] or 0)

        if diff <= ONLINE_THRESHOLD_SECONDS:
            status = "online"
        elif diff <= STALE_THRESHOLD_SECONDS:
            status = "recent"
        else:
            status = "stale"

        return devices, latency, loss, bw, status, diff

    except:
        return 0,0,0,0,"offline",999

# -------------------------
# SAVE TO DB
# -------------------------
def save_data(devices, latency, loss, bw, prediction):
    conn = get_db_connection()
    if not conn:
        return False

    try:
        cursor = conn.cursor()

        query = """
        INSERT INTO network_metrics 
        (devices, latency, packet_loss, bandwidth, congestion_prediction, timestamp)
        VALUES (%s,%s,%s,%s,%s,%s)
        """

        cursor.execute(query, (
            int(devices),
            float(latency),
            float(loss),
            float(bw),
            int(prediction),
            datetime.now()
        ))

        conn.commit()
        cursor.close()
        conn.close()
        return True

    except:
        return False

# -------------------------
# CREATE GAUGE CHART
# -------------------------
def create_gauge_chart(value, title, min_val=0, max_val=100, threshold=70):
    fig = go.Figure(go.Indicator(
        mode = "gauge+number",
        value = value,
        title = {'text': title, 'font': {'size': 14}},
        domain = {'x': [0, 1], 'y': [0, 1]},
        gauge = {
            'axis': {'range': [min_val, max_val], 'tickwidth': 1},
            'bar': {'color': "#667eea"},
            'steps': [
                {'range': [min_val, threshold], 'color': "lightgreen"},
                {'range': [threshold, max_val], 'color': "orange"}
            ],
            'threshold': {
                'line': {'color': "red", 'width': 4},
                'thickness': 0.75,
                'value': threshold
            }
        }
    ))
    
    fig.update_layout(
        height=250,
        margin=dict(l=20, r=20, t=50, b=20),
        paper_bgcolor='rgba(0,0,0,0)',
        font={'color': "#333"}
    )
    
    return fig

# -------------------------
# UI
# -------------------------
def main():
    # Header Section
    st.markdown("""
    <div class="main-header fade-in">
        <div class="title">
            📡 AI Network Monitor
        </div>
        <div class="subtitle">
            Real-time Network Intelligence & Congestion Detection
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    placeholder = st.empty()
    counter = 0
    
    # Sidebar with info
    with st.sidebar:
        st.markdown("""
        <div style="background: rgba(255,255,255,0.95); padding: 1.5rem; border-radius: 15px;">
            <h3 style="color: #667eea;">📊 System Info</h3>
            <p><strong>Model:</strong> Random Forest Classifier</p>
            <p><strong>Features:</strong> Devices, Latency, Packet Loss, Bandwidth</p>
            <p><strong>Update Interval:</strong> 5 seconds</p>
            <p><strong>Status Thresholds:</strong></p>
            <ul>
                <li>🟢 Online: &lt; 60s</li>
                <li>🟡 Recent: 60-120s</li>
                <li>⚪ Stale: 120-300s</li>
                <li>🔴 Offline: &gt; 300s</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
        # Add some spacing
        st.markdown("<br>", unsafe_allow_html=True)
        
        # Add a cute network icon
        st.markdown("""
        <div style="text-align: center; background: rgba(255,255,255,0.95); padding: 1rem; border-radius: 15px;">
            <h4 style="color: #667eea;">🌐 Network Health</h4>
            <p style="font-size: 0.9rem;">AI-powered monitoring for proactive network management</p>
        </div>
        """, unsafe_allow_html=True)

    while True:
        with placeholder.container():
            devices, latency, loss, bw, status, age = fetch_data()
            
            # Status Card with dynamic styling
            status_colors = {
                "online": "status-online",
                "recent": "status-recent",
                "stale": "status-stale",
                "offline": "status-offline"
            }
            
            status_icons = {
                "online": "🟢",
                "recent": "🟡",
                "stale": "⚪",
                "offline": "🔴"
            }
            
            status_text = {
                "online": "Network Active - Real-time Data",
                "recent": "Network Recent - Data Available",
                "stale": "Network Stale - Delayed Data",
                "offline": "Network Offline - No Data"
            }
            
            st.markdown(f"""
            <div class="status-card {status_colors.get(status, 'status-offline')} fade-in">
                <div style="display: flex; align-items: center; justify-content: space-between;">
                    <div>
                        <h2 style="margin: 0; color: white;">{status_icons.get(status, '🔴')} {status.upper()}</h2>
                        <p style="margin: 0; color: rgba(255,255,255,0.9);">{status_text.get(status, 'Unknown Status')}</p>
                        <p style="margin: 0; font-size: 0.8rem; color: rgba(255,255,255,0.8);">Last update: {age:.1f} seconds ago</p>
                    </div>
                    <div style="font-size: 3rem;">
                        📊
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Metrics in elegant cards
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.markdown("""
                <div class="metric-card fade-in">
                    <div class="metric-label">Connected Devices</div>
                    <div class="metric-value">{}</div>
                    <div class="metric-unit">active endpoints</div>
                </div>
                """.format(devices), unsafe_allow_html=True)
                
            with col2:
                st.markdown("""
                <div class="metric-card fade-in">
                    <div class="metric-label">Network Latency</div>
                    <div class="metric-value">{:.1f}</div>
                    <div class="metric-unit">milliseconds</div>
                </div>
                """.format(latency), unsafe_allow_html=True)
                
            with col3:
                st.markdown("""
                <div class="metric-card fade-in">
                    <div class="metric-label">Packet Loss</div>
                    <div class="metric-value">{:.2f}</div>
                    <div class="metric-unit">percentage</div>
                </div>
                """.format(loss), unsafe_allow_html=True)
                
            with col4:
                st.markdown("""
                <div class="metric-card fade-in">
                    <div class="metric-label">Bandwidth</div>
                    <div class="metric-value">{:.1f}</div>
                    <div class="metric-unit">Mbps</div>
                </div>
                """.format(bw), unsafe_allow_html=True)
            
            # Visualization Row
            if status in ["online", "recent"]:
                col_chart1, col_chart2 = st.columns(2)
                
                with col_chart1:
                    with st.container():
                        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
                        st.plotly_chart(create_gauge_chart(latency, "Latency Health", 0, 500, 100), 
                                      use_container_width=True, key="latency_gauge")
                        st.markdown('</div>', unsafe_allow_html=True)
                
                with col_chart2:
                    with st.container():
                        st.markdown('<div class="chart-container">', unsafe_allow_html=True)
                        st.plotly_chart(create_gauge_chart(bw, "Bandwidth Usage", 0, 1000, 50), 
                                      use_container_width=True, key="bandwidth_gauge")
                        st.markdown('</div>', unsafe_allow_html=True)
                
                # AI Prediction
                pred = predict_network(devices, latency, loss, bw)
                
                if pred == 1:
                    st.markdown("""
                    <div class="alert-card alert-danger fade-in">
                        <div style="display: flex; align-items: center; gap: 1rem;">
                            <div style="font-size: 2rem;">🚨</div>
                            <div>
                                <h3 style="margin: 0; color: #721c24;">Critical Congestion Risk Detected!</h3>
                                <p style="margin: 0; color: #721c24;">Immediate action recommended to prevent network degradation.</p>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown("""
                    <div class="alert-card alert-success fade-in">
                        <div style="display: flex; align-items: center; gap: 1rem;">
                            <div style="font-size: 2rem;">✅</div>
                            <div>
                                <h3 style="margin: 0; color: #155724;">Network Operating Normally</h3>
                                <p style="margin: 0; color: #155724;">All metrics within acceptable ranges.</p>
                            </div>
                        </div>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Save to database periodically
                counter += 1
                if counter % 5 == 0:
                    if save_data(devices, latency, loss, bw, pred):
                        st.toast("💾 Data saved to database", icon="✅")
                    else:
                        st.toast("⚠️ Failed to save to database", icon="❌")
            else:
                st.markdown("""
                <div class="alert-card alert-warning fade-in">
                    <div style="display: flex; align-items: center; gap: 1rem;">
                        <div style="font-size: 2rem;">⚠️</div>
                        <div>
                            <h3 style="margin: 0; color: #856404;">No Valid Data Available</h3>
                            <p style="margin: 0; color: #856404;">Waiting for network data to become available.</p>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            # Footer
            st.markdown("""
            <div class="footer fade-in">
                <p>🤖 Powered by AI • Real-time Network Intelligence • Predictive Analytics</p>
                <p style="font-size: 0.8rem;">Data updates every 5 seconds • Last refresh: {}</p>
            </div>
            """.format(datetime.now().strftime("%Y-%m-%d %H:%M:%S")), unsafe_allow_html=True)
            
        time.sleep(5)

# -------------------------
if __name__ == "__main__":
    main()
