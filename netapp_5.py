# -*- coding: utf-8 -*-
"""
AI Network Monitor with MySQL Database Integration
Enhanced with Real-time Data Collection & Advanced AI Graphics
Created for Railway MySQL Database
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
import json
import random
from collections import deque
import warnings
warnings.filterwarnings('ignore')

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
DATA_COLLECTION_INTERVAL = 60  # 1 minute

# -------------------------
# Global Data Queue for Real-time Updates
# -------------------------
if 'data_history' not in st.session_state:
    st.session_state.data_history = deque(maxlen=100)
if 'last_collection_time' not in st.session_state:
    st.session_state.last_collection_time = None
if 'auto_refresh' not in st.session_state:
    st.session_state.auto_refresh = True

# -------------------------
# Database Connection Function (Railway MySQL)
# -------------------------
@st.cache_resource
def get_db_connection():
    """Create connection to Railway MySQL database"""
    try:
        connection = mysql.connector.connect(
            host="mysql.railway.internal",
            user="root",
            password="NQWyDcbHVmWuxWaEMnoKLfQHxYVxNFHo",
            database="railway",
            port=3306,
            connection_timeout=10,
            autocommit=True
        )
        return connection
    except Error as e:
        st.error(f"Database connection failed: {e}")
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
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_timestamp (timestamp),
                    INDEX idx_prediction (congestion_prediction)
                )
            """)
            
            # Create recommendations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS recommendations (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    metric_id INT,
                    recommendation TEXT,
                    severity VARCHAR(20),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (metric_id) REFERENCES network_metrics(id) ON DELETE CASCADE,
                    INDEX idx_severity (severity),
                    INDEX idx_created (created_at)
                )
            """)
            
            # Create system_logs table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS system_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    log_type VARCHAR(20),
                    message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_type (log_type),
                    INDEX idx_created (created_at)
                )
            """)
            
            # Create alerts table for real-time notifications
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    alert_type VARCHAR(50),
                    message TEXT,
                    severity VARCHAR(20),
                    is_read BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_read (is_read),
                    INDEX idx_severity (severity)
                )
            """)
            
            connection.commit()
            cursor.close()
            connection.close()
            return True
        except Error as e:
            st.error(f"Database initialization error: {e}")
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
            
            advice_list, severity_list = network_advice(devices, latency, packet_loss, bandwidth, prediction)
            
            for advice, severity in zip(advice_list, severity_list):
                rec_query = "INSERT INTO recommendations (metric_id, recommendation, severity) VALUES (%s, %s, %s)"
                cursor.execute(rec_query, (metric_id, advice, severity))
                
                # Create alert for critical issues
                if severity in ['critical', 'high']:
                    alert_query = "INSERT INTO alerts (alert_type, message, severity) VALUES (%s, %s, %s)"
                    cursor.execute(alert_query, ('NETWORK_ISSUE', advice[:255], severity))
            
            log_query = "INSERT INTO system_logs (log_type, message) VALUES (%s, %s)"
            log_message = f'Network metrics saved - Devices: {devices}, Latency: {latency:.1f}ms, Prediction: {prediction}'
            cursor.execute(log_query, ('INFO', log_message))
            
            connection.commit()
            cursor.close()
            connection.close()
            
            # Store in session state for real-time display
            st.session_state.data_history.append({
                'timestamp': current_time,
                'devices': devices,
                'latency': latency,
                'packet_loss': packet_loss,
                'bandwidth': bandwidth,
                'prediction': prediction
            })
            
            return True
        except Error as e:
            print(f"Database save error: {e}")
            return False
    return False

# -------------------------
# Predict Network Congestion
# -------------------------
def predict_network(devices, latency, packet_loss, bandwidth):
    """Predict network congestion using AI model"""
    devices = float(devices) if not isinstance(devices, (int, float)) else devices
    latency = float(latency)
    packet_loss = float(packet_loss)
    bandwidth = float(bandwidth)
    
    if model is None:
        # Demo mode prediction logic
        risk_score = (latency / 200) + (packet_loss / 5) + (50 / max(bandwidth, 1)) + (devices / 30)
        return 1 if risk_score > 0.5 else 0
    
    try:
        sample = np.array([[devices, latency, packet_loss, bandwidth]])
        prediction = model.predict(sample)[0]
        return int(prediction)
    except:
        return 0

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
        response = requests.get(url, timeout=10)
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
            else:
                time_diff = OFFLINE_THRESHOLD_SECONDS
                last_update = None
            
            field1 = latest.get('field1')
            field2 = latest.get('field2')
            field3 = latest.get('field3')
            field4 = latest.get('field4')
            
            if field1 is None or field2 is None or field3 is None or field4 is None:
                return 0, 0.0, 0.0, 0.0, time_diff, last_update, "offline"
            
            devices = int(float(field1)) if field1 else 0
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
        print(f"ThingSpeak fetch error: {e}")
        return 0, 0.0, 0.0, 0.0, OFFLINE_THRESHOLD_SECONDS, None, "offline"

# -------------------------
# Automatic Data Collection Thread
# -------------------------
def auto_collect_data():
    """Background thread to collect data every minute"""
    while True:
        try:
            devices, latency, packet_loss, bandwidth, time_diff, last_update, status = fetch_thingspeak_data()
            
            if status in ["online", "recent"] and not (devices == 0 and latency == 0):
                prediction = predict_network(devices, latency, packet_loss, bandwidth)
                save_to_database(devices, latency, packet_loss, bandwidth, prediction, time_diff)
                st.session_state.last_collection_time = datetime.now()
            
            # Wait for 60 seconds
            time.sleep(DATA_COLLECTION_INTERVAL)
        except Exception as e:
            print(f"Auto collection error: {e}")
            time.sleep(DATA_COLLECTION_INTERVAL)

# Start auto-collection thread
if 'collection_thread_started' not in st.session_state:
    collection_thread = threading.Thread(target=auto_collect_data, daemon=True)
    collection_thread.start()
    st.session_state.collection_thread_started = True

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
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT COUNT(*) as total FROM network_metrics")
            total_records = cursor.fetchone()['total']
            
            cursor.execute("SELECT COUNT(*) as total FROM network_metrics WHERE congestion_prediction = 1")
            congestion_count = cursor.fetchone()['total']
            
            cursor.execute("""
                SELECT 
                    AVG(latency) as avg_latency,
                    AVG(packet_loss) as avg_packet_loss,
                    AVG(bandwidth) as avg_bandwidth,
                    AVG(devices) as avg_devices,
                    MAX(latency) as max_latency,
                    MIN(bandwidth) as min_bandwidth
                FROM network_metrics
                WHERE timestamp >= NOW() - INTERVAL 24 HOUR
            """)
            avg_data = cursor.fetchone()
            
            cursor.execute("SELECT COUNT(*) as unread FROM alerts WHERE is_read = FALSE")
            unread_alerts = cursor.fetchone()['unread']
            
            cursor.close()
            connection.close()
            
            return {
                'total_records': int(total_records) if total_records else 0,
                'congestion_count': int(congestion_count) if congestion_count else 0,
                'avg_latency': float(avg_data['avg_latency']) if avg_data['avg_latency'] else 0.0,
                'avg_packet_loss': float(avg_data['avg_packet_loss']) if avg_data['avg_packet_loss'] else 0.0,
                'avg_bandwidth': float(avg_data['avg_bandwidth']) if avg_data['avg_bandwidth'] else 0.0,
                'avg_devices': float(avg_data['avg_devices']) if avg_data['avg_devices'] else 0.0,
                'max_latency': float(avg_data['max_latency']) if avg_data['max_latency'] else 0.0,
                'min_bandwidth': float(avg_data['min_bandwidth']) if avg_data['min_bandwidth'] else 0.0,
                'unread_alerts': int(unread_alerts)
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
                df = df.sort_values('timestamp')
            return df
        except Error as e:
            return pd.DataFrame()
    return pd.DataFrame()

# -------------------------
# Load Unread Alerts
# -------------------------
@st.cache_data(ttl=10)
def load_unread_alerts():
    """Load unread alerts from database"""
    connection = get_db_connection()
    if connection:
        try:
            query = """
                SELECT id, alert_type, message, severity, created_at
                FROM alerts
                WHERE is_read = FALSE
                ORDER BY created_at DESC
                LIMIT 10
            """
            df = pd.read_sql(query, connection)
            connection.close()
            return df
        except Error as e:
            return pd.DataFrame()
    return pd.DataFrame()

def mark_alert_read(alert_id):
    """Mark an alert as read"""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            cursor.execute("UPDATE alerts SET is_read = TRUE WHERE id = %s", (alert_id,))
            connection.commit()
            cursor.close()
            connection.close()
            st.cache_data.clear()
            return True
        except:
            return False
    return False

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
                SELECT r.id, r.recommendation, r.severity, r.created_at,
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
# Create Network Visualization
# -------------------------
def create_network_topology(devices, latency, packet_loss, bandwidth):
    """Create an interactive network topology visualization"""
    fig = go.Figure()
    
    # Node positions (circular layout)
    num_nodes = min(int(devices), 20) if devices > 0 else 5
    angles = np.linspace(0, 2*np.pi, num_nodes, endpoint=False)
    
    # Center node (router)
    router_x, router_y = 0, 0
    
    # Client nodes
    client_x = np.cos(angles) * 2
    client_y = np.sin(angles) * 2
    
    # Add router node
    fig.add_trace(go.Scatter(
        x=[router_x],
        y=[router_y],
        mode='markers+text',
        marker=dict(size=40, symbol='star', color='#f56565', 
                   line=dict(color='white', width=2)),
        text=['<b>ROUTER</b>'],
        textposition='bottom center',
        name='Router',
        hoverinfo='text',
        hovertext=f'Router<br>Latency: {latency:.1f}ms<br>Bandwidth: {bandwidth:.1f}Mbps'
    ))
    
    # Add client nodes
    colors = []
    sizes = []
    for i in range(num_nodes):
        if packet_loss > 2:
            colors.append('#f56565')
            sizes.append(25)
        elif latency > 100:
            colors.append('#ed8936')
            sizes.append(22)
        else:
            colors.append('#48bb78')
            sizes.append(20)
    
    fig.add_trace(go.Scatter(
        x=client_x,
        y=client_y,
        mode='markers+text',
        marker=dict(size=sizes, color=colors, 
                   line=dict(color='white', width=1.5)),
        text=[f'Device {i+1}' for i in range(num_nodes)],
        textposition='top center',
        name='Devices',
        hoverinfo='text',
        hovertext=[f'Device {i+1}<br>Status: {"⚠ Poor" if packet_loss > 2 else "✅ Good"}' 
                   for i in range(num_nodes)]
    ))
    
    # Add connection lines
    for i in range(num_nodes):
        fig.add_trace(go.Scatter(
            x=[router_x, client_x[i]],
            y=[router_y, client_y[i]],
            mode='lines',
            line=dict(color='#667eea', width=2, dash='solid'),
            showlegend=False,
            hoverinfo='none'
        ))
    
    fig.update_layout(
        title="<b>🌐 Network Topology Map</b>",
        showlegend=True,
        height=500,
        xaxis=dict(showgrid=False, zeroline=False, visible=False),
        yaxis=dict(showgrid=False, zeroline=False, visible=False),
        plot_bgcolor='rgba(0,0,0,0.3)',
        paper_bgcolor='rgba(0,0,0,0)',
        hovermode='closest'
    )
    
    return fig

def create_animated_gauge(value, title, min_val, max_val, threshold_high, threshold_medium):
    """Create an animated gauge chart"""
    color = '#48bb78' if value <= threshold_medium else '#ed8936' if value <= threshold_high else '#f56565'
    
    fig = go.Figure(go.Indicator(
        mode = "gauge+number+delta",
        value = value,
        title = {'text': title, 'font': {'color': 'white', 'size': 20}},
        delta = {'reference': threshold_medium},
        gauge = {
            'axis': {'range': [min_val, max_val], 'tickwidth': 1, 'tickcolor': "white"},
            'bar': {'color': color},
            'bgcolor': "rgba(0,0,0,0.5)",
            'borderwidth': 2,
            'bordercolor': "white",
            'steps': [
                {'range': [min_val, threshold_medium], 'color': 'rgba(72,187,120,0.3)'},
                {'range': [threshold_medium, threshold_high], 'color': 'rgba(237,137,54,0.3)'},
                {'range': [threshold_high, max_val], 'color': 'rgba(245,101,101,0.3)'}
            ],
            'threshold': {
                'line': {'color': "white", 'width': 4},
                'thickness': 0.75,
                'value': threshold_high
            }
        }
    ))
    
    fig.update_layout(
        height=250,
        paper_bgcolor='rgba(0,0,0,0)',
        font={'color': "white"}
    )
    
    return fig

# -------------------------
# Custom CSS - Enhanced AI Design
# -------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    /* Global Styles */
    .stApp {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
        font-family: 'Inter', sans-serif;
    }
    
    /* Animated Background */
    @keyframes gradientBG {
        0% { background-position: 0% 50%; }
        50% { background-position: 100% 50%; }
        100% { background-position: 0% 50%; }
    }
    
    /* Main Header */
    .main-header {
        background: linear-gradient(135deg, rgba(102,126,234,0.9) 0%, rgba(118,75,162,0.9) 100%);
        backdrop-filter: blur(10px);
        padding: 2rem;
        border-radius: 20px;
        margin-bottom: 2rem;
        box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        border: 1px solid rgba(255,255,255,0.2);
        animation: fadeInDown 0.8s ease-out;
    }
    
    @keyframes fadeInDown {
        from {
            opacity: 0;
            transform: translateY(-30px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    .main-title {
        font-size: 3rem;
        font-weight: 800;
        background: linear-gradient(135deg, #fff 0%, #e0e0e0 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.5rem;
        animation: pulse 2s infinite;
    }
    
    @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.9; }
    }
    
    .subtitle {
        color: rgba(255,255,255,0.9);
        font-size: 1.1rem;
    }
    
    /* Metric Cards with Animation */
    .metric-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        backdrop-filter: blur(10px);
        border-radius: 20px;
        padding: 1.5rem;
        box-shadow: 0 8px 20px rgba(0,0,0,0.2);
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        border: 1px solid rgba(255,255,255,0.2);
        animation: fadeInUp 0.6s ease-out;
        position: relative;
        overflow: hidden;
    }
    
    @keyframes fadeInUp {
        from {
            opacity: 0;
            transform: translateY(20px);
        }
        to {
            opacity: 1;
            transform: translateY(0);
        }
    }
    
    .metric-card::before {
        content: '';
        position: absolute;
        top: 0;
        left: -100%;
        width: 100%;
        height: 100%;
        background: linear-gradient(90deg, transparent, rgba(255,255,255,0.2), transparent);
        transition: left 0.5s;
    }
    
    .metric-card:hover::before {
        left: 100%;
    }
    
    .metric-card:hover {
        transform: translateY(-5px) scale(1.02);
        box-shadow: 0 15px 30px rgba(0,0,0,0.4);
        border: 1px solid rgba(255,255,255,0.4);
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
        font-size: 2.5rem;
        font-weight: 800;
        background: linear-gradient(135deg, #fff 0%, #e0e0e0 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 0.25rem;
    }
    
    .metric-unit {
        font-size: 0.8rem;
        color: #a0aec0;
    }
    
    /* AI Prediction Cards with Glow Effect */
    .prediction-risk {
        background: linear-gradient(135deg, #f56565 0%, #e53e3e 100%);
        animation: glowRed 2s infinite, slideIn 0.5s ease-out;
    }
    
    .prediction-normal {
        background: linear-gradient(135deg, #48bb78 0%, #38a169 100%);
        animation: glowGreen 2s infinite, slideIn 0.5s ease-out;
    }
    
    @keyframes glowRed {
        0%, 100% { box-shadow: 0 0 20px rgba(245,101,101,0.5); }
        50% { box-shadow: 0 0 40px rgba(245,101,101,0.8); }
    }
    
    @keyframes glowGreen {
        0%, 100% { box-shadow: 0 0 20px rgba(72,187,120,0.5); }
        50% { box-shadow: 0 0 40px rgba(72,187,120,0.8); }
    }
    
    @keyframes slideIn {
        from {
            opacity: 0;
            transform: translateX(-30px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }
    
    .prediction-risk, .prediction-normal {
        color: white;
        padding: 1.5rem;
        border-radius: 15px;
        text-align: center;
        margin: 1rem 0;
    }
    
    .prediction-title {
        font-size: 1.5rem;
        font-weight: 800;
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
        animation: fadeIn 0.5s ease-out;
    }
    
    @keyframes fadeIn {
        from { opacity: 0; }
        to { opacity: 1; }
    }
    
    .status-online {
        border-left: 4px solid #48bb78;
        animation: pulseGreen 2s infinite;
    }
    
    @keyframes pulseGreen {
        0%, 100% { border-left-color: #48bb78; }
        50% { border-left-color: #9ae6b4; }
    }
    
    .status-recent { border-left: 4px solid #4299e1; }
    .status-stale { border-left: 4px solid #ed8936; }
    .status-offline { border-left: 4px solid #f56565; }
    
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
        transform: translateY(-2px);
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
        box-shadow: 0 2px 10px rgba(102,126,234,0.3);
    }
    
    /* Alert Badge */
    .alert-badge {
        background: #f56565;
        color: white;
        border-radius: 50%;
        width: 20px;
        height: 20px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        font-weight: bold;
        margin-left: 5px;
        animation: bounce 1s infinite;
    }
    
    @keyframes bounce {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-3px); }
    }
    
    /* Recommendation Cards */
    .recommendation-card {
        background: rgba(0,0,0,0.3);
        border-radius: 15px;
        padding: 1rem;
        margin: 0.5rem 0;
        border-left: 4px solid;
        transition: all 0.3s ease;
        animation: slideInRight 0.5s ease-out;
    }
    
    @keyframes slideInRight {
        from {
            opacity: 0;
            transform: translateX(30px);
        }
        to {
            opacity: 1;
            transform: translateX(0);
        }
    }
    
    .recommendation-card:hover {
        background: rgba(0,0,0,0.5);
        transform: translateX(5px);
    }
    
    /* Loading Animation */
    .loading-spinner {
        width: 50px;
        height: 50px;
        border: 3px solid rgba(255,255,255,0.3);
        border-radius: 50%;
        border-top-color: #667eea;
        animation: spin 1s ease-in-out infinite;
        margin: 20px auto;
    }
    
    @keyframes spin {
        to { transform: rotate(360deg); }
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
    
    /* Real-time indicator */
    .real-time-indicator {
        display: inline-block;
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background-color: #48bb78;
        margin-right: 8px;
        animation: blink 1s infinite;
    }
    
    @keyframes blink {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.3; }
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
        st.warning("⚠ Model file not found. Using demo mode with advanced AI simulation.")
        return None

model = load_model()

# Initialize database tables
initialize_database()

# -------------------------
# Main App
# -------------------------
def main():
    # Header with animated elements
    st.markdown("""
    <div class="main-header">
        <div class="main-title">
            <span class="real-time-indicator"></span>
            📡 AI Network Congestion Monitor
        </div>
        <div class="subtitle">
            Real-time network analytics with advanced AI prediction • Auto-collection every minute • Railway MySQL integration
        </div>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 🤖 AI-Powered Dashboard")
        
        # Auto-refresh toggle
        col1, col2 = st.columns([3, 1])
        with col1:
            st.session_state.auto_refresh = st.checkbox("🔄 Auto-refresh", value=st.session_state.auto_refresh)
        with col2:
            if st.button("🔄", help="Refresh now"):
                st.cache_data.clear()
                st.rerun()
        
        # Last collection time
        if st.session_state.last_collection_time:
            st.info(f"📊 Last collection: {st.session_state.last_collection_time.strftime('%H:%M:%S')}")
        else:
            st.info("📊 Waiting for first data collection...")
        
        st.markdown("---")
        
        # Device status
        status, time_diff, last_update = get_thingspeak_status()
        
        if status == "online":
            st.success(f"✅ ThingSpeak: ONLINE")
            st.caption(f"📡 Update: {format_time_diff(time_diff)}")
        elif status == "recent":
            st.info(f"🟢 ThingSpeak: RECENT")
            st.caption(f"📡 Update: {format_time_diff(time_diff)}")
        elif status == "stale":
            st.warning(f"⚠️ ThingSpeak: STALE")
            st.caption(f"⏰ No data: {format_time_diff(time_diff)}")
        else:
            st.error(f"❌ ThingSpeak: OFFLINE")
        
        # Database status
        db_connection = get_db_connection()
        if db_connection:
            st.success("✅ Railway MySQL: Connected")
            db_connection.close()
        else:
            st.error("❌ Railway MySQL: Disconnected")
        
        st.markdown("---")
        
        # Statistics
        stats = get_db_statistics()
        if stats and stats['total_records'] > 0:
            st.markdown("### 📊 Database Stats")
            col1, col2 = st.columns(2)
            with col1:
                st.metric("Total Records", stats['total_records'])
                st.metric("Congestion Events", stats['congestion_count'])
            with col2:
                st.metric("Avg Latency", f"{stats['avg_latency']:.1f}ms")
                st.metric("Peak Latency", f"{stats['max_latency']:.1f}ms")
            
            # Unread alerts badge
            if stats['unread_alerts'] > 0:
                st.markdown(f"""
                <div style="background: #f56565; padding: 10px; border-radius: 10px; text-align: center; margin-top: 10px;">
                    <strong>🔔 {stats['unread_alerts']} New Alert{'s' if stats['unread_alerts'] != 1 else ''}</strong>
                </div>
                """, unsafe_allow_html=True)
        
        st.markdown("---")
        st.markdown("### 🧠 AI Model")
        st.markdown("""
        **Features:**
        - Device count analysis
        - Latency prediction
        - Packet loss detection
        - Bandwidth optimization
        - Real-time congestion forecasting
        """)
        
        if st.button("⚙️ Reset Dashboard"):
            st.cache_data.clear()
            st.rerun()
    
    # Tabs
    tab1, tab2, tab3, tab4, tab5 = st.tabs(["📡 Live Monitor", "🌐 Network Visualization", "📊 Historical Data", "💡 Recommendations", "📝 System Logs"])
    
    # Tab 1: Live Monitor
    with tab1:
        st.markdown("### 📡 Real-Time Network Monitoring")
        st.markdown("Live data feed with AI-powered analysis - Auto-updates every minute")
        
        # Fetch and display data
        devices, latency, packet_loss, bandwidth, time_diff, last_update, status = fetch_thingspeak_data()
        
        # Status display with animation
        if status == "online":
            st.markdown(f"""
            <div class="status-online">
                <strong>✅ DEVICE ONLINE - RECEIVING LIVE DATA</strong><br>
                <span class="real-time-indicator"></span> Data received {format_time_diff(time_diff)}<br>
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
        
        # Metrics with animated gauges
        data_valid = status in ["online", "recent"] and not (devices == 0 and latency == 0)
        
        col1, col2 = st.columns(2)
        
        with col1:
            if data_valid:
                st.plotly_chart(create_animated_gauge(latency, "Latency (ms)", 0, 200, 100, 50), 
                               use_container_width=True)
                st.plotly_chart(create_animated_gauge(packet_loss, "Packet Loss (%)", 0, 10, 2, 1), 
                               use_container_width=True)
            else:
                st.plotly_chart(create_animated_gauge(0, "Latency (ms)", 0, 200, 100, 50), 
                               use_container_width=True)
                st.plotly_chart(create_animated_gauge(0, "Packet Loss (%)", 0, 10, 2, 1), 
                               use_container_width=True)
        
        with col2:
            if data_valid:
                st.plotly_chart(create_animated_gauge(bandwidth, "Bandwidth (Mbps)", 0, 500, 100, 50), 
                               use_container_width=True)
                st.plotly_chart(create_animated_gauge(devices, "Connected Devices", 0, 50, 15, 10), 
                               use_container_width=True)
            else:
                st.plotly_chart(create_animated_gauge(0, "Bandwidth (Mbps)", 0, 500, 100, 50), 
                               use_container_width=True)
                st.plotly_chart(create_animated_gauge(0, "Connected Devices", 0, 50, 15, 10), 
                               use_container_width=True)
        
        # AI Prediction
        if data_valid:
            prediction = predict_network(devices, latency, packet_loss, bandwidth)
            
            if prediction == 1:
                st.markdown("""
                <div class="prediction-risk">
                    <div class="prediction-title">🚨 CRITICAL: NETWORK CONGESTION RISK DETECTED</div>
                    <div>🧠 AI model predicts high probability of network congestion. Immediate action recommended!</div>
                    <div style="margin-top: 10px; font-size: 0.9rem;">⚠️ High latency / packet loss detected</div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div class="prediction-normal">
                    <div class="prediction-title">✅ NETWORK OPERATING NORMALLY</div>
                    <div>🧠 AI model indicates stable network conditions. All systems operational.</div>
                    <div style="margin-top: 10px; font-size: 0.9rem;">📊 All metrics within optimal ranges</div>
                </div>
                """, unsafe_allow_html=True)
            
            # Save to database
            save_to_database(devices, latency, packet_loss, bandwidth, prediction, time_diff)
        else:
            prediction = 0
        
        # Recommendations
        st.markdown("### 💡 AI-Generated Recommendations")
        advice_list, _ = network_advice(
            devices if data_valid else 0,
            latency if data_valid else 0,
            packet_loss if data_valid else 0,
            bandwidth if data_valid else 0,
            prediction
        )
        
        for idx, advice in enumerate(advice_list):
            if "CRITICAL" in advice:
                st.error(f"🚨 {advice}")
            elif "⚠" in advice:
                st.warning(f"⚠️ {advice}")
            else:
                st.success(f"✅ {advice}")
        
        # Real-time data stream indicator
        if data_valid:
            st.markdown("---")
            st.markdown("### 📈 Real-time Data Stream")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Devices Trend", f"{devices} devices", 
                         delta=f"{devices - (st.session_state.data_history[-1]['devices'] if st.session_state.data_history else devices)}")
            with col2:
                st.metric("Latency Trend", f"{latency:.1f}ms",
                         delta=f"{(latency - (st.session_state.data_history[-1]['latency'] if st.session_state.data_history else latency)):.1f}")
            with col3:
                st.metric("Auto-collection", "Active", delta="Every 60 seconds")
    
    # Tab 2: Network Visualization
    with tab2:
        st.markdown("### 🌐 Interactive Network Visualization")
        st.markdown("AI-generated network topology map with real-time status")
        
        devices, latency, packet_loss, bandwidth, _, _, status = fetch_thingspeak_data()
        data_valid = status in ["online", "recent"] and not (devices == 0 and latency == 0)
        
        if data_valid:
            # Network topology
            fig = create_network_topology(devices, latency, packet_loss, bandwidth)
            st.plotly_chart(fig, use_container_width=True)
            
            # Performance heatmap
            st.markdown("#### 📊 Network Performance Heatmap")
            
            # Create sample data for heatmap
            time_slots = ['00:00', '04:00', '08:00', '12:00', '16:00', '20:00']
            metrics = ['Latency', 'Packet Loss', 'Bandwidth Usage', 'Device Activity']
            
            # Simulate performance data
            performance_data = np.array([
                [latency * (0.8 + 0.4 * np.random.random()) for _ in range(len(metrics))],
                [packet_loss * (0.7 + 0.6 * np.random.random()) for _ in range(len(metrics))],
                [bandwidth * (0.6 + 0.8 * np.random.random()) for _ in range(len(metrics))],
                [devices * (0.9 + 0.2 * np.random.random()) for _ in range(len(metrics))]
            ])
            
            fig_heatmap = go.Figure(data=go.Heatmap(
                z=performance_data,
                x=metrics,
                y=time_slots,
                colorscale='Viridis',
                text=performance_data.round(1),
                texttemplate='%{text}',
                textfont={"size": 10, "color": "white"}
            ))
            
            fig_heatmap.update_layout(
                title="<b>Network Performance Heatmap</b>",
                xaxis_title="<b>Metrics</b>",
                yaxis_title="<b>Time of Day</b>",
                height=400,
                plot_bgcolor='rgba(0,0,0,0.3)',
                paper_bgcolor='rgba(0,0,0,0)'
            )
            
            st.plotly_chart(fig_heatmap, use_container_width=True)
            
            # Traffic flow animation
            st.markdown("#### 🚦 Real-time Traffic Flow")
            
            # Create animated traffic flow
            frames = []
            for i in range(10):
                frame = go.Frame(
                    data=[
                        go.Scatter(
                            x=[0, 1, 2, 3, 4],
                            y=[latency * np.random.random() for _ in range(5)],
                            mode='lines+markers',
                            line=dict(width=3, color='#667eea'),
                            marker=dict(size=10)
                        )
                    ],
                    name=str(i)
                )
                frames.append(frame)
            
            fig_traffic = go.Figure(
                data=[
                    go.Scatter(
                        x=[0, 1, 2, 3, 4],
                        y=[0, 0, 0, 0, 0],
                        mode='lines+markers',
                        line=dict(width=3, color='#667eea'),
                        marker=dict(size=10)
                    )
                ],
                frames=frames
            )
            
            fig_traffic.update_layout(
                title="<b>Network Traffic Flow Simulation</b>",
                xaxis_title="<b>Network Segment</b>",
                yaxis_title="<b>Traffic Load</b>",
                height=400,
                updatemenus=[{
                    'type': 'buttons',
                    'showactive': False,
                    'buttons': [{
                        'label': 'Play',
                        'method': 'animate',
                        'args': [None, {'frame': {'duration': 500, 'redraw': True}, 'fromcurrent': True}]
                    }]
                }],
                plot_bgcolor='rgba(0,0,0,0.3)',
                paper_bgcolor='rgba(0,0,0,0)'
            )
            
            st.plotly_chart(fig_traffic, use_container_width=True)
            
        else:
            st.info("📭 Network visualization will appear when device data is available.")
    
    # Tab 3: Historical Data
    with tab3:
        st.markdown("### 📊 Historical Network Data Analysis")
        st.markdown("Analyze network performance trends and patterns over time")
        
        historical_df = load_historical_data(200)
        
        if not historical_df.empty:
            # Filters
            col1, col2, col3 = st.columns(3)
            with col1:
                show_congestion_only = st.checkbox("🔴 Show only congestion events", key="hist_congestion")
            with col2:
                days = st.slider("📅 Select days to show", 1, 30, 7)
                cutoff_date = datetime.now() - timedelta(days=days)
                filtered_df = historical_df[historical_df['timestamp'] >= cutoff_date]
            with col3:
                if st.button("🔄 Reset Filters"):
                    st.rerun()
            
            if show_congestion_only:
                filtered_df = filtered_df[filtered_df['congestion_prediction'] == 1]
            
            if not filtered_df.empty:
                # Metrics overview
                st.markdown("#### 📈 Performance Metrics Overview")
                col1, col2, col3, col4 = st.columns(4)
                with col1:
                    st.metric("Avg Latency", f"{filtered_df['latency'].mean():.1f} ms", 
                             delta=f"{filtered_df['latency'].mean() - filtered_df['latency'].median():.1f}")
                with col2:
                    st.metric("Avg Packet Loss", f"{filtered_df['packet_loss'].mean():.2f}%")
                with col3:
                    st.metric("Avg Bandwidth", f"{filtered_df['bandwidth'].mean():.1f} Mbps")
                with col4:
                    st.metric("Peak Devices", f"{filtered_df['devices'].max():.0f}")
                
                # Time series chart with area fill
                st.markdown("#### 📊 Network Metrics Timeline")
                fig = go.Figure()
                
                fig.add_trace(go.Scatter(
                    x=filtered_df['timestamp'], 
                    y=filtered_df['latency'], 
                    mode='lines', 
                    name='Latency (ms)',
                    fill='tozeroy',
                    line=dict(color='#f56565', width=3),
                    fillcolor='rgba(245,101,101,0.3)'
                ))
                
                fig.add_trace(go.Scatter(
                    x=filtered_df['timestamp'], 
                    y=filtered_df['bandwidth'], 
                    mode='lines', 
                    name='Bandwidth (Mbps)',
                    yaxis='y2',
                    line=dict(color='#48bb78', width=3)
                ))
                
                fig.add_trace(go.Scatter(
                    x=filtered_df['timestamp'], 
                    y=filtered_df['packet_loss'] * 10, 
                    mode='lines', 
                    name='Packet Loss (x10 %)',
                    line=dict(color='#4299e1', width=2, dash='dot')
                ))
                
                # Add congestion markers
                congestion_points = filtered_df[filtered_df['congestion_prediction'] == 1]
                if not congestion_points.empty:
                    fig.add_trace(go.Scatter(
                        x=congestion_points['timestamp'],
                        y=congestion_points['latency'],
                        mode='markers',
                        name='⚠️ Congestion Events',
                        marker=dict(symbol='x', size=12, color='#f56565'),
                        hovertemplate='<b>⚠️ Congestion Detected</b><br>Time: %{x}<br>Latency: %{y:.1f}ms<extra></extra>'
                    ))
                
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
                
                # Statistical analysis
                st.markdown("#### 📊 Statistical Analysis")
                col1, col2 = st.columns(2)
                
                with col1:
                    st.markdown("##### Distribution Analysis")
                    fig_hist = go.Figure()
                    fig_hist.add_trace(go.Histogram(
                        x=filtered_df['latency'],
                        nbinsx=20,
                        name='Latency Distribution',
                        marker_color='#667eea',
                        opacity=0.7
                    ))
                    fig_hist.update_layout(
                        title="<b>Latency Distribution</b>",
                        xaxis_title="Latency (ms)",
                        yaxis_title="Frequency",
                        height=300,
                        plot_bgcolor='rgba(0,0,0,0.3)',
                        paper_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig_hist, use_container_width=True)
                
                with col2:
                    st.markdown("##### Box Plot Analysis")
                    fig_box = go.Figure()
                    fig_box.add_trace(go.Box(
                        y=filtered_df['latency'],
                        name='Latency',
                        marker_color='#f56565',
                        boxmean='sd'
                    ))
                    fig_box.add_trace(go.Box(
                        y=filtered_df['bandwidth'],
                        name='Bandwidth',
                        marker_color='#48bb78',
                        boxmean='sd'
                    ))
                    fig_box.update_layout(
                        title="<b>Metrics Distribution (Box Plot)</b>",
                        yaxis_title="Value",
                        height=300,
                        plot_bgcolor='rgba(0,0,0,0.3)',
                        paper_bgcolor='rgba(0,0,0,0)'
                    )
                    st.plotly_chart(fig_box, use_container_width=True)
                
                # Data table
                st.markdown("#### 📋 Detailed Data Table")
                st.dataframe(filtered_df, use_container_width=True, height=400)
                
                # Download button
                csv = filtered_df.to_csv(index=False)
                st.download_button("📥 Download Data as CSV", csv, "network_metrics.csv", "text/csv")
            else:
                st.info("ℹ️ No data matches the selected filters.")
        else:
            st.info("📭 No historical data available yet. Data will appear as monitoring continues.")
    
    # Tab 4: Recommendations
    with tab4:
        st.markdown("### 💡 AI-Powered Recommendations History")
        st.markdown("Intelligent network optimization suggestions generated by AI")
        
        recommendations_df = load_recommendations_history(100)
        
        if not recommendations_df.empty:
            # Summary statistics
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("Total Recommendations", len(recommendations_df))
            with col2:
                critical_count = len(recommendations_df[recommendations_df['severity'] == 'critical'])
                st.metric("Critical Issues", critical_count, delta_color="inverse")
            with col3:
                high_count = len(recommendations_df[recommendations_df['severity'] == 'high'])
                st.metric("High Severity", high_count)
            with col4:
                unique_count = recommendations_df['recommendation'].nunique()
                st.metric("Unique Issues", unique_count)
            
            st.markdown("---")
            
            # Filter by severity
            severity_filter = st.multiselect(
                "Filter by Severity",
                options=['critical', 'high', 'medium', 'warning', 'good'],
                default=['critical', 'high', 'medium']
            )
            
            filtered_recs = recommendations_df[recommendations_df['severity'].isin(severity_filter)]
            
            # Display recommendations as cards
            for idx, row in filtered_recs.iterrows():
                severity_colors = {
                    'critical': '#dc2626',
                    'high': '#f56565',
                    'medium': '#ed8936',
                    'warning': '#ecc94b',
                    'good': '#48bb78'
                }
                border_color = severity_colors.get(row['severity'], '#667eea')
                
                with st.expander(f"{'🚨' if row['severity'] in ['critical', 'high'] else '💡'} {row['created_at'].strftime('%Y-%m-%d %H:%M:%S')} - {row['recommendation'][:60]}...", expanded=False):
                    st.markdown(f"""
                    <div class="recommendation-card" style="border-left-color: {border_color};">
                        <p style="color: #e2e8f0; font-size: 1rem;"><strong>📋 Recommendation:</strong> {row['recommendation']}</p>
                        <p style="color: #a0aec0; font-size: 0.85rem;"><strong>Severity:</strong> 
                            <span style="color: {border_color}; font-weight: bold;">{row['severity'].upper()}</span>
                        </p>
                        <hr style="margin: 10px 0; border-color: rgba(255,255,255,0.1);">
                        <p style="color: #e2e8f0;"><strong>📊 Network Metrics at Time:</strong></p>
                        <ul style="color: #cbd5e0;">
                            <li>🖥️ Connected Devices: {row['devices']}</li>
                            <li>⏱️ Latency: {row['latency']:.1f} ms</li>
                            <li>📉 Packet Loss: {row['packet_loss']:.2f}%</li>
                            <li>🌐 Bandwidth: {row['bandwidth']:.1f} Mbps</li>
                        </ul>
                        <p style="color: #a0aec0; font-size: 0.85rem;">📅 Generated: {row['created_at'].strftime('%Y-%m-%d %H:%M:%S')}</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("📭 No recommendations available yet. Recommendations will appear when network data is analyzed.")
    
    # Tab 5: System Logs
    with tab5:
        st.markdown("### 📝 System Audit Logs")
        st.markdown("Complete audit trail of system events and operations")
        
        # Check for unread alerts
        alerts_df = load_unread_alerts()
        if not alerts_df.empty:
            st.warning(f"🔔 You have {len(alerts_df)} unread alert(s)!")
            for _, alert in alerts_df.iterrows():
                with st.container():
                    col1, col2, col3 = st.columns([6, 1, 1])
                    with col1:
                        st.error(f"**{alert['alert_type']}** - {alert['message']}")
                    with col2:
                        if st.button("✓", key=f"read_{alert['id']}"):
                            mark_alert_read(alert['id'])
                            st.rerun()
                    with col3:
                        st.caption(alert['created_at'].strftime('%H:%M:%S'))
            st.markdown("---")
        
        logs_df = load_system_logs(200)
        
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
            
            # Search filter
            search_term = st.text_input("🔍 Search logs", placeholder="Enter search term...")
            
            # Filter logs
            if search_term:
                logs_df = logs_df[logs_df['message'].str.contains(search_term, case=False, na=False)]
            
            # Color code and display logs
            for idx, row in logs_df.iterrows():
                log_color = '#f56565' if row['log_type'] == 'ERROR' else '#ed8936' if row['log_type'] == 'WARNING' else '#48bb78'
                st.markdown(f"""
                <div style="background: rgba(0,0,0,0.3); border-left: 4px solid {log_color}; padding: 12px; margin: 8px 0; border-radius: 8px; transition: all 0.3s ease;">
                    <div style="display: flex; justify-content: space-between; align-items: center;">
                        <small style="color: #a0aec0;">{row['created_at'].strftime('%Y-%m-%d %H:%M:%S')}</small>
                        <strong style="color: {log_color};">[{row['log_type']}]</strong>
                    </div>
                    <div style="color: #e2e8f0; margin-top: 5px;">{row['message']}</div>
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
    
    # Auto-refresh logic
    if st.session_state.auto_refresh:
        time.sleep(60)
        st.rerun()

if __name__ == "__main__":
    main()