import os
import uuid
import hashlib
import datetime
import time
import requests
from flask import Flask, render_template, request, make_response, jsonify, redirect, url_for
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from models import Base, Event
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'super-secret-key-for-local-dev')

# --- Database Setup ---
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///local.db')
# SQLAlchemy 1.4+ requires postgresql:// instead of postgres://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Connect args needed for some serverless postgres (like Neon or Supabase sometimes)
connect_args = {}
if 'sqlite' in DATABASE_URL:
    connect_args = {'check_same_thread': False}

engine = create_engine(DATABASE_URL, connect_args=connect_args)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)

# --- Meta CAPI Configuration ---
META_ACCESS_TOKEN = os.environ.get('META_ACCESS_TOKEN')
META_PIXEL_ID = os.environ.get('META_PIXEL_ID')

def hash_data(data):
    if not data:
        return None
    return hashlib.sha256(data.strip().lower().encode('utf-8')).hexdigest()

def send_meta_capi_event(event_name, event_source_url, event_time, user_data=None):
    """
    Sends an event to Meta Conversions API.
    """
    if not META_ACCESS_TOKEN or not META_PIXEL_ID:
        print("Meta CAPI not configured. Skipping server-side event.")
        return

    url = f"https://graph.facebook.com/v18.0/{META_PIXEL_ID}/events"
    
    # Construct base user_data
    capi_user_data = {
        "client_ip_address": user_data.get('ip_address'),
        "client_user_agent": user_data.get('user_agent'),
    }
    
    if user_data.get('fbp'):
        capi_user_data["fbp"] = user_data.get('fbp')
    if user_data.get('fbc'):
        capi_user_data["fbc"] = user_data.get('fbc')
        
    # Example Custom Data
    custom_data = {}
    if event_name == 'Lead':
        custom_data['currency'] = 'USD'
        custom_data['value'] = 0.00
        
    payload = {
        "data": [
            {
                "event_name": event_name,
                "event_time": int(event_time.timestamp()),
                "action_source": "website",
                "event_source_url": event_source_url,
                "user_data": capi_user_data,
                "custom_data": custom_data
            }
        ],
        "access_token": META_ACCESS_TOKEN
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
        print(f"Meta CAPI Event '{event_name}' sent successfully.")
    except Exception as e:
        print(f"Failed to send Meta CAPI event: {e}")

# --- Helper Methods ---

def get_or_set_variant(request_obj):
    """Checks for an existing variant cookie, or assigns one randomly."""
    variant = request_obj.cookies.get('ab_variant')
    if not variant:
        # Simple 50/50 split based on random UUID
        variant = 'A' if int(uuid.uuid4().hex[0], 16) % 2 == 0 else 'B'
    return variant

def extract_utms(request_obj):
    return {
        'utm_source': request_obj.args.get('utm_source'),
        'utm_medium': request_obj.args.get('utm_medium'),
        'utm_campaign': request_obj.args.get('utm_campaign')
    }

def record_db_event(event_name, variant, utms, request_obj, custom_fbp=None, custom_fbc=None):
    db_session = SessionLocal()
    try:
        new_event = Event(
            event_name=event_name,
            variant=variant,
            utm_source=utms.get('utm_source'),
            utm_medium=utms.get('utm_medium'),
            utm_campaign=utms.get('utm_campaign'),
            ip_address=request_obj.remote_addr,
            user_agent=request_obj.user_agent.string,
            fbp=custom_fbp or request_obj.cookies.get('_fbp'),
            fbc=custom_fbc or request_obj.cookies.get('_fbc'),
            timestamp=datetime.datetime.utcnow()
        )
        db_session.add(new_event)
        db_session.commit()
        return new_event
    except Exception as e:
        print(f"DB Error: {e}")
        db_session.rollback()
    finally:
        db_session.close()

# --- Routes ---

@app.route('/')
def index():
    variant = get_or_set_variant(request)
    utms = extract_utms(request)
    
    # Determine which template to render
    template_name = 'landing_a.html' if variant == 'A' else 'landing_b.html'
    
    # We delay the event recording to the frontend via JS so we can easily capture the _fbp/_fbc cookies 
    # that Meta's standard pixel generates on page load.
    
    resp = make_response(render_template(template_name, variant=variant, utms=utms, pixel_id=META_PIXEL_ID))
    
    # Set cookies if they don't exist (90 days expiry)
    if not request.cookies.get('ab_variant'):
        resp.set_cookie('ab_variant', variant, max_age=60*60*24*90)
    
    # Persist UTMs in cookies so they are available on the Thank You page
    for key, value in utms.items():
        if value:
            resp.set_cookie(key, value, max_age=60*60*24*90)
            
    return resp

@app.route('/thank-you')
def thank_you():
    variant = request.cookies.get('ab_variant', 'Unknown')
    utms = {
        'utm_source': request.cookies.get('utm_source'),
        'utm_medium': request.cookies.get('utm_medium'),
        'utm_campaign': request.cookies.get('utm_campaign')
    }
    
    return render_template('thank_you.html', variant=variant, utms=utms, pixel_id=META_PIXEL_ID)

@app.route('/api/record_event', methods=['POST'])
def api_record_event():
    data = request.json
    if not data or 'event_name' not in data:
        return jsonify({'error': 'event_name is required'}), 400
        
    event_name = data['event_name']
    
    # The frontend might explicitly send fbp/fbc if it just generated them
    custom_fbp = data.get('fbp')
    custom_fbc = data.get('fbc')
    
    variant = request.cookies.get('ab_variant', 'Unknown')
    utms = {
        'utm_source': request.cookies.get('utm_source'),
        'utm_medium': request.cookies.get('utm_medium'),
        'utm_campaign': request.cookies.get('utm_campaign')
    }

    # Record in DB
    event_record = record_db_event(event_name, variant, utms, request, custom_fbp, custom_fbc)
    
    # Trigger CAPI for specific conversion events
    if event_name in ['clickedctabutton', 'visitedThankYouPage', 'Lead']:
        # Map our internal event name to a Standard Meta Event if needed
        capi_event_name = 'Lead' if event_name == 'visitedThankYouPage' else event_name
        
        user_data = {
            'ip_address': request.remote_addr,
            'user_agent': request.user_agent.string,
            'fbp': custom_fbp or request.cookies.get('_fbp'),
            'fbc': custom_fbc or request.cookies.get('_fbc')
        }
        
        send_meta_capi_event(
            event_name=capi_event_name,
            event_source_url=request.referrer or request.url,
            event_time=datetime.datetime.utcnow(),
            user_data=user_data
        )

    return jsonify({'status': 'success'})

@app.route('/<page_name>')
def serve_static_page(page_name):
    # Security check to prevent directory traversal
    if ".." in page_name or "/" in page_name:
        return "Invalid page", 400
        
    try:
        if not page_name.endswith('.html'):
            page_name += '.html'
        # Doesn't pass variants or utms, serving the template purely as requested
        return render_template(page_name)
    except Exception:
        return "Page not found", 404

@app.route('/analytics')
def analyticsDashboard():
    db_session = SessionLocal()
    try:
        # Get total visitors per variant
        visitors_a = db_session.query(func.count(Event.id)).filter(Event.event_name == 'visitedLandingPage', Event.variant == 'A').scalar() or 0
        visitors_b = db_session.query(func.count(Event.id)).filter(Event.event_name == 'visitedLandingPage', Event.variant == 'B').scalar() or 0
        
        # Get CTA clicks
        clicks_a = db_session.query(func.count(Event.id)).filter(Event.event_name == 'clickedctabutton', Event.variant == 'A').scalar() or 0
        clicks_b = db_session.query(func.count(Event.id)).filter(Event.event_name == 'clickedctabutton', Event.variant == 'B').scalar() or 0
        
        # Get Conversions (Thank you page visits)
        conv_a = db_session.query(func.count(Event.id)).filter(Event.event_name == 'visitedThankYouPage', Event.variant == 'A').scalar() or 0
        conv_b = db_session.query(func.count(Event.id)).filter(Event.event_name == 'visitedThankYouPage', Event.variant == 'B').scalar() or 0
        
        # Calculate Rates
        ctr_a = round((clicks_a / visitors_a * 100) if visitors_a > 0 else 0, 2)
        ctr_b = round((clicks_b / visitors_b * 100) if visitors_b > 0 else 0, 2)
        
        cvr_a = round((conv_a / visitors_a * 100) if visitors_a > 0 else 0, 2)
        cvr_b = round((conv_b / visitors_b * 100) if visitors_b > 0 else 0, 2)
        
        stats = {
            'A': {'visitors': visitors_a, 'clicks': clicks_a, 'conversions': conv_a, 'ctr': ctr_a, 'cvr': cvr_a},
            'B': {'visitors': visitors_b, 'clicks': clicks_b, 'conversions': conv_b, 'ctr': ctr_b, 'cvr': cvr_b}
        }
        
        return render_template('analytics.html', stats=stats)
    finally:
        db_session.close()

if __name__ == '__main__':
    app.run(debug=True)
