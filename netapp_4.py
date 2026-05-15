# -*- coding: utf-8 -*-
"""
AI Network Monitor with Service Classification - AUTO REFRESH
Monitors Google and YouTube performance with combined speed metrics
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

# -------------------------
# Page Configuration
# -------------------------
st.set_page_config(
    page_title="AI Network Monitor - Google & YouTube",
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
AUTO_REFRESH_INTERVAL = 5  # Seconds between automatic updates

# Service thresholds
SERVICE_THRESHOLDS = {
    'google': {'latency_good': 50, 'latency_warning': 100, 'loss_good': 1, 'loss_warning': 2, 'bw_good': 50, 'bw_warning': 20},
    'youtube': {'latency_good': 70, 'latency_warning': 140, 'loss_good': 0.5, 'loss_warning': 1.5, 'bw_good': 75, 'bw_warning': 30}
}

# -------------------------
# Database Connection
# -------------------------
def get_db_connection():
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
        st.error(f"Database connection error: {e}")
        return None

# -------------------------
# Initialize Database Tables
# -------------------------
def initialize_database():
    """Create tables for classified metrics"""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            
            # Check if table exists and has correct columns
            cursor.execute("SHOW TABLES LIKE 'network_metrics'")
            table_exists = cursor.fetchone()
            
            if table_exists:
                # Check if network_score column exists
                cursor.execute("SHOW COLUMNS FROM network_metrics LIKE 'network_score'")
                column_exists = cursor.fetchone()
                
                if not column_exists:
                    # Drop and recreate tables with correct schema
                    cursor.execute("DROP TABLE IF EXISTS recommendations")
                    cursor.execute("DROP TABLE IF EXISTS network_metrics")
                    cursor.execute("DROP TABLE IF EXISTS system_logs")
                    table_exists = False
            
            if not table_exists:
                # Create new classified metrics table
                cursor.execute("""
                    CREATE TABLE network_metrics (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        timestamp DATETIME NOT NULL,
                        google_latency FLOAT,
                        google_packet_loss FLOAT,
                        google_bandwidth FLOAT,
                        google_quality_score INT,
                        youtube_latency FLOAT,
                        youtube_packet_loss FLOAT,
                        youtube_bandwidth FLOAT,
                        youtube_quality_score INT,
                        combined_speed FLOAT,
                        network_score FLOAT,
                        network_status VARCHAR(20),
                        congestion_prediction INT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                cursor.execute("""
                    CREATE TABLE recommendations (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        metric_id INT,
                        service VARCHAR(20),
                        recommendation TEXT,
                        severity VARCHAR(20),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (metric_id) REFERENCES network_metrics(id) ON DELETE CASCADE
                    )
                """)
                
                cursor.execute("""
                    CREATE TABLE system_logs (
                        id INT AUTO_INCREMENT PRIMARY KEY,
                        log_type VARCHAR(20),
                        message TEXT,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                connection.commit()
                add_log_entry('INFO', 'Database initialized with Google & YouTube classification schema')
            
            cursor.close()
            connection.close()
            return True
        except Error as e:
            st.error(f"Database initialization error: {e}")
            return False
    return False

# -------------------------
# Add Log Entry
# -------------------------
def add_log_entry(log_type, message):
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            query = "INSERT INTO system_logs (log_type, message) VALUES (%s, %s)"
            cursor.execute(query, (log_type, message))
            connection.commit()
            cursor.close()
            connection.close()
        except Error as e:
            pass

# -------------------------
# Save Classified Metrics
# -------------------------
def save_classified_metrics(data, prediction):
    """Save classified metrics to database"""
    connection = get_db_connection()
    if connection:
        try:
            cursor = connection.cursor()
            
            query = """
                INSERT INTO network_metrics 
                (timestamp, google_latency, google_packet_loss, google_bandwidth, google_quality_score,
                 youtube_latency, youtube_packet_loss, youtube_bandwidth, youtube_quality_score,
                 combined_speed, network_score, network_status, congestion_prediction)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            
            current_time = datetime.now()
            cursor.execute(query, (
                current_time,
                data['google_latency'], data['google_packet_loss'], data['google_bandwidth'], data['google_quality'],
                data['youtube_latency'], data['youtube_packet_loss'], data['youtube_bandwidth'], data['youtube_quality'],
                data['combined_speed'], data['network_score'], data['network_status'], prediction
            ))
            
            metric_id = cursor.lastrowid
            
            # Save recommendations
            recommendations = generate_recommendations(data)
            for rec in recommendations:
                rec_query = "INSERT INTO recommendations (metric_id, service, recommendation, severity) VALUES (%s, %s, %s, %s)"
                cursor.execute(rec_query, (metric_id, rec['service'], rec['message'], rec['severity']))
            
            connection.commit()
            cursor.close()
            connection.close()
            return True
        except Error as e:
            print(f"Error saving to database: {e}")
            return False
    return False

# -------------------------
# Fetch ThingSpeak Data (Updated for your channel)
# -------------------------
# REMOVED CACHE FOR REAL-TIME UPDATES
def fetch_thingspeak_data():
    """Fetch classified data from ThingSpeak - Real-time"""
    try:
        CHANNEL_ID = "3381959"
        READ_API_KEY = "8F8XKE0PABJFF6GG"
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
                    return None, time_diff, last_update, "offline"
                elif time_diff > STALE_THRESHOLD_SECONDS:
                    return None, time_diff, last_update, "stale"
            
            # Parse 8 fields from ThingSpeak
            google_latency = float(latest.get('field1', 0)) if latest.get('field1') else 0
            google_packet_loss = float(latest.get('field2', 0)) if latest.get('field2') else 0
            google_bandwidth = float(latest.get('field3', 0)) if latest.get('field3') else 0
            
            youtube_latency = float(latest.get('field4', 0)) if latest.get('field4') else 0
            youtube_packet_loss = float(latest.get('field5', 0)) if latest.get('field5') else 0
            youtube_bandwidth = float(latest.get('field6', 0)) if latest.get('field6') else 0
            
            combined_speed = float(latest.get('field7', 0)) if latest.get('field7') else 0
            network_score = float(latest.get('field8', 0)) if latest.get('field8') else 0
            
            # If no data received, return None
            if google_latency == 0 and youtube_latency == 0:
                return None, time_diff, last_update, "offline"
            
            # Calculate quality scores
            google_quality = calculate_quality_score(google_latency, google_packet_loss, google_bandwidth, 'google')
            youtube_quality = calculate_quality_score(youtube_latency, youtube_packet_loss, youtube_bandwidth, 'youtube')
            
            # Determine network status
            network_status = get_network_status(network_score)
            
            classified_data = {
                'google_latency': google_latency,
                'google_packet_loss': google_packet_loss,
                'google_bandwidth': google_bandwidth,
                'google_quality': google_quality,
                'youtube_latency': youtube_latency,
                'youtube_packet_loss': youtube_packet_loss,
                'youtube_bandwidth': youtube_bandwidth,
                'youtube_quality': youtube_quality,
                'combined_speed': combined_speed,
                'network_score': network_score,
                'network_status': network_status
            }
            
            status = "online" if time_diff <= ONLINE_THRESHOLD_SECONDS else "recent"
            return classified_data, time_diff, last_update, status
        else:
            return None, OFFLINE_THRESHOLD_SECONDS, None, "offline"
            
    except Exception as e:
        print(f"Error fetching ThingSpeak data: {e}")
        return None, OFFLINE_THRESHOLD_SECONDS, None, "offline"

def calculate_quality_score(latency, packet_loss, bandwidth, service):
    """Calculate quality score (0-100) for a service"""
    thresholds = SERVICE_THRESHOLDS.get(service, SERVICE_THRESHOLDS['google'])
    
    # Latency score (40% weight)
    if latency <= thresholds['latency_good']:
        latency_score = 100
    elif latency <= thresholds['latency_warning']:
        latency_score = 60 - (latency - thresholds['latency_good']) / (thresholds['latency_warning'] - thresholds['latency_good']) * 40
    else:
        latency_score = max(0, 20 - (latency - thresholds['latency_warning']) / 10)
    
    # Packet loss score (30% weight)
    if packet_loss <= thresholds['loss_good']:
        loss_score = 100
    elif packet_loss <= thresholds['loss_warning']:
        loss_score = 70 - (packet_loss - thresholds['loss_good']) / (thresholds['loss_warning'] - thresholds['loss_good']) * 30
    else:
        loss_score = max(0, 40 - (packet_loss - thresholds['loss_warning']) * 20)
    
    # Bandwidth score (30% weight)
    if bandwidth >= thresholds['bw_good']:
        bw_score = 100
    elif bandwidth >= thresholds['bw_warning']:
        bw_score = 60 + (bandwidth - thresholds['bw_warning']) / (thresholds['bw_good'] - thresholds['bw_warning']) * 40
    else:
        bw_score = max(0, (bandwidth / thresholds['bw_warning']) * 60)
    
    # Weighted score
    quality = (latency_score * 0.4) + (loss_score * 0.3) + (bw_score * 0.3)
    return int(quality)

def get_network_status(network_score):
    """Get network status based on score"""
    if network_score >= 80:
        return "EXCELLENT"
    elif network_score >= 60:
        return "GOOD"
    elif network_score >= 40:
        return "FAIR"
    elif network_score >= 20:
        return "POOR"
    else:
        return "CRITICAL"

def generate_recommendations(data):
    """Generate recommendations based on metrics"""
    recommendations = []
    
    # Google recommendations
    if data['google_quality'] < 40:
        recommendations.append({
            'service': 'Google',
            'message': f"🚨 CRITICAL: Google performance severely degraded (Score: {data['google_quality']}/100). Latency: {data['google_latency']:.1f}ms, Loss: {data['google_packet_loss']:.1f}%",
            'severity': 'critical'
        })
    elif data['google_quality'] < 60:
        recommendations.append({
            'service': 'Google',
            'message': f"⚠️ Google experiencing issues (Score: {data['google_quality']}/100). Check network connectivity to Google services.",
            'severity': 'warning'
        })
    elif data['google_quality'] >= 80:
        recommendations.append({
            'service': 'Google',
            'message': f"✅ Google performance excellent (Score: {data['google_quality']}/100). All metrics optimal.",
            'severity': 'good'
        })
    
    # YouTube recommendations
    if data['youtube_quality'] < 40:
        recommendations.append({
            'service': 'YouTube',
            'message': f"🚨 CRITICAL: YouTube performance severely degraded (Score: {data['youtube_quality']}/100). Video streaming may be affected.",
            'severity': 'critical'
        })
    elif data['youtube_quality'] < 60:
        recommendations.append({
            'service': 'YouTube',
            'message': f"⚠️ YouTube experiencing issues (Score: {data['youtube_quality']}/100). May affect video quality.",
            'severity': 'warning'
        })
    elif data['youtube_quality'] >= 80:
        recommendations.append({
            'service': 'YouTube',
            'message': f"✅ YouTube performance excellent (Score: {data['youtube_quality']}/100). HD streaming available.",
            'severity': 'good'
        })
    
    # Overall network recommendations
    if data['network_score'] < 50:
        recommendations.append({
            'service': 'Network',
            'message': f"🌐 Overall network health critical (Score: {data['network_score']:.0f}/100). Immediate investigation required.",
            'severity': 'critical'
        })
    elif data['combined_speed'] < 30:
        recommendations.append({
            'service': 'Network',
            'message': f"⚠️ Low combined bandwidth ({data['combined_speed']:.1f} Mbps). Consider upgrading internet plan.",
            'severity': 'warning'
        })
    
    return recommendations

# -------------------------
# Get ThingSpeak Status
# -------------------------
def get_thingspeak_status():
    """Get ThingSpeak connection status"""
    data, time_diff, last_update, status = fetch_thingspeak_data()
    return status, time_diff, last_update

# -------------------------
# Load Historical Data - REMOVED CACHE FOR REAL-TIME
# -------------------------
def load_historical_data(limit=100):
    """Load historical metrics from database"""
    connection = get_db_connection()
    if connection:
        try:
            query = """
                SELECT * FROM network_metrics
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
# Load Recommendations History - REMOVED CACHE FOR REAL-TIME
# -------------------------
def load_recommendations_history(limit=50):
    """Load recommendations history"""
    connection = get_db_connection()
    if connection:
        try:
            query = """
                SELECT r.*, n.timestamp, n.network_score, n.network_status
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
# Load System Logs - REMOVED CACHE FOR REAL-TIME
# -------------------------
def load_system_logs(limit=100):
    """Load system logs"""
    connection = get_db_connection()
    if connection:
        try:
            query = """
                SELECT * FROM system_logs
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
# Auto Refresh Component
# -------------------------
def auto_refresh():
    """Add auto-refresh functionality"""
    st.markdown(
        f"""
        <meta http-equiv="refresh" content="{AUTO_REFRESH_INTERVAL}">
        <div style="position: fixed; bottom: 20px; right: 20px; background: rgba(0,0,0,0.7); 
                    backdrop-filter: blur(10px); padding: 8px 15px; border-radius: 20px; 
                    font-size: 0.8rem; z-index: 999; border: 1px solid rgba(255,255,255,0.2);">
            🔄 Auto-refresh every {AUTO_REFRESH_INTERVAL}s
        </div>
        """,
        unsafe_allow_html=True
    )

# -------------------------
# Custom CSS
# -------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800&display=swap');
    
    .stApp {
        background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
        font-family: 'Inter', sans-serif;
    }
    
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
    
    .service-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        padding: 1.5rem;
        margin: 0.5rem 0;
        border: 1px solid rgba(255,255,255,0.2);
        transition: transform 0.3s ease;
    }
    
    .service-card:hover {
        transform: translateY(-3px);
    }
    
    .metric-card {
        background: linear-gradient(135deg, rgba(255,255,255,0.1) 0%, rgba(255,255,255,0.05) 100%);
        backdrop-filter: blur(10px);
        border-radius: 20px;
        padding: 1.5rem;
        text-align: center;
        border: 1px solid rgba(255,255,255,0.2);
        margin: 0.5rem 0;
    }
    
    .metric-label {
        font-size: 0.85rem;
        font-weight: 600;
        color: #a0aec0;
        text-transform: uppercase;
        letter-spacing: 1px;
    }
    
    .metric-value {
        font-size: 2rem;
        font-weight: 700;
        color: #ffffff;
    }
    
    .status-online, .status-recent, .status-stale, .status-offline {
        background: rgba(255,255,255,0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        padding: 1rem;
        margin: 1rem 0;
        text-align: center;
        border: 1px solid rgba(255,255,255,0.2);
    }
    
    .status-online { border-left: 4px solid #48bb78; }
    .status-recent { border-left: 4px solid #4299e1; }
    .status-stale { border-left: 4px solid #ed8936; }
    .status-offline { border-left: 4px solid #f56565; }
    
    .score-excellent { color: #48bb78; }
    .score-good { color: #4299e1; }
    .score-fair { color: #ed8936; }
    .score-poor { color: #f56565; }
    .score-critical { color: #dc2626; }
    
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
    }
    
    .stTabs [aria-selected="true"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%) !important;
        color: white !important;
    }
    
    .stTabs [data-baseweb="tab-panel"] {
        background: rgba(255,255,255,0.1);
        backdrop-filter: blur(10px);
        border-radius: 15px;
        padding: 20px;
        margin-top: 10px;
        border: 1px solid rgba(255,255,255,0.2);
    }
    
    .stAlert {
        background: rgba(0,0,0,0.5) !important;
        border: 1px solid rgba(255,255,255,0.2) !important;
    }
    
    /* Fade animation for updates */
    @keyframes fadeIn {
        from { opacity: 0; transform: translateY(-10px); }
        to { opacity: 1; transform: translateY(0); }
    }
    
    .live-update {
        animation: fadeIn 0.5s ease-out;
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
        return None

model = load_model()

# Initialize database
initialize_database()

# -------------------------
# Main App
# -------------------------
def main():
    # Add auto-refresh
    auto_refresh()
    
    # Header
    st.markdown("""
    <div class="main-header">
        <div class="main-title">📡 AI Network Monitor - Google & YouTube</div>
        <div class="subtitle">Real-time service classification with automatic updates (every 5 seconds)</div>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar
    with st.sidebar:
        st.markdown("### 📊 System Status")
        
        status, time_diff, last_update = get_thingspeak_status()
        
        if status == "online":
            st.success("✅ ThingSpeak: ONLINE")
            st.info(f"📡 Last update: {format_time_diff(time_diff)}")
        elif status == "recent":
            st.info("🟢 ThingSpeak: RECENT")
            st.info(f"📡 Last update: {format_time_diff(time_diff)}")
        elif status == "stale":
            st.warning("⚠️ ThingSpeak: STALE")
        else:
            st.error("❌ ThingSpeak: OFFLINE")
        
        st.markdown("---")
        
        db_connection = get_db_connection()
        if db_connection:
            st.success("✅ Database: Connected")
            db_connection.close()
        else:
            st.error("❌ Database: Disconnected")
        
        st.markdown("---")
        
        df_hist = load_historical_data(1000)
        if not df_hist.empty and 'network_score' in df_hist.columns:
            st.markdown("### 📈 Statistics")
            st.metric("Total Records", len(df_hist))
            st.metric("Avg Network Score", f"{df_hist['network_score'].mean():.0f}/100")
            st.metric("Avg Combined Speed", f"{df_hist['combined_speed'].mean():.1f} Mbps")
        elif not df_hist.empty:
            st.markdown("### 📈 Statistics")
            st.metric("Total Records", len(df_hist))
            st.info("Waiting for data with new schema...")
        
        st.markdown("---")
        st.info(f"🔄 Page auto-refreshes every {AUTO_REFRESH_INTERVAL} seconds")
    
    # Tabs
    tab1, tab2, tab3, tab4 = st.tabs(["📡 Live Monitor", "📊 Historical Data", "💡 Recommendations", "📝 System Logs"])
    
    # Tab 1: Live Monitor
    with tab1:
        data, time_diff, last_update, status = fetch_thingspeak_data()
        
        if data and data['network_score'] > 0:
            st.markdown('<div class="live-update">', unsafe_allow_html=True)
            st.markdown("### 🌐 Service Performance Dashboard")
            
            # Network Score Display
            if data['network_score'] >= 80:
                score_color = "score-excellent"
            elif data['network_score'] >= 60:
                score_color = "score-good"
            elif data['network_score'] >= 40:
                score_color = "score-fair"
            else:
                score_color = "score-poor"
                
            st.markdown(f"""
            <div class="service-card">
                <div style="text-align: center;">
                    <h2>🌐 NETWORK HEALTH SCORE</h2>
                    <div class="{score_color}" style="font-size: 4rem; font-weight: 800;">{data['network_score']:.0f}/100</div>
                    <div style="font-size: 1.2rem;">Status: {data['network_status']}</div>
                    <div style="font-size: 0.9rem; color: #a0aec0;">Combined Speed: {data['combined_speed']:.1f} Mbps</div>
                    <div style="font-size: 0.8rem; color: #a0aec0;">Last update: {format_time_diff(time_diff)}</div>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Two columns for services
            col1, col2 = st.columns(2)
            
            # Google
            with col1:
                if data['google_quality'] >= 80:
                    google_color = "score-excellent"
                elif data['google_quality'] >= 60:
                    google_color = "score-good"
                elif data['google_quality'] >= 40:
                    google_color = "score-fair"
                else:
                    google_color = "score-poor"
                    
                st.markdown(f"""
                <div class="service-card">
                    <h2 style="text-align: center; color: white;">🔍 Google</h2>
                    <div class="metric-card">
                        <div class="metric-label">Quality Score</div>
                        <div class="{google_color}" style="font-size: 2.5rem;">{data['google_quality']}/100</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Latency</div>
                        <div class="metric-value">{data['google_latency']:.1f} <span style="font-size: 1rem;">ms</span></div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Packet Loss</div>
                        <div class="metric-value">{data['google_packet_loss']:.2f}%</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Bandwidth</div>
                        <div class="metric-value">{data['google_bandwidth']:.1f} <span style="font-size: 1rem;">Mbps</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            # YouTube
            with col2:
                if data['youtube_quality'] >= 80:
                    youtube_color = "score-excellent"
                elif data['youtube_quality'] >= 60:
                    youtube_color = "score-good"
                elif data['youtube_quality'] >= 40:
                    youtube_color = "score-fair"
                else:
                    youtube_color = "score-poor"
                    
                st.markdown(f"""
                <div class="service-card">
                    <h2 style="text-align: center; color: white;">📺 YouTube</h2>
                    <div class="metric-card">
                        <div class="metric-label">Quality Score</div>
                        <div class="{youtube_color}" style="font-size: 2.5rem;">{data['youtube_quality']}/100</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Latency</div>
                        <div class="metric-value">{data['youtube_latency']:.1f} <span style="font-size: 1rem;">ms</span></div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Packet Loss</div>
                        <div class="metric-value">{data['youtube_packet_loss']:.2f}%</div>
                    </div>
                    <div class="metric-card">
                        <div class="metric-label">Bandwidth</div>
                        <div class="metric-value">{data['youtube_bandwidth']:.1f} <span style="font-size: 1rem;">Mbps</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            # Prediction (simple rule-based)
            prediction = 1 if data['network_score'] < 50 else 0
            
            if prediction == 1:
                st.markdown("""
                <div style="background: linear-gradient(135deg, #f56565 0%, #e53e3e 100%); padding: 1.5rem; border-radius: 15px; text-align: center; margin: 1rem 0;">
                    <strong style="font-size: 1.3rem;">🚨 NETWORK CONGESTION RISK DETECTED</strong><br>
                    Multiple services showing degraded performance. Immediate action recommended!
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown("""
                <div style="background: linear-gradient(135deg, #48bb78 0%, #38a169 100%); padding: 1.5rem; border-radius: 15px; text-align: center; margin: 1rem 0;">
                    <strong style="font-size: 1.3rem;">✅ NETWORK OPERATING NORMALLY</strong><br>
                    All services within acceptable parameters.
                </div>
                """, unsafe_allow_html=True)
            
            # Save to database
            save_classified_metrics(data, prediction)
            
            # Recommendations
            st.markdown("### 💡 Real-time Recommendations")
            recommendations = generate_recommendations(data)
            for rec in recommendations:
                if rec['severity'] == 'critical':
                    st.error(f"**{rec['service']}**: {rec['message']}")
                elif rec['severity'] == 'warning':
                    st.warning(f"**{rec['service']}**: {rec['message']}")
                else:
                    st.success(f"**{rec['service']}**: {rec['message']}")
            
            st.markdown('</div>', unsafe_allow_html=True)
        
        elif data and data['network_score'] == 0:
            st.warning("⚠️ Device is sending data but network score is 0. Make sure your ESP8266 is calculating metrics correctly.")
            st.info(f"Latest data - Google: {data['google_latency']:.1f}ms, YouTube: {data['youtube_latency']:.1f}ms")
        else:
            st.warning("⚠️ Waiting for data from ThingSpeak device...")
            st.info("Make sure your ESP8266 is running and sending data to ThingSpeak channel 3381959")
            
            # Show connection info
            with st.expander("📡 ThingSpeak Connection Info"):
                st.code(f"""
Channel ID: 3381959
Write API Key: 8F8XKE0PABJFF6GG

Expected fields:
- field1: Google Latency (ms)
- field2: Google Packet Loss (%)  
- field3: Google Bandwidth (Mbps)
- field4: YouTube Latency (ms)
- field5: YouTube Packet Loss (%)
- field6: YouTube Bandwidth (Mbps)
- field7: Combined Speed (Mbps)
- field8: Network Score (0-100)
                """)
    
    # Tab 2: Historical Data
    with tab2:
        st.markdown("### 📊 Historical Service Analytics")
        
        historical_df = load_historical_data(100)
        
        if not historical_df.empty:
            # Time series chart
            st.markdown("#### 📈 Network Metrics Over Time")
            
            if 'network_score' in historical_df.columns and 'combined_speed' in historical_df.columns:
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=historical_df['timestamp'], y=historical_df['network_score'],
                                        mode='lines+markers', name='Network Score',
                                        line=dict(color='#667eea', width=3),
                                        marker=dict(size=8, color='#667eea')))
                fig.add_trace(go.Scatter(x=historical_df['timestamp'], y=historical_df['combined_speed'],
                                        mode='lines+markers', name='Combined Speed (Mbps)',
                                        yaxis='y2',
                                        line=dict(color='#48bb78', width=3),
                                        marker=dict(size=8, color='#48bb78')))
                
                fig.update_layout(
                    title="Network Health & Combined Speed",
                    xaxis_title="Timestamp",
                    yaxis_title="Network Score (0-100)",
                    yaxis2=dict(title="Combined Speed (Mbps)", overlaying='y', side='right'),
                    template="plotly_dark",
                    height=500,
                    hovermode='x unified',
                    plot_bgcolor='rgba(0,0,0,0.3)',
                    paper_bgcolor='rgba(0,0,0,0)'
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # Service comparison
            st.markdown("#### 📊 Service Quality Comparison")
            
            fig2 = go.Figure()
            if 'google_quality_score' in historical_df.columns:
                fig2.add_trace(go.Scatter(x=historical_df['timestamp'], y=historical_df['google_quality_score'],
                                         mode='lines+markers', name='Google Quality',
                                         line=dict(color='#f56565', width=2)))
            if 'youtube_quality_score' in historical_df.columns:
                fig2.add_trace(go.Scatter(x=historical_df['timestamp'], y=historical_df['youtube_quality_score'],
                                         mode='lines+markers', name='YouTube Quality',
                                         line=dict(color='#4299e1', width=2)))
            
            fig2.update_layout(
                title="Service Quality Comparison",
                xaxis_title="Timestamp",
                yaxis_title="Quality Score (0-100)",
                template="plotly_dark",
                height=400,
                plot_bgcolor='rgba(0,0,0,0.3)',
                paper_bgcolor='rgba(0,0,0,0)'
            )
            st.plotly_chart(fig2, use_container_width=True)
            
            # Data table
            st.markdown("#### 📋 Detailed Data")
            display_cols = ['timestamp']
            if 'google_latency' in historical_df.columns:
                display_cols.extend(['google_latency', 'google_packet_loss', 'google_bandwidth'])
            if 'youtube_latency' in historical_df.columns:
                display_cols.extend(['youtube_latency', 'youtube_packet_loss', 'youtube_bandwidth'])
            if 'combined_speed' in historical_df.columns:
                display_cols.append('combined_speed')
            if 'network_score' in historical_df.columns:
                display_cols.append('network_score')
            if 'network_status' in historical_df.columns:
                display_cols.append('network_status')
            
            display_df = historical_df[display_cols].head(50)
            st.dataframe(display_df, use_container_width=True)
            
            # Download button
            csv = historical_df.to_csv(index=False)
            st.download_button("📥 Download CSV", csv, "network_metrics.csv", "text/csv")
        else:
            st.info("📭 No historical data available yet. Data will appear after first successful save.")
    
    # Tab 3: Recommendations
    with tab3:
        st.markdown("### 💡 Recommendations History")
        
        recommendations_df = load_recommendations_history(50)
        
        if not recommendations_df.empty:
            for idx, row in recommendations_df.iterrows():
                with st.expander(f"{row['created_at'].strftime('%Y-%m-%d %H:%M:%S')} - {row['service']}", expanded=False):
                    st.markdown(f"""
                    <div style="background: rgba(0,0,0,0.3); padding: 15px; border-radius: 10px;">
                        <p><strong>📋 Recommendation:</strong> {row['recommendation']}</p>
                        <hr>
                        <p><strong>📊 Network Score at time:</strong> {row['network_score']:.0f}/100 ({row['network_status']})</p>
                    </div>
                    """, unsafe_allow_html=True)
        else:
            st.info("📭 No recommendations available yet")
    
    # Tab 4: System Logs
    with tab4:
        st.markdown("### 📝 System Logs")
        
        logs_df = load_system_logs(100)
        
        if not logs_df.empty:
            for idx, row in logs_df.iterrows():
                if row['log_type'] == 'ERROR':
                    log_color = "#f56565"
                elif row['log_type'] == 'WARNING':
                    log_color = "#ed8936"
                else:
                    log_color = "#48bb78"
                    
                st.markdown(f"""
                <div style="background: rgba(0,0,0,0.3); border-left: 4px solid {log_color}; padding: 10px; margin: 5px 0; border-radius: 5px;">
                    <small style="color: #a0aec0;">{row['created_at'].strftime('%Y-%m-%d %H:%M:%S')}</small>
                    <strong style="color: {log_color};">[{row['log_type']}]</strong>
                    <span style="color: #e2e8f0;">{row['message']}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("📭 No logs available yet")

if __name__ == "__main__":
    main()