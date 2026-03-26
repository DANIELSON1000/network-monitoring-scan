# -*- coding: utf-8 -*-
"""
AI Network Monitor with MySQL Database Integration
Enhanced UI with better visibility and comprehensive data display
Created for XAMPP MySQL Database
"""

import streamlit as st
import pandas as pd
import numpy as np
import joblib
import requests
import time
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
import mysql.connector
from mysql.connector import Error
import plotly.graph_objects as go
import plotly.express as px
import socket

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
# Constants for Time Thresholds
# -------------------------
ONLINE_THRESHOLD_SECONDS = 60  # Device is online if data received within last 60 seconds
STALE_THRESHOLD_SECONDS = 120  # Data is stale if older than 120 seconds (2 minutes)
OFFLINE_THRESHOLD_SECONDS = 300  # Consider device offline if no data for 5 minutes

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
            password='@Danielson2000',  # XAMPP default password is empty
            connection_timeout=5
        )
        return connection
    except Error as e:
        return None

# -------------------------
# Save Metrics to Database (Only when data is valid and recent)
# -------------------------
def save_to_database(devices, latency, packet_loss, bandwidth, prediction, data_age_seconds):
    """Save network metrics to database - only if data is valid and recent"""
    # Don't save if data is stale or offline (older than STALE_THRESHOLD_SECONDS)
    if data_age_seconds > STALE_THRESHOLD_SECONDS:
        return False
    
    # Don't save if all metrics are zero (indicates offline/error state)
    if devices == 0 and latency == 0 and packet_loss == 0 and bandwidth == 0:
        return False
    
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            
            # Convert numpy types to Python native types
            devices = int(devices)
            latency = float(latency)
            packet_loss = float(packet_loss)
            bandwidth = float(bandwidth)
            prediction = int(prediction)
            
            # Insert into network_metrics
            query = """
                INSERT INTO network_metrics 
                (devices, latency, packet_loss, bandwidth, congestion_prediction, timestamp)
                VALUES (%s, %s, %s, %s, %s, %s)
            """
            current_time = datetime.now()
            cursor.execute(query, (devices, latency, packet_loss, bandwidth, prediction, current_time))
            metric_id = cursor.lastrowid
            
            # Generate and save recommendations
            advice_list, _ = network_advice(devices, latency, packet_loss, bandwidth, prediction)
            
            for advice in advice_list:
                rec_query = "INSERT INTO recommendations (metric_id, recommendation) VALUES (%s, %s)"
                cursor.execute(rec_query, (metric_id, advice))
            
            # Log the action
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
    """Predict network congestion with proper type conversion"""
    # Convert to float/int to ensure correct types
    devices = float(devices) if not isinstance(devices, (int, float)) else devices
    latency = float(latency)
    packet_loss = float(packet_loss)
    bandwidth = float(bandwidth)
    
    if model is None:
        # Demo logic
        if latency > 100 or packet_loss > 2 or bandwidth < 50 or devices > 15:
            return 1
        return 0
    
    sample = [[devices, latency, packet_loss, bandwidth]]
    prediction = model.predict(sample)[0]
    return int(prediction)

# -------------------------
# Fetch ThingSpeak Data with Timestamp Check
# -------------------------
@st.cache_data(ttl=5)
def fetch_thingspeak_data():
    """Fetch data from ThingSpeak and check if data is fresh"""
    try:
        url = f"http://api.thingspeak.com/channels/{CHANNEL_ID}/feeds.json?api_key={READ_API_KEY}&results=1"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if 'feeds' in data and len(data['feeds']) > 0:
            latest = data['feeds'][0]
            
            # Get the timestamp of the last update
            last_update_str = latest.get('created_at')
            
            if last_update_str:
                # Parse the timestamp
                last_update = datetime.strptime(last_update_str, '%Y-%m-%dT%H:%M:%SZ')
                current_time = datetime.utcnow()
                
                # Calculate time difference in seconds
                time_diff = (current_time - last_update).total_seconds()
                
                # Check if data is too old (offline)
                if time_diff > OFFLINE_THRESHOLD_SECONDS:
                    # Device is offline - return zeros with age
                    return 0, 0.0, 0.0, 0.0, time_diff, last_update, "offline"
                elif time_diff > STALE_THRESHOLD_SECONDS:
                    # Data is stale but not completely offline
                    return 0, 0.0, 0.0, 0.0, time_diff, last_update, "stale"
            
            # Check if the feed has valid data (not None or empty)
            field1 = latest.get('field1')
            field2 = latest.get('field2')
            field3 = latest.get('field3')
            field4 = latest.get('field4')
            
            # If any field is None or empty, consider device offline
            if field1 is None or field2 is None or field3 is None or field4 is None:
                return 0, 0.0, 0.0, 0.0, time_diff if last_update_str else OFFLINE_THRESHOLD_SECONDS, last_update if last_update_str else None, "offline"
            
            # Convert to Python native types
            devices = int(field1) if field1 else 0
            latency = float(field2) if field2 else 0.0
            packet_loss = float(field3) if field3 else 0.0
            bandwidth = float(field4) if field4 else 0.0
            
            # If all values are zero, consider device offline
            if devices == 0 and latency == 0 and packet_loss == 0 and bandwidth == 0:
                return 0, 0.0, 0.0, 0.0, time_diff, last_update, "offline"
            
            # Determine status based on data freshness
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
        # Any exception (connection error, timeout, etc.) means device is offline
        return 0, 0.0, 0.0, 0.0, OFFLINE_THRESHOLD_SECONDS, None, "offline"

# -------------------------
# Check if ThingSpeak Device is Online (Based on Timestamp)
# -------------------------
def get_thingspeak_status():
    """Check ThingSpeak device status based on last update time"""
    try:
        url = f"http://api.thingspeak.com/channels/{CHANNEL_ID}/feeds.json?api_key={READ_API_KEY}&results=1"
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        
        if 'feeds' in data and len(data['feeds']) > 0:
            latest = data['feeds'][0]
            
            # Get the timestamp of the last update
            last_update_str = latest.get('created_at')
            
            if last_update_str:
                # Parse the timestamp
                last_update = datetime.strptime(last_update_str, '%Y-%m-%dT%H:%M:%SZ')
                current_time = datetime.utcnow()
                
                # Calculate time difference in seconds
                time_diff = (current_time - last_update).total_seconds()
                
                # Check status based on time difference
                if time_diff <= ONLINE_THRESHOLD_SECONDS:
                    return "online", time_diff, last_update
                elif time_diff <= STALE_THRESHOLD_SECONDS:
                    return "recent", time_diff, last_update
                elif time_diff <= OFFLINE_THRESHOLD_SECONDS:
                    return "stale", time_diff, last_update
                else:
                    return "offline", time_diff, last_update
            
            return "offline", OFFLINE_THRESHOLD_SECONDS, None
        else:
            return "offline", OFFLINE_THRESHOLD_SECONDS, None
            
    except Exception as e:
        return "offline", OFFLINE_THRESHOLD_SECONDS, None

# -------------------------
# Get Database Statistics
# -------------------------
def get_db_statistics():
    """Get statistics from database"""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            
            # Total records
            cursor.execute("SELECT COUNT(*) FROM network_metrics")
            total_records = cursor.fetchone()[0]
            
            # Congestion predictions count
            cursor.execute("SELECT COUNT(*) FROM network_metrics WHERE congestion_prediction = 1")
            congestion_count = cursor.fetchone()[0]
            
            # Average metrics
            cursor.execute("""
                SELECT AVG(latency), AVG(packet_loss), AVG(bandwidth), AVG(devices)
                FROM network_metrics
            """)
            avg_data = cursor.fetchone()
            
            # Latest record timestamp
            cursor.execute("SELECT MAX(timestamp) FROM network_metrics")
            latest_timestamp = cursor.fetchone()[0]
            
            cursor.close()
            connection.close()
            
            # Convert to Python native types
            return {
                'total_records': int(total_records) if total_records else 0,
                'congestion_count': int(congestion_count) if congestion_count else 0,
                'avg_latency': float(avg_data[0]) if avg_data[0] else 0.0,
                'avg_packet_loss': float(avg_data[1]) if avg_data[1] else 0.0,
                'avg_bandwidth': float(avg_data[2]) if avg_data[2] else 0.0,
                'avg_devices': float(avg_data[3]) if avg_data[3] else 0.0,
                'latest_timestamp': latest_timestamp
            }
        except Error as e:
            return {}
    return {}

# -------------------------
# Load Historical Data
# -------------------------
@st.cache_data(ttl=60)
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
            return df
        except Error as e:
            return pd.DataFrame()
    return pd.DataFrame()

# -------------------------
# Load Recommendations History
# -------------------------
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
# Enhanced Custom CSS with Better Visibility
# -------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
    
    /* Main background with dark gradient for better contrast */
    .stApp {
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%);
        font-family: 'Inter', sans-serif;
    }
    
    /* Main header with glassmorphism effect */
    .main-header {
        background: linear-gradient(135deg, rgba(102, 126, 234, 0.9) 0%, rgba(118, 75, 162, 0.9) 100%);
        backdrop-filter: blur(10px);
        padding: 2rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 30px rgba(0,0,0,0.2);
        border: 1px solid rgba(255,255,255,0.2);
    }
    
    .main-title {
        font-size: 3rem;
        font-weight: 700;
        background: linear-gradient(135deg, #fff 0%, #e0e0e0 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
    }
    
    .subtitle {
        color: rgba(255,255,255,0.95);
        font-size: 1.1rem;
    }
    
    /* Metric cards with dark background and light text */
    .metric-card {
        background: rgba(30, 30, 50, 0.95);
        border-radius: 20px;
        padding: 1.5rem;
        box-shadow: 0 8px 20px rgba(0,0,0,0.2);
        transition: transform 0.3s ease;
        border: 1px solid rgba(102, 126, 234, 0.3);
        backdrop-filter: blur(5px);
    }
    
    .metric-card:hover {
        transform: translateY(-5px);
        border-color: rgba(102, 126, 234, 0.6);
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
        color: #a0aec0;
        font-size: 0.8rem;
    }
    
    /* Prediction cards */
    .prediction-risk {
        background: linear-gradient(135deg, #dc2626 0%, #b91c1c 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 15px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(220, 38, 38, 0.3);
    }
    
    .prediction-normal {
        background: linear-gradient(135deg, #059669 0%, #047857 100%);
        color: white;
        padding: 1.5rem;
        border-radius: 15px;
        text-align: center;
        box-shadow: 0 4px 15px rgba(5, 150, 105, 0.3);
    }
    
    .prediction-title {
        font-size: 1.3rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    
    /* Status cards with dark backgrounds */
    .status-online {
        background: rgba(5, 150, 105, 0.2);
        border-radius: 15px;
        padding: 1rem;
        margin: 1rem 0;
        border-left: 4px solid #059669;
        text-align: center;
        backdrop-filter: blur(5px);
        color: #ffffff;
    }
    
    .status-recent {
        background: rgba(59, 130, 246, 0.2);
        border-radius: 15px;
        padding: 1rem;
        margin: 1rem 0;
        border-left: 4px solid #3b82f6;
        text-align: center;
        backdrop-filter: blur(5px);
        color: #ffffff;
    }
    
    .status-stale {
        background: rgba(245, 158, 11, 0.2);
        border-radius: 15px;
        padding: 1rem;
        margin: 1rem 0;
        border-left: 4px solid #f59e0b;
        text-align: center;
        backdrop-filter: blur(5px);
        color: #ffffff;
    }
    
    .status-offline {
        background: rgba(220, 38, 38, 0.2);
        border-radius: 15px;
        padding: 1rem;
        margin: 1rem 0;
        border-left: 4px solid #dc2626;
        text-align: center;
        backdrop-filter: blur(5px);
        color: #ffffff;
    }
    
    /* Recommendation cards */
    .recommendation-card {
        background: rgba(45, 45, 65, 0.95);
        border-radius: 15px;
        padding: 1rem;
        margin: 0.5rem 0;
        border-left: 4px solid #667eea;
        backdrop-filter: blur(5px);
    }
    
    .recommendation-text {
        color: #e2e8f0;
        font-size: 0.95rem;
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: rgba(30, 30, 50, 0.5);
        border-radius: 12px;
        padding: 0.5rem;
    }
    
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 0.5rem 1rem;
        color: #e2e8f0;
        font-weight: 500;
    }
    
    .stTabs [aria-selected="true"] {
        background-color: #667eea;
        color: white;
    }
    
    /* Dataframe styling */
    .stDataFrame {
        background: rgba(30, 30, 50, 0.8);
        border-radius: 12px;
        padding: 0.5rem;
    }
    
    .stDataFrame div[data-testid="stDataFrame"] {
        color: #e2e8f0;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #0f172a 100%);
        border-right: 1px solid rgba(102, 126, 234, 0.3);
    }
    
    [data-testid="stSidebar"] .stMarkdown {
        color: #e2e8f0;
    }
    
    /* Footer */
    .footer {
        text-align: center;
        padding: 2rem;
        color: rgba(255,255,255,0.6);
        font-size: 0.9rem;
    }
    
    /* Metric value colors */
    .metric-value-high {
        color: #f87171;
    }
    
    .metric-value-medium {
        color: #fbbf24;
    }
    
    .metric-value-low {
        color: #4ade80;
    }
    
    /* Button styling */
    .stButton button {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.5rem 1rem;
        font-weight: 500;
    }
    
    .stButton button:hover {
        transform: translateY(-2px);
        box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
    }
    
    /* Download button */
    .stDownloadButton button {
        background: linear-gradient(135deg, #059669 0%, #047857 100%);
    }
    
    /* Expander styling */
    .streamlit-expanderHeader {
        background: rgba(45, 45, 65, 0.8);
        border-radius: 10px;
        color: #e2e8f0;
    }
    
    .streamlit-expanderContent {
        background: rgba(30, 30, 50, 0.6);
        border-radius: 10px;
        color: #e2e8f0;
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

# -------------------------
# ThingSpeak Configuration
# -------------------------
CHANNEL_ID = "3272879"
READ_API_KEY = "DVHBFJFGLFO80Y2N"

# -------------------------
# Generate Recommendations
# -------------------------
def network_advice(devices, latency, packet_loss, bandwidth, prediction):
    advice = []
    severity_levels = []
    
    # Don't generate advice if all metrics are zero (offline state)
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
    """Format time difference in human readable format"""
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
# Get value color class
# -------------------------
def get_value_color(value, thresholds):
    """Return CSS class based on value thresholds"""
    if value > thresholds.get('high', float('inf')):
        return "metric-value-high"
    elif value > thresholds.get('medium', float('inf')):
        return "metric-value-medium"
    return "metric-value-low"

# -------------------------
# Main App
# -------------------------
def main():
    # Header
    st.markdown("""
    <div class="main-header">
        <div class="main-title">📡 AI Network Congestion Monitor</div>
        <div class="subtitle">Real-time network analytics with MySQL database integration | Live ThingSpeak Data</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 📊 System Status")
        
        # Check ThingSpeak device status
        status, time_diff, last_update = get_thingspeak_status()
        
        if status == "online":
            st.success(f"✅ ThingSpeak Device: ONLINE")
            if last_update:
                st.info(f"📡 Last update: {format_time_diff(time_diff)}")
        elif status == "recent":
            st.info(f"🟢 ThingSpeak Device: RECENT DATA")
            if last_update:
                st.info(f"📡 Last update: {format_time_diff(time_diff)}")
        elif status == "stale":
            st.warning(f"⚠️ ThingSpeak Device: STALE DATA")
            if last_update:
                st.warning(f"⏰ No data for: {format_time_diff(time_diff)}")
        else:
            st.error(f"❌ ThingSpeak Device: OFFLINE")
            if last_update:
                st.error(f"⏰ Last data: {format_time_diff(time_diff)}")
            else:
                st.error("⏰ No data received from device")
        
        # Check database connection
        db_connection = get_db_connection()
        if db_connection:
            st.success("✅ MySQL Database: Connected")
            db_connection.close()
        else:
            st.error("❌ MySQL Database: Disconnected")
        
        st.markdown("---")
        
        # Database statistics
        stats = get_db_statistics()
        if stats and stats['total_records'] > 0:
            st.markdown("### 📈 Database Statistics")
            st.metric("Total Records", stats['total_records'])
            st.metric("Congestion Events", stats['congestion_count'])
            st.metric("Avg Devices", f"{stats['avg_devices']:.1f}")
            st.metric("Avg Latency", f"{stats['avg_latency']:.1f} ms")
            st.metric("Avg Bandwidth", f"{stats['avg_bandwidth']:.1f} Mbps")
            st.metric("Avg Packet Loss", f"{stats['avg_packet_loss']:.2f}%")
            if stats['latest_timestamp']:
                st.info(f"📅 Latest data: {stats['latest_timestamp'].strftime('%Y-%m-%d %H:%M:%S')}")
        else:
            st.info("📭 No data in database yet. Waiting for fresh data...")
        
        st.markdown("---")
        st.markdown("### 🤖 AI Model")
        st.markdown("Machine Learning model analyzing network patterns to predict congestion.")
        st.markdown("**Features:** Devices, Latency, Packet Loss, Bandwidth")
        
        if st.button("🔄 Refresh Data"):
            st.cache_data.clear()
            st.rerun()
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📡 Live Monitor", "📊 Historical Data", "💡 Recommendations", "📝 System Logs"])
    
    with tab1:
        # Live monitoring with auto-refresh
        placeholder = st.empty()
        
        # Auto-refresh loop
        refresh_count = 0
        
        while True:
            with placeholder.container():
                # Fetch data from ThingSpeak with timestamp
                devices, latency, packet_loss, bandwidth, time_diff, last_update, data_status = fetch_thingspeak_data()
                
                # Determine if data is usable (online or recent)
                data_usable = data_status in ["online", "recent"] and not (devices == 0 and latency == 0 and packet_loss == 0 and bandwidth == 0)
                
                # Display status message based on data freshness
                if data_status == "online":
                    st.markdown(f"""
                    <div class="status-online">
                        <strong>✅ DEVICE ONLINE - RECEIVING LIVE DATA</strong><br>
                        Data received {format_time_diff(time_diff)}<br>
                        <small>Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'Unknown'} UTC</small>
                    </div>
                    """, unsafe_allow_html=True)
                elif data_status == "recent":
                    st.markdown(f"""
                    <div class="status-recent">
                        <strong>🟢 DEVICE RECENT - DATA AVAILABLE</strong><br>
                        Data received {format_time_diff(time_diff)}<br>
                        <small>Last update: {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'Unknown'} UTC</small>
                    </div>
                    """, unsafe_allow_html=True)
                elif data_status == "stale":
                    st.markdown(f"""
                    <div class="status-stale">
                        <strong>⚠️ STALE DATA - DEVICE MAY BE OFFLINE</strong><br>
                        No data received for {format_time_diff(time_diff)}<br>
                        <small>Last data: {last_update.strftime('%Y-%m-%d %H:%M:%S') if last_update else 'Unknown'} UTC</small>
                    </div>
                    """, unsafe_allow_html=True)
                else:  # offline
                    st.markdown(f"""
                    <div class="status-offline">
                        <strong>❌ DEVICE OFFLINE - NO DATA RECEIVED</strong><br>
                        {f'Last data received {format_time_diff(time_diff)}' if last_update else 'No data ever received'}<br>
                        <small>Waiting for device to come online...</small>
                    </div>
                    """, unsafe_allow_html=True)
                
                st.markdown(f"""
                <div style="text-align: right; color: rgba(255,255,255,0.7); margin-bottom: 1rem;">
                    Dashboard updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
                </div>
                """, unsafe_allow_html=True)
                
                # Display metrics
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    device_color = get_value_color(devices if data_usable else 0, {'high': 15, 'medium': 10})
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">📱 Active Devices</div>
                        <div class="metric-value {device_color if data_usable else 'metric-value-low'}">{devices if data_usable else 0}</div>
                        <div class="metric-unit">connected devices</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col2:
                    display_latency = latency if data_usable else 0
                    latency_color = get_value_color(display_latency, {'high': 100, 'medium': 50})
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">⏱️ Network Latency</div>
                        <div class="metric-value {latency_color}">{display_latency:.1f}</div>
                        <div class="metric-unit">milliseconds</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col3:
                    display_loss = packet_loss if data_usable else 0
                    loss_color = get_value_color(display_loss, {'high': 2, 'medium': 1})
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">📉 Packet Loss</div>
                        <div class="metric-value {loss_color}">{display_loss:.2f}</div>
                        <div class="metric-unit">percentage</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                with col4:
                    display_bandwidth = bandwidth if data_usable else 0
                    bw_color = get_value_color(display_bandwidth, {'high': 50, 'medium': 100, 'reverse': True})
                    # Reverse color logic for bandwidth (lower is worse)
                    if display_bandwidth < 50:
                        bw_color = "metric-value-high"
                    elif display_bandwidth < 100:
                        bw_color = "metric-value-medium"
                    else:
                        bw_color = "metric-value-low"
                    st.markdown(f"""
                    <div class="metric-card">
                        <div class="metric-label">🌐 Bandwidth</div>
                        <div class="metric-value {bw_color}">{display_bandwidth:.1f}</div>
                        <div class="metric-unit">Mbps</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Predict (only if data is usable)
                if data_usable:
                    prediction = predict_network(devices, latency, packet_loss, bandwidth)
                else:
                    prediction = 0
                
                # Save to database only if data is fresh and every 5th refresh
                refresh_count += 1
                if data_usable and refresh_count % 5 == 0 and time_diff <= STALE_THRESHOLD_SECONDS:
                    if save_to_database(devices, latency, packet_loss, bandwidth, prediction, time_diff):
                        st.toast("✅ Fresh data saved to database!", icon="💾")
                elif not data_usable and refresh_count % 10 == 0:
                    if data_status == "stale":
                        st.toast(f"⚠️ Stale data detected - Last update {format_time_diff(time_diff)}", icon="⚠️")
                    elif data_status == "offline":
                        st.toast("❌ Device offline - No data to save", icon="❌")
                
                # Display prediction
                st.markdown("---")
                st.markdown("### 🔮 AI Prediction")
                
                if not data_usable:
                    if data_status == "stale":
                        st.markdown(f"""
                        <div class="status-stale">
                            <div class="prediction-title">⚠️ PREDICTION UNAVAILABLE - STALE DATA</div>
                            <div>Waiting for fresh data from monitoring device...<br>
                            <small>Last data received: {format_time_diff(time_diff)}</small></div>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.markdown("""
                        <div class="status-offline">
                            <div class="prediction-title">⚠️ NO DATA AVAILABLE</div>
                            <div>Waiting for network monitoring device to come online...</div>
                        </div>
                        """, unsafe_allow_html=True)
                elif prediction == 1:
                    st.markdown("""
                    <div class="prediction-risk">
                        <div class="prediction-title">🚨 NETWORK CONGESTION RISK DETECTED</div>
                        <div>AI model predicts high probability of network congestion. Immediate attention recommended.</div>
                    </div>
                    """, unsafe_allow_html=True)
                else:
                    st.markdown("""
                    <div class="prediction-normal">
                        <div class="prediction-title">✅ NETWORK OPERATING NORMALLY</div>
                        <div>AI model indicates stable network conditions. No immediate action required.</div>
                    </div>
                    """, unsafe_allow_html=True)
                
                # Recommendations
                st.markdown("### 💡 IT Recommendations")
                display_devices = devices if data_usable else 0
                display_latency = latency if data_usable else 0
                display_packet_loss = packet_loss if data_usable else 0
                display_bandwidth = bandwidth if data_usable else 0
                
                advice_list, severity_levels = network_advice(display_devices, display_latency, 
                                                             display_packet_loss, display_bandwidth, prediction)
                
                for advice, severity in zip(advice_list, severity_levels):
                    st.markdown(f"""
                    <div class="recommendation-card">
                        <div class="recommendation-text">{advice}</div>
                    </div>
                    """, unsafe_allow_html=True)
            
            time.sleep(5)
    
    with tab2:
        st.markdown("### 📊 Historical Network Data")
        
        # Load historical data
        historical_df = load_historical_data(200)
        
        if not historical_df.empty:
            # Display summary statistics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Records", len(historical_df))
            with col2:
                congestion_pct = (historical_df['congestion_prediction'].sum() / len(historical_df)) * 100
                st.metric("Congestion Rate", f"{congestion_pct:.1f}%")
            with col3:
                st.metric("Avg Devices", f"{historical_df['devices'].mean():.1f}")
            with col4:
                st.metric("Data Range", f"{historical_df['timestamp'].min().strftime('%m/%d')} - {historical_df['timestamp'].max().strftime('%m/%d')}")
            
            # Filters
            col1, col2, col3 = st.columns(3)
            with col1:
                date_range = st.date_input("Select Date Range", 
                                           value=[historical_df['timestamp'].min().date(), historical_df['timestamp'].max().date()])
            with col2:
                show_congestion_only = st.checkbox("Show only congestion events")
            with col3:
                metric_to_plot = st.selectbox("Select Metric", ["latency", "bandwidth", "packet_loss", "devices"])
            
            # Apply filters
            df_filtered = historical_df.copy()
            if len(date_range) == 2:
                start_date, end_date = date_range
                df_filtered = df_filtered[(df_filtered['timestamp'].dt.date >= start_date) & 
                                          (df_filtered['timestamp'].dt.date <= end_date)]
            if show_congestion_only:
                df_filtered = df_filtered[df_filtered['congestion_prediction'] == 1]
            
            if not df_filtered.empty:
                # Display metrics over time
                fig = go.Figure()
                
                if metric_to_plot == "latency":
                    fig.add_trace(go.Scatter(x=df_filtered['timestamp'], y=df_filtered['latency'], 
                                             mode='lines+markers', name='Latency (ms)',
                                             line=dict(color='#f87171', width=2),
                                             marker=dict(size=6, color='#f87171')))
                    fig.update_layout(yaxis_title="Latency (ms)")
                elif metric_to_plot == "bandwidth":
                    fig.add_trace(go.Scatter(x=df_filtered['timestamp'], y=df_filtered['bandwidth'], 
                                             mode='lines+markers', name='Bandwidth (Mbps)',
                                             line=dict(color='#4ade80', width=2),
                                             marker=dict(size=6, color='#4ade80')))
                    fig.update_layout(yaxis_title="Bandwidth (Mbps)")
                elif metric_to_plot == "packet_loss":
                    fig.add_trace(go.Scatter(x=df_filtered['timestamp'], y=df_filtered['packet_loss'], 
                                             mode='lines+markers', name='Packet Loss (%)',
                                             line=dict(color='#fbbf24', width=2),
                                             marker=dict(size=6, color='#fbbf24')))
                    fig.update_layout(yaxis_title="Packet Loss (%)")
                else:
                    fig.add_trace(go.Scatter(x=df_filtered['timestamp'], y=df_filtered['devices'], 
                                             mode='lines+markers', name='Active Devices',
                                             line=dict(color='#a78bfa', width=2),
                                             marker=dict(size=6, color='#a78bfa')))
                    fig.update_layout(yaxis_title="Active Devices")
                
                # Add congestion markers
                congestion_points = df_filtered[df_filtered['congestion_prediction'] == 1]
                if not congestion_points.empty:
                    fig.add_trace(go.Scatter(x=congestion_points['timestamp'], 
                                            y=congestion_points[metric_to_plot],
                                            mode='markers', name='Congestion Event',
                                            marker=dict(size=12, color='#dc2626', symbol='x')))
                
                fig.update_layout(
                    title=f"{metric_to_plot.title()} Over Time",
                    xaxis_title="Time",
                    template="plotly_dark",
                    height=500,
                    hovermode='x unified'
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Correlation heatmap
                st.markdown("### 🔗 Correlation Analysis")
                corr_cols = ['devices', 'latency', 'packet_loss', 'bandwidth']
                corr_matrix = df_filtered[corr_cols].corr()
                
                fig_corr = go.Figure(data=go.Heatmap(
                    z=corr_matrix.values,
                    x=corr_matrix.columns,
                    y=corr_matrix.columns,
                    colorscale='RdBu',
                    zmin=-1, zmax=1,
                    text=corr_matrix.values.round(2),
                    texttemplate='%{text}',
                    textfont={"size": 12}
                ))
                fig_corr.update_layout(title="Correlation Between Network Metrics", height=500)
                st.plotly_chart(fig_corr, use_container_width=True)
                
                # Data table
                st.markdown("### 📋 Detailed Data Table")
                st.dataframe(df_filtered.sort_values('timestamp', ascending=False), use_container_width=True)
                
                # Download button
                csv = df_filtered.to_csv(index=False)
                st.download_button("📥 Download Data as CSV", csv, "network_metrics.csv", "text/csv")
            else:
                st.info("No data matches the selected filters.")
        else:
            st.info("📭 No historical data available yet. Data will appear as monitoring continues.")
    
    with tab3:
        st.markdown("### 💡 IT Recommendations History")
        st.markdown("AI-generated recommendations based on network conditions")
        
        recommendations_df = load_recommendations_history(100)
        
        if not recommendations_df.empty:
            # Summary stats
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Recommendations", len(recommendations_df))
            with col2:
                unique_recs = recommendations_df['recommendation'].nunique()
                st.metric("Unique Recommendations", unique_recs)
            with col3:
                st.metric("Most Recent", recommendations_df['created_at'].max().strftime('%Y-%m-%d %H:%M'))
            
            # Filter by congestion prediction
            show_congestion_only = st.checkbox("Show only recommendations from congestion events")
            if show_congestion_only:
                recommendations_df = recommendations_df[recommendations_df['congestion_prediction'] == 1]
            
            # Display recommendations in expandable cards
            for idx, row in recommendations_df.iterrows():
                with st.expander(f"📌 {row['created_at'].strftime('%Y-%m-%d %H:%M:%S')} - Devices: {row['devices']}"):
                    st.markdown(f"**💡 Recommendation:** {row['recommendation']}")
                    st.markdown("---")
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        st.metric("Devices", row['devices'])
                    with col2:
                        st.metric("Latency", f"{row['latency']:.1f} ms")
                    with col3:
                        st.metric("Packet Loss", f"{row['packet_loss']:.2f}%")
                    with col4:
                        st.metric("Bandwidth", f"{row['bandwidth']:.1f} Mbps")
                    
                    if row['congestion_prediction'] == 1:
                        st.error("⚠️ Congestion was predicted at this time")
                    else:
                        st.success("✅ No congestion predicted at this time")
        else:
            st.info("📭 No recommendations available yet. Recommendations will appear when network data is collected.")
    
    with tab4:
        st.markdown("### 📝 System Logs")
        st.markdown("System activity and data collection logs")
        
        logs_df = load_system_logs(200)
        
        if not logs_df.empty:
            # Filter controls
            col1, col2 = st.columns(2)
            with col1:
                log_type_filter = st.multiselect("Filter by Log Type", 
                                                 options=logs_df['log_type'].unique(),
                                                 default=logs_df['log_type'].unique())
            with col2:
                search_term = st.text_input("Search in Messages", placeholder="Enter search term...")
            
            # Apply filters
            filtered_logs = logs_df[logs_df['log_type'].isin(log_type_filter)]
            if search_term:
                filtered_logs = filtered_logs[filtered_logs['message'].str.contains(search_term, case=False, na=False)]
            
            # Display logs with color coding
            def color_log_row(row):
                if row['log_type'] == 'ERROR':
                    return ['background-color: rgba(220, 38, 38, 0.2)'] * len(row)
                elif row['log_type'] == 'WARNING':
                    return ['background-color: rgba(245, 158, 11, 0.2)'] * len(row)
                else:
                    return ['background-color: rgba(5, 150, 105, 0.2)'] * len(row)
            
            st.dataframe(
                filtered_logs[['created_at', 'log_type', 'message']].sort_values('created_at', ascending=False),
                use_container_width=True,
                column_config={
                    'created_at': st.column_config.DatetimeColumn('Timestamp', format='YYYY-MM-DD HH:mm:ss'),
                    'log_type': st.column_config.TextColumn('Type'),
                    'message': st.column_config.TextColumn('Message')
                }
            )
            
            # Clear logs button
            col1, col2, col3 = st.columns([1, 1, 2])
            with col1:
                if st.button("🗑️ Clear All Logs", type="secondary"):
                    connection = get_db_connection()
                    if connection:
                        cursor = connection.cursor()
                        cursor.execute("DELETE FROM system_logs")
                        connection.commit()
                        cursor.close()
                        connection.close()
                        st.success("Logs cleared!")
                        st.rerun()
            with col2:
                if st.button("📥 Export Logs"):
                    csv = filtered_logs.to_csv(index=False)
                    st.download_button("Download", csv, "system_logs.csv", "text/csv", key="export_logs_btn")
        else:
            st.info("📭 No logs available yet. System logs will appear as monitoring runs.")

    # Footer
    st.markdown("""
    <div class="footer">
        <p>AI Network Congestion Monitor | Powered by Machine Learning | Data from ThingSpeak Channel 3272879</p>
        <p>Real-time monitoring with MySQL database integration</p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
