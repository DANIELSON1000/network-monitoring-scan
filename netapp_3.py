# -*- coding: utf-8 -*-
"""
AI Network Monitor with MySQL Database Integration
Created for XAMPP MySQL Database
"""

import streamlit as st
import pandas as pd
import numpy as np
import joblib
import requests
import time
from datetime import datetime, timedelta
import mysql.connector
from mysql.connector import Error
import plotly.graph_objects as go
import plotly.express as px
import threading

# -------------------------
# Page Configuration
# -------------------------
st.set_page_config(
    page_title="AI Network Monitor",
    page_icon="📡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# -------------------------
# Constants
# -------------------------
ONLINE_THRESHOLD_SECONDS = 60
STALE_THRESHOLD_SECONDS = 120
OFFLINE_THRESHOLD_SECONDS = 300

# -------------------------
# Database Connection Function
# -------------------------
def get_db_connection():
    """Create connection to MySQL database"""
    try:
        connection = mysql.connector.connect(
            host='localhost',
            database='network_monitor',
            user='root',
            password='',
            connection_timeout=5
        )
        return connection
    except Error as e:
        return None

# -------------------------
# Initialize Database Tables
# -------------------------
def initialize_database():
    """Create necessary tables if they don't exist"""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            
            # Create network_metrics table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS network_metrics (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    timestamp DATETIME NOT NULL,
                    devices INT,
                    latency FLOAT,
                    packet_loss FLOAT,
                    bandwidth FLOAT,
                    congestion_prediction INT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create recommendations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    metric_id INT,
                    recommendation TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (metric_id) REFERENCES network_metrics(id) ON DELETE CASCADE
                )
            """)
            
            # Create system_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    log_type VARCHAR(20),
                    message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            connection.commit()
            cursor.close()
            connection.close()
            return True
        except Error as e:
            return False
    return False

# -------------------------
# Save Metrics to Database
# -------------------------
def save_to_database(devices, latency, packet_loss, bandwidth, prediction, data_age_seconds):
    """Save network metrics to database"""
    if data_age_seconds > STALE_THRESHOLD_SECONDS:
        return False
    
    if devices == 0 and latency == 0 and packet_loss == 0 and bandwidth == 0:
        return False
    
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            
            devices = int(devices)
            latency = float(latency)
            packet_loss = float(packet_loss)
            bandwidth = float(bandwidth)
            prediction = int(prediction)
            
            query = """
                INSERT INTO network_metrics 
                (devices, latency, packet_loss, bandwidth, congestion_prediction, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            current_time = datetime.now()
            cursor.execute(query, (devices, latency, packet_loss, bandwidth, prediction, current_time))
            metric_id = cursor.lastrowid
            
            advice_list, _ = network_advice(devices, latency, packet_loss, bandwidth, prediction)
            
            for advice in advice_list:
                rec_query = "INSERT INTO recommendations (metric_id, recommendation) VALUES (%s, %s)"
                cursor.execute(rec_query, (metric_id, advice))
            
            log_query = "INSERT INTO system_logs (log_type, message) VALUES (%s, %s)"
            log_message = f'Network metrics saved - Devices: {devices}, Latency: {latency}, Prediction: {prediction}'
            cursor.execute(log_query, ('INFO', log_message))
            
            connection.commit()
            cursor.close()
            connection.close()
            return True
        except Error as e:
            return False
    return False

# -------------------------
# Predict Network Congestion
# -------------------------
def predict_network(devices, latency, packet_loss, bandwidth):
    """Predict network congestion"""
    devices = float(devices) if not isinstance(devices, (int, float)) else devices
    latency = float(latency)
    packet_loss = float(packet_loss)
    bandwidth = float(bandwidth)
    
    if model is None:
        if latency > 100 or packet_loss > 2 or bandwidth < 50 or devices > 15:
            return 1
        return 0
    
    sample = [[devices, latency, packet_loss, bandwidth]]
    prediction = model.predict(sample)[0]
    return int(prediction)

# -------------------------
# Fetch ThingSpeak Data
# -------------------------
@st.cache_data(ttl=5)
def fetch_thingspeak_data():
    """Fetch data from ThingSpeak"""
    try:
        CHANNEL_ID = "3272879"
        READ_API_KEY = "DVHBFJFGLFO80Y2N"
        url = f"http://api.thingspeak.com/channels/{CHANNEL_ID}/feeds.json?api_key={READ_API_KEY}&results=1"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if 'feeds' in data and len(data['feeds']) > 0:
            latest = data['feeds'][0]
            last_update_str = latest.get('created_at')
            
            if last_update_str:
                last_update = datetime.strptime(last_update_str, '%Y-%m-%dT%H:%M:%SZ')
                current_time = datetime.utcnow()
                time_diff = (current_time - last_update).total_seconds()
                
                if time_diff > OFFLINE_THRESHOLD_SECONDS:
                    return 0, 0.0, 0.0, 0.0, time_diff, last_update, "offline"
                elif time_diff > STALE_THRESHOLD_SECONDS:
                    return 0, 0.0, 0.0, 0.0, time_diff, last_update, "stale"
            
            field1 = latest.get('field1')
            field2 = latest.get('field2')
            field3 = latest.get('field3')
            field4 = latest.get('field4')
            
            if field1 is None or field2 is None or field3 is None or field4 is None:
                return 0, 0.0, 0.0, 0.0, time_diff if last_update_str else OFFLINE_THRESHOLD_SECONDS, last_update if last_update_str else None, "offline"
            
            devices = int(field1) if field1 else 0
            latency = float(field2) if field2 else 0.0
            packet_loss = float(field3) if field3 else 0.0
            bandwidth = float(field4) if field4 else 0.0
            
            if devices == 0 and latency == 0 and packet_loss == 0 and bandwidth == 0:
                return 0, 0.0, 0.0, 0.0, time_diff, last_update, "offline"
            
            if time_diff <= ONLINE_THRESHOLD_SECONDS:
                status = "online"
            elif time_diff <= STALE_THRESHOLD_SECONDS:
                status = "recent"
            else:
                status = "stale"
                
            return devices, latency, packet_loss, bandwidth, time_diff, last_update, status
        else:
            return 0, 0.0, 0.0, 0.0, OFFLINE_THRESHOLD_SECONDS, None, "offline"
            
    except Exception as e:
        return 0, 0.0, 0.0, 0.0, OFFLINE_THRESHOLD_SECONDS, None, "offline"

# -------------------------
# Get ThingSpeak Status Only
# -------------------------
def get_thingspeak_status():
    """Get only the status, time_diff, and last_update from ThingSpeak"""
    devices, latency, packet_loss, bandwidth, time_diff, last_update, status = fetch_thingspeak_data()
    return status, time_diff, last_update

# -------------------------
# Get Database Statistics
# -------------------------
@st.cache_data(ttl=30)
def get_db_statistics():
    """Get statistics from database"""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM network_metrics")
            total_records = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM network_metrics WHERE congestion_prediction = 1")
            congestion_count = cursor.fetchone()[0]
            
            cursor.execute("""
                SELECT AVG(latency), AVG(packet_loss), AVG(bandwidth), AVG(devices)
                FROM network_metrics
            """)
            avg_data = cursor.fetchone()
            
            cursor.close()
            connection.close()
            
            return {
                'total_records': int(total_records) if total_records else 0,
                'congestion_count': int(congestion_count) if congestion_count else 0,
                'avg_latency': float(avg_data[0]) if avg_data[0] else 0.0,
                'avg_packet_loss': float(avg_data[1]) if avg_data[1] else 0.0,
                'avg_bandwidth': float(avg_data[2]) if avg_data[2] else 0.0,
                'avg_devices': float(avg_data[3]) if avg_data[3] else 0.0
            }
        except Error as e:
            return {}
    return {}

# -------------------------
# Load Historical Data
# -------------------------
@st.cache_data(ttl=30)
def load_historical_data(limit=100):
    """Load historical network metrics from database"""
    connection = get_db_connection()
    if connection:
        try:
            query = """
                SELECT id, timestamp, devices, latency, packet_loss, bandwidth, 
                       congestion_prediction
                FROM network_metrics
                ORDER BY timestamp DESC
                LIMIT %s
            """
            df = pd.read_sql(query, connection, params=(int(limit),))
            connection.close()
            
            if not df.empty:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
            return df
        except Error as e:
            return pd.DataFrame()
    return pd.DataFrame()

# -------------------------
# Load Recommendations History
# -------------------------
@st.cache_data(ttl=30)
def load_recommendations_history(limit=50):
    """Load recommendations with metrics data"""
    connection = get_db_connection()
    if connection:
        try:
            query = """
                SELECT r.id, r.recommendation, r.created_at,
                       n.timestamp, n.devices, n.latency, n.packet_loss, n.bandwidth,
                       n.congestion_prediction
                FROM recommendations r
                JOIN network_metrics n ON r.metric_id = n.id
                ORDER BY r.created_at DESC
                LIMIT %s
            """
            df = pd.read_sql(query, connection, params=(limit,))
            connection.close()
            return df
        except Error as e:
            return pd.DataFrame()
    return pd.DataFrame()

# -------------------------
# Load System Logs
# -------------------------
@st.cache_data(ttl=30)
def load_system_logs(limit=100):
    """Load system logs from database"""
    connection = get_db_connection()
    if connection:
        try:
            query = """
                SELECT id, log_type, message, created_at
                FROM system_logs
                ORDER BY created_at DESC
                LIMIT %s
            """
            df = pd.read_sql(query, connection, params=(limit,))
            connection.close()
            return df
        except Error as e:
            return pd.DataFrame()
    return pd.DataFrame()

# -------------------------
# Generate Recommendations
# -------------------------
def network_advice(devices, latency, packet_loss, bandwidth, prediction):
    advice = []
    severity_levels = []
    
    if devices == 0 and latency == 0 and packet_loss == 0 and bandwidth == 0:
        advice.append("⚠️ Network monitoring device is offline - No data available")
        severity_levels.append("warning")
        return advice, severity_levels
    
    if latency > 100:
        advice.append(f"⚠ High Latency ({latency:.1f}ms): Check router config, Enable QoS, Optimize routing")
        severity_levels.append("high")
    elif latency > 50:
        advice.append(f"⚠ Moderate Latency ({latency:.1f}ms): Monitor network traffic, consider optimization")
        severity_levels.append("medium")
    
    if packet_loss > 2:
        advice.append(f"⚠ Critical Packet Loss ({packet_loss:.2f}%): Check cables, switch ports, inspect interference")
        severity_levels.append("high")
    elif packet_loss > 1:
        advice.append(f"⚠ Packet Loss Detected ({packet_loss:.2f}%): Investigate network stability")
        severity_levels.append("medium")
    
    if bandwidth < 50:
        advice.append(f"⚠ Low Bandwidth ({bandwidth:.1f}Mbps): Upgrade ISP, limit heavy traffic apps")
        severity_levels.append("high")
    elif bandwidth < 100:
        advice.append(f"⚠ Moderate Bandwidth ({bandwidth:.1f}Mbps): Monitor usage patterns")
        severity_levels.append("medium")
    
    if devices > 15:
        advice.append(f"⚠ High Device Count ({devices} devices): Add APs, implement VLAN segmentation")
        severity_levels.append("high")
    elif devices > 10:
        advice.append(f"⚠ Growing Device Count ({devices} devices): Plan for network expansion")
        severity_levels.append("medium")
    
    if not advice:
        advice.append("✅ Network Operating Normally - All metrics within optimal ranges")
        severity_levels.append("good")
    
    if prediction == 1:
        advice.insert(0, "🚨 CRITICAL: AI predicts network congestion risk! Immediate action required.")
        severity_levels.insert(0, "critical")
    
    return advice, severity_levels

# -------------------------
# Format Time Difference
# -------------------------
def format_time_diff(seconds):
    if seconds < 60:
        return f"{int(seconds)} seconds ago"
    elif seconds < 3600:
        minutes = int(seconds / 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds / 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    else:
        days = int(seconds / 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"

# -------------------------
# Custom CSS - Beautiful Dark Gradient Background
# -------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    /* Global Styles */
    .stApp {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
        font-family: 'Inter', sans-serif;
    }
    
    /* Main Header */
    .main-header {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 2rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.1);
    }
    
    .main-title {
        font-size: 3rem;
        font-weight: 800;
        background: linear-gradient(135deg, #fff 0%, #e0e0e0 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .subtitle {
        color: rgba(255,255,255,0.9);
        font-size: 1.1rem;
    }
    
    /* Metric Cards */
    .metric-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        backdrop-filter: blur(10px);
        border-radius: 20px;
        padding: 1.5rem;
        box-shadow: 0 8px 20px rgba(0,0,0,0.2);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        border: 1px solid rgba(255,255,255,0.2);
    }
    
    .metric-card:hover {
        transform: translateY(-5px);
        box-shadow: 0 15px 30px rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.3);
    }
    
    .metric-label {
        font-size: 0.9rem;
        font-weight: 600;
        color: #a0aec0;
        text-transform: uppercase;
        letter-spacing: 1px;
        margin-bottom: 0.5rem;
    }
    
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #ffffff;
        margin-bottom: 0.25rem;
    }
    
    .metric-unit {
        font-size: 0.8rem;
        color: #a0aec0;
    }
    
    /* Prediction Cards */
    .prediction-risk {
        background: linear-gradient(135deg, #f56565 0%, #e53e3e 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 15px;
        text-align: center;
        box-shadow: 0 5px 15px rgba(229,62,62,0.3);
    }
    
    .prediction-normal {
        background: linear-gradient(135deg, #48bb78 0%, #38a169 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 15px;
        text-align: center;
        box-shadow: 0 5px 15px rgba(72,187,120,0.3);
    }
    
    .prediction-title {
        font-size: 1.3rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    
    /* Status Cards */
    .status-online, .status-recent, .status-stale, .status-offline {
        background: rgba(255,255,255,0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        padding: 1rem;
        margin: 1rem 0;
        text-align: center;
        border: 1px solid rgba(255,255,255,0.2);
    }
    
    .status-online {
        border-left: 4px solid #48bb78;
    }
    
    .status-recent {
        border-left: 4px solid #4299e1;
    }
    
    .status-stale {
        border-left: 4px solid #ed8936;
    }
    
    .status-offline {
        border-left: 4px solid #f56565;
    }
    
    /* Tabs Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: rgba(0,0,0,0.3);
        border-radius: 10px;
        padding: 5px;
    }
    
    .stTabs [data-baseweb="tab"] {
        background-color: rgba(255,255,255,0.1);
        color: #e2e8f0 !important;
        font-weight: 600;
        border-radius: 8px;
        padding: 10px 20px;
        transition: all 0.3s ease;
    }
    
    .stTabs [data-baseweb="tab"]:hover {
        background-color: rgba(255,255,255,0.2);
        color: white !important;
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
        box-shadow: 0 2px 10px rgba(102,126,234,0.3);
    }
    
    /* Tab Content */
    .stTabs [data-baseweb="tab-panel"] {
        background: rgba(255,255,255,0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        padding: 20px;
        margin-top: 10px;
        border: 1px solid rgba(255,255,255,0.2);
    }
    
    /* Headers in tabs */
    .stTabs [data-baseweb="tab-panel"] h1,
    .stTabs [data-baseweb="tab-panel"] h2,
    .stTabs [data-baseweb="tab-panel"] h3 {
        color: #ffffff !important;
        font-weight: 700 !important;
    }
    
    /* Text in tabs */
    .stTabs [data-baseweb="tab-panel"] p,
    .stTabs [data-baseweb="tab-panel"] span,
    .stTabs [data-baseweb="tab-panel"] div {
        color: #e2e8f0 !important;
    }
    
    /* Dataframe styling */
    .stDataFrame {
        background: rgba(0,0,0,0.3);
        border-radius: 10px;
        padding: 10px;
    }
    
    .stDataFrame table {
        color: #e2e8f0 !important;
    }
    
    .stDataFrame th {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
    }
    
    .stDataFrame td {
        color: #e2e8f0 !important;
    }
    
    /* Expander styling */
    .streamlit-expanderHeader {
        background: linear-gradient(135deg, rgba(102,126,234,0.2) 0%, rgba(118,75,162,0.2) 100%);
        border-radius: 10px;
        font-weight: 600;
        color: #ffffff !important;
        border: 1px solid rgba(255,255,255,0.2);
    }
    
    .streamlit-expanderContent {
        background: rgba(0,0,0,0.3);
        border-radius: 10px;
        color: #e2e8f0 !important;
    }
    
    /* Sidebar styling */
    .css-1d391kg, .css-163ttbj {
        background: linear-gradient(135deg, #0f0c29 0%, #1a1a2e 100%);
    }
    
    .css-1d391kg .stMarkdown, .css-163ttbj .stMarkdown {
        color: #e2e8f0 !important;
    }
    
    /* Buttons */
    .stButton button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 10px 20px;
        font-weight: 600;
        transition: all 0.3s ease;
    }
    
    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 5px 15px rgba(102,126,234,0.4);
    }
    
    /* Metrics in sidebar */
    .stMetric {
        background: rgba(255,255,255,0.1);
        border-radius: 10px;
        padding: 10px;
    }
    
    .stMetric label {
        color: #a0aec0 !important;
    }
    
    .stMetric div {
        color: #ffffff !important;
    }
    
    /* Info, success, warning boxes */
    .stAlert {
        background: rgba(0,0,0,0.5) !important;
        border: 1px solid rgba(255,255,255,0.2) !important;
        color: #e2e8f0 !important;
    }
    
    .stAlert div {
        color: #e2e8f0 !important;
    }
    
    /* Recommendation cards */
    .recommendation-card {
        background: rgba(0,0,0,0.3);
        border-radius: 15px;
        padding: 1rem;
        margin: 0.5rem 0;
        border-left: 4px solid #667eea;
        transition: all 0.3s ease;
    }
    
    .recommendation-card:hover {
        background: rgba(0,0,0,0.5);
        transform: translateX(5px);
    }
    
    .recommendation-text {
        color: #e2e8f0 !important;
        font-size: 0.95rem;
    }
    
    /* Footer */
    .footer {
        text-align: center;
        padding: 2rem;
        color: rgba(255,255,255,0.6);
        font-size: 0.9rem;
    }
    
    /* Plotly charts */
    .js-plotly-plot .plotly .main-svg {
        background: rgba(0,0,0,0.3) !important;
    }
    
    /* Download button */
    .stDownloadButton button {
        background: linear-gradient(135deg, #48bb78 0%, #38a169 100%);
    }
    
    /* Scrollbar */
    ::-webkit-scrollbar {
        width: 10px;
        height: 10px;
    }
    
    ::-webkit-scrollbar-track {
        background: rgba(0,0,0,0.3);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        border-radius: 10px;
    }
    
    ::-webkit-scrollbar-thumb:hover {
        background: linear-gradient(135deg, #764ba2 0%, #667eea 100%);
    }
</style>
""", unsafe_allow_html=True)

# -------------------------
# Load Model
# -------------------------
@st.cache_resource
def load_model():
    try:
        model = joblib.load("network_congestion_model.pkl")
        return model
    except:
        st.warning("⚠ Model file not found. Using demo mode.")
        return None

model = load_model()

# Initialize database tables
initialize_database()

# -------------------------
# Main App
# -------------------------
def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <div class="main-title">📡 AI Network Congestion Monitor</div>
        <div class="subtitle">Real-time network analytics with advanced AI prediction & MySQL integration</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 📊 System Status")
        
        # Fixed: Use get_thingspeak_status() instead of slicing
        status, time_diff, last_update = get_thingspeak_status()
        
        if status == "online":
            st.success(f"✅ ThingSpeak Device: ONLINE")
            st.info(f"📡 Last update: {format_time_diff(time_diff)}")
        elif status == "recent":
            st.info(f"🟢 ThingSpeak Device: RECENT DATA")
            st.info(f"📡 Last update: {format_time_diff(time_diff)}")
        elif status == "stale":
            st.warning(f"⚠️ ThingSpeak Device: STALE DATA")
            st.warning(f"⏰ No data for: {format_time_diff(time_diff)}")
        else:
            st.error(f"❌ ThingSpeak Device: OFFLINE")
        
        st.markdown("---")
        
        db_connection = get_db_connection()
        if db_connection:
            st.success("✅ MySQL Database: Connected")
            db_connection.close()
        else:
            st.error("❌ MySQL Database: Disconnected")
        
        st.markdown("---")
        
        stats = get_db_statistics()
        if stats and stats['total_records'] > 0:
            st.markdown("### 📈 Database Statistics")
            st.metric("Total Records", stats['total_records'])
            st.metric("Congestion Events", stats['congestion_count'])
            st.metric("Avg Latency", f"{stats['avg_latency']:.1f} ms")
            st.metric("Avg Bandwidth", f"{stats['avg_bandwidth']:.1f} Mbps")
        
        st.markdown("---")
        st.markdown("### 🤖 AI Model")
        st.markdown("Machine Learning model analyzing network patterns to predict congestion in real-time.")
        
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📡 Live Monitor", "📊 Historical Data", "💡 Recommendations", "📝 System Logs"])
    
    # Tab 1: Live Monitor
    with tab1:
        st.markdown("### 📡 Real-Time Network Monitoring")
        st.markdown("Live data feed from ThingSpeak with AI-powered analysis")
        
        # Create a placeholder for auto-refresh
        live_placeholder = st.empty()
        
        # Fetch and display data
        devices, latency, packet_loss, bandwidth, time_diff, last_update, status = fetch_thingspeak_data()
        
        with live_placeholder.container():
            # Status display
            if status == "online":
                st.markdown(f"""
                <div class="status-online">
                    <strong>✅ DEVICE ONLINE - RECEIVING LIVE DATA</strong><br>
                    Data received {format_time_diff(time_diff)}<br>
                    <small>Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'Unknown'} UTC</small>
                </div>
                """, unsafe_allow_html=True)
            elif status == "recent":
                st.markdown(f"""
                <div class="status-recent">
                    <strong>🟢 DEVICE ACTIVE - DATA AVAILABLE</strong><br>
                    Data received {format_time_diff(time_diff)}<br>
                    <small>Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'Unknown'} UTC</small>
                </div>
                """, unsafe_allow_html=True)
            elif status == "stale":
                st.markdown(f"""
                <div class="status-stale">
                    <strong>⚠️ STALE DATA - DEVICE MAY BE OFFLINE</strong><br>
                    No data received for {format_time_diff(time_diff)}<br>
                    <small>Last data: {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'Unknown'} UTC</small>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="status-offline">
                    <strong>❌ DEVICE OFFLINE - NO DATA RECEIVED</strong><br>
                    {f'Last data received {format_time_diff(time_diff)}' if last_update else 'No data ever received'}<br>
                    <small>Waiting for device to come online...</small>
                </div>
                """, unsafe_allow_html=True)
            
            st.markdown(f"""
            <div style="text-align: right; color: rgba(255,255,255,0.6); margin-bottom: 1rem;">
                Dashboard updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
            </div>
            """, unsafe_allow_html=True)
            
            # Metrics
            col1, col2, col3, col4 = st.columns(4)
            
            data_valid = status in ["online", "recent"] and not (devices == 0 and latency == 0)
            
            with col1:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">📱 Active Devices</div>
                    <div class="metric-value">{devices if data_valid else 0}</div>
                    <div class="metric-unit">connected devices</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col2:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">⏱️ Network Latency</div>
                    <div class="metric-value">{latency if data_valid else 0:.1f}</div>
                    <div class="metric-unit">milliseconds</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col3:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">📉 Packet Loss</div>
                    <div class="metric-value">{packet_loss if data_valid else 0:.2f}</div>
                    <div class="metric-unit">percentage</div>
                </div>
                """, unsafe_allow_html=True)
            
            with col4:
                st.markdown(f"""
                <div class="metric-card">
                    <div class="metric-label">🌐 Bandwidth</div>
                    <div class="metric-value">{bandwidth if data_valid else 0:.1f}</div>
                    <div class="metric-unit">Mbps</div>
                </div>
                """, unsafe_allow_html=True)
            
            # AI Prediction
            if data_valid:
                prediction = predict_network(devices, latency, packet_loss, bandwidth)
                
                if prediction == 1:
                    st.markdown("""
                    <div class="prediction-risk">
                        <div class="prediction-title">🚨 NETWORK CONGESTION RISK DETECTED</div>
                        <div>AI model predicts high probability of network congestion. Immediate action recommended!</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown("""
                    <div class="prediction-normal">
                        <div class="prediction-title">✅ NETWORK OPERATING NORMALLY</div>
                        <div>AI model indicates stable network conditions. All systems operational.</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Save to database
                save_to_database(devices, latency, packet_loss, bandwidth, prediction, time_diff)
            else:
                prediction = 0
            
            # Recommendations
            st.markdown("### 💡 IT Recommendations")
            advice_list, _ = network_advice(
                devices if data_valid else 0,
                latency if data_valid else 0,
                packet_loss if data_valid else 0,
                bandwidth if data_valid else 0,
                prediction
            )
            
            for advice in advice_list:
                if "CRITICAL" in advice:
                    st.error(advice)
                elif "⚠" in advice:
                    st.warning(advice)
                else:
                    st.success(advice)
    
    # Tab 2: Historical Data
    with tab2:
        st.markdown("### 📊 Historical Network Data Analysis")
        st.markdown("Analyze network performance trends and patterns over time")
        
        historical_df = load_historical_data(100)
        
        if not historical_df.empty:
            # Filters
            col1, col2, col3 = st.columns(3)
            with col1:
                show_congestion_only = st.checkbox("🔴 Show only congestion events", key="hist_congestion")
            with col2:
                days = st.slider("📅 Select days to show", 1, 30, 7)
                cutoff_date = datetime.now() - timedelta(days=days)
                historical_df = historical_df[historical_df['timestamp'] >= cutoff_date]
            with col3:
                if st.button("🔄 Reset Filters"):
                    st.rerun()
            
            if show_congestion_only:
                historical_df = historical_df[historical_df['congestion_prediction'] == 1]
            
            if not historical_df.empty:
                # Metrics overview
                st.markdown("#### 📈 Performance Metrics Overview")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Avg Latency", f"{historical_df['latency'].mean():.1f} ms", 
                             delta=f"{historical_df['latency'].mean() - historical_df['latency'].median():.1f}")
                with col2:
                    st.metric("Avg Packet Loss", f"{historical_df['packet_loss'].mean():.2f}%")
                with col3:
                    st.metric("Avg Bandwidth", f"{historical_df['bandwidth'].mean():.1f} Mbps")
                with col4:
                    st.metric("Avg Devices", f"{historical_df['devices'].mean():.1f}")
                
                # Time series chart
                st.markdown("#### 📊 Network Metrics Timeline")
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=historical_df['timestamp'], y=historical_df['latency'], 
                                        mode='lines+markers', name='Latency (ms)',
                                        line=dict(color='#f56565', width=2),
                                        marker=dict(size=6, color='#f56565')))
                fig.add_trace(go.Scatter(x=historical_df['timestamp'], y=historical_df['bandwidth'], 
                                        mode='lines+markers', name='Bandwidth (Mbps)',
                                        yaxis='y2',
                                        line=dict(color='#48bb78', width=2),
                                        marker=dict(size=6, color='#48bb78')))
                fig.add_trace(go.Scatter(x=historical_df['timestamp'], y=historical_df['packet_loss'] * 10, 
                                        mode='lines+markers', name='Packet Loss (x10 %)',
                                        line=dict(color='#4299e1', width=2, dash='dot'),
                                        marker=dict(size=6, color='#4299e1')))
                
                fig.update_layout(
                    title="<b>Network Metrics Over Time</b>",
                    xaxis_title="<b>Timestamp</b>",
                    yaxis_title="<b>Latency (ms)</b>",
                    yaxis2=dict(title="<b>Bandwidth (Mbps)</b>", overlaying='y', side='right'),
                    template="plotly_dark",
                    height=500,
                    hovermode='x unified',
                    plot_bgcolor='rgba(0,0,0,0.3)',
                    paper_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Congestion distribution
                col1, col2 = st.columns(2)
                with col1:
                    st.markdown("#### 🎯 Network Status Distribution")
                    congestion_counts = historical_df['congestion_prediction'].value_counts()
                    fig_pie = px.pie(values=congestion_counts.values, 
                                     names=['Normal Operation', 'Congestion Risk'],
                                     title='<b>Network Status Distribution</b>',
                                     color_discrete_sequence=['#48bb78', '#f56565'])
                    fig_pie.update_layout(showlegend=True, height=400, 
                                         plot_bgcolor='rgba(0,0,0,0.3)',
                                         paper_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_pie, use_container_width=True)
                
                with col2:
                    st.markdown("#### 🔗 Metrics Correlation Matrix")
                    corr_matrix = historical_df[['latency', 'packet_loss', 'bandwidth', 'devices']].corr()
                    fig_heatmap = px.imshow(corr_matrix, 
                                            text_auto=True, 
                                            title='<b>Metrics Correlation Matrix</b>',
                                            color_continuous_scale='RdBu',
                                            aspect='auto')
                    fig_heatmap.update_layout(height=400,
                                             plot_bgcolor='rgba(0,0,0,0.3)',
                                             paper_bgcolor='rgba(0,0,0,0)')
                    st.plotly_chart(fig_heatmap, use_container_width=True)
                
                # Data table
                st.markdown("#### 📋 Detailed Data Table")
                st.dataframe(historical_df, use_container_width=True, height=400)
                
                # Download button
                csv = historical_df.to_csv(index=False)
                st.download_button("📥 Download Data as CSV", csv, "network_metrics.csv", "text/csv")
            else:
                st.info("ℹ️ No data matches the selected filters.")
        else:
            st.info("📭 No historical data available yet. Data will appear as monitoring continues.")
    
    # Tab 3: Recommendations
    with tab3:
        st.markdown("### 💡 IT Recommendations History")
        st.markdown("AI-generated network optimization recommendations")
        
        recommendations_df = load_recommendations_history(50)
        
        if not recommendations_df.empty:
            # Summary statistics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Recommendations", len(recommendations_df))
            with col2:
                congestion_recs = len(recommendations_df[recommendations_df['congestion_prediction'] == 1])
                st.metric("Congestion-Related", congestion_recs)
            with col3:
                st.metric("Unique Issues", recommendations_df['recommendation'].nunique())
            
            st.markdown("---")
            
            # Display recommendations
            for idx, row in recommendations_df.iterrows():
                if row['congestion_prediction'] == 1:
                    icon = "🚨"
                    border_color = "#dc2626"
                else:
                    icon = "💡"
                    border_color = "#10b981"
                
                with st.expander(f"{icon} {row['created_at'].strftime('%Y-%m-%d %H:%M:%S')} - {row['recommendation'][:50]}...", expanded=False):
                    st.markdown(f"""
                    <div style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 10px; border-left: 4px solid {border_color};">
                        <p style="color: #e2e8f0; font-size: 1rem;"><strong>📋 Recommendation:</strong> {row['recommendation']}</p>
                        <hr style="margin: 10px 0; border-color: rgba(255,255,255,0.1);">
                        <p style="color: #e2e8f0;"><strong>📊 Network Metrics at Time:</strong></p>
                        <ul style="color: #cbd5e0;">
                            <li>🖥️ Connected Devices: {row['devices']}</li>
                            <li>⏱️ Latency: {row['latency']:.1f} ms</li>
                            <li>📉 Packet Loss: {row['packet_loss']:.2f}%</li>
                            <li>🌐 Bandwidth: {row['bandwidth']:.1f} Mbps</li>
                        </ul>
                        <p style="color: {'#f56565' if row['congestion_prediction'] == 1 else '#48bb78'};">
                            <strong>{'⚠️ Congestion Risk Detected' if row['congestion_prediction'] == 1 else '✅ Network Operating Normally'}</strong>
                        </p>
                        <p style="color: #a0aec0; font-size: 0.85rem;">📅 Generated: {row['created_at'].strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("📭 No recommendations available yet. Recommendations will appear when network data is analyzed.")
    
    # Tab 4: System Logs
    with tab4:
        st.markdown("### 📝 System Logs")
        st.markdown("Complete audit trail of system events and operations")
        
        logs_df = load_system_logs(100)
        
        if not logs_df.empty:
            # Log statistics
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Logs", len(logs_df))
            with col2:
                error_count = len(logs_df[logs_df['log_type'] == 'ERROR'])
                st.metric("Errors", error_count, delta_color="inverse")
            with col3:
                info_count = len(logs_df[logs_df['log_type'] == 'INFO'])
                st.metric("Info Events", info_count)
            
            st.markdown("---")
            
            # Color code logs
            def get_log_color(log_type):
                if log_type == 'ERROR':
                    return '#f56565'
                elif log_type == 'WARNING':
                    return '#ed8936'
                else:
                    return '#48bb78'
            
            # Display logs
            for idx, row in logs_df.iterrows():
                log_color = get_log_color(row['log_type'])
                st.markdown(f"""
                <div style="background: rgba(0,0,0,0.3); border-left: 4px solid {log_color}; padding: 10px; margin: 5px 0; border-radius: 5px;">
                    <small style="color: #a0aec0;">{row['created_at'].strftime('%Y-%m-%d %H:%M:%S')}</small>
                    <strong style="color: {log_color};">[{row['log_type']}]</strong>
                    <span style="color: #e2e8f0;">{row['message']}</span>
                </div>
                """, unsafe_allow_html=True)
            
            # Clear logs button
            col1, col2, col3 = st.columns([1, 1, 1])
            with col2:
                if st.button("🗑️ Clear All Logs", type="secondary", use_container_width=True):
                    connection = get_db_connection()
                    if connection:
                        cursor = connection.cursor()
                        cursor.execute("DELETE FROM system_logs")
                        connection.commit()
                        cursor.close()
                        connection.close()
                        st.success("✅ Logs cleared successfully!")
                        time.sleep(1)
                        st.rerun()
        else:
            st.info("📭 No logs available yet. System events will appear here as they occur.")

if __name__ == "__main__":
    main()
