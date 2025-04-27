from flask import Flask, request, render_template, session, redirect, url_for, g
from flask_session import Session
import google.generativeai as genai
import psycopg2
from psycopg2 import sql
import os
from datetime import datetime
import hashlib
from PIL import Image
import pytesseract
from dotenv import load_dotenv

app = Flask(__name__)

# Configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/tmp/flask_session"  # Use /tmp for session storage on Render
app.config["SESSION_FILE_THRESHOLD"] = 500
Session(app)

# Configure upload folder
UPLOAD_FOLDER = '/opt/render/project/src/uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER, mode=0o755)
    print(f"Created upload folder: {UPLOAD_FOLDER}")
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Load environment variables
load_dotenv()
api_key = os.getenv("API_KEY", "AIzaSyDMz8KbMluDCKlBmm-13L8xRHvoTtTgwHo")
DB_HOST = os.getenv("DB_HOST")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASS")
DB_PORT = os.getenv("DB_PORT", "5432")

# Configure Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel('models/gemini-2.0-flash')

# System prompt to enforce scope
SYSTEM_PROMPT = """
You are an AI-based expense categorizer. Respond to queries about categorizing expenses or tracking financial management with helpful suggestions. Use natural, human-like language for out-of-scope queries, such as 'Hmm, I'm not really equipped to answer that—I'm all about expense tracking!', use more answers like this for out of scope queries'
"""

def init_db():
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            connect_timeout=10
        )
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS chats
                     (chat_id SERIAL PRIMARY KEY,
                      user_message TEXT,
                      ai_response TEXT,
                      timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id SERIAL PRIMARY KEY,
                      username TEXT UNIQUE,
                      password TEXT)''')
        conn.commit()
        print("Database initialized successfully with PostgreSQL")
        return True
    except Exception as e:
        print(f"Failed to initialize database: {e}")
        return False
    finally:
        if conn is not None:
            conn.close()

@app.before_request
def initialize_database():
    if not hasattr(g, 'db_initialized'):
        g.db_initialized = init_db()
        print(f"Database initialization on request: {'Success' if g.db_initialized else 'Failed'}")

def save_chat(user_message, ai_response):
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            connect_timeout=10
        )
        c = conn.cursor()
        c.execute("INSERT INTO chats (user_message, ai_response) VALUES (%s, %s)", (user_message, ai_response))
        conn.commit()
        c.execute("SELECT chat_id FROM chats WHERE chat_id = currval(pg_get_serial_sequence('chats', 'chat_id'))")
        last_id = c.fetchone()[0]
        print(f"Chat saved successfully with ID {last_id}: User - {user_message}, AI - {ai_response}")
    except Exception as e:
        print(f"Error saving chat: {e}")
    finally:
        if conn is not None:
            conn.close()

def get_all_chats():
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            connect_timeout=10
        )
        c = conn.cursor()
        c.execute("SELECT chat_id, user_message, ai_response, timestamp FROM chats")
        chats = c.fetchall()
        print(f"Retrieved {len(chats)} chats from view_past: {chats}")
        return chats
    except Exception as e:
        print(f"Error retrieving chats: {e}")
        return []
    finally:
        if conn is not None:
            conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            connect_timeout=10
        )
        c = conn.cursor()
        hashed_password = hash_password(password)
        c.execute("INSERT INTO users (username, password) VALUES (%s, %s)", (username, hashed_password))
        conn.commit()
        print(f"User {username} registered successfully")
    except psycopg2.IntegrityError as e:
        print(f"Registration failed: Username {username} already exists, error: {e}")
        return False
    except psycopg2.OperationalError as e:
        print(f"Database connection error during registration: {e}")
        return False
    except Exception as e:
        print(f"Unexpected error during registration: {e}")
        return False
    finally:
        if conn is not None:
            conn.close()
    return True

def login_user(username, password):
    conn = None
    try:
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            connect_timeout=10
        )
        c = conn.cursor()
        hashed_password = hash_password(password)
        c.execute("SELECT user_id FROM users WHERE username = %s AND password = %s", (username, hashed_password))
        user = c.fetchone()
        if user:
            print(f"User {username} logged in successfully with user_id {user[0]}")
            return user[0]
        print(f"Login failed for user {username}: Invalid credentials")
        return None
    except psycopg2.OperationalError as e:
        print(f"Database connection error during login: {e}")
        return None
    except Exception as e:
        print(f"Unexpected error during login: {e}")
        return None
    finally:
        if conn is not None:
            conn.close()

def extract_text_from_image(image_file):
    try:
        img = Image.open(image_file)
        img = img.convert('L')
        img = img.point(lambda x: 0 if x < 128 else 255, '1')
        text = pytesseract.image_to_string(img)
        print(f"Extracted text from image: {text}")
        return text
    except Exception as e:
        print(f"Error extracting text from image: {e}")
        return f"Error extracting text: {e}"

def generate_response(query):
    try:
        print(f"Received query: {query}")
        response = model.generate_content(f"{SYSTEM_PROMPT}\nUser query: {query}")
        print(f"Generated response: {response.text}")
        return response.text
    except Exception as e:
        print(f"Error in generate_response: {e}")
        return f"Error: {e}"

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    session['messages'] = []
    print(f"Redirecting to home for user_id {session.get('user_id')}")
    return render_template('index.html', messages=session['messages'], show_past=False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    print("Entering /login route")
    if request.method == 'POST':
        print("Received POST request for login")
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        print(f"Attempting login for username: {username}")
        user_id = login_user(username, password)
        if user_id is not None:
            session['user_id'] = user_id
            print(f"Session set for user_id {user_id}, redirecting to home")
            return redirect(url_for('home'))
        print("Login failed, rendering login.html with error")
        error_msg = "Invalid username or password."
        if not getattr(g, 'db_initialized', False):
            error_msg += " Database connection failed; please try again later."
        return render_template('login.html', error=error_msg)
    print("Rendering login.html for GET request")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    print("Entering /register route")
    if request.method == 'POST':
        print("Received POST request for register")
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        print(f"Attempting registration for username: {username}")
        if register_user(username, password):
            print(f"Registration successful for {username}, redirecting to login")
            return redirect(url_for('login'))
        print("Registration failed, rendering register.html with error")
        error_msg = "Username already exists."
        if not getattr(g, 'db_initialized', False):
            error_msg += " Database connection failed; please try again later."
        return render_template('register.html', error=error_msg)
    print("Rendering register.html for GET request")
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session['messages'] = []
    print("User logged out, redirecting to login")
    return redirect(url_for('login'))

@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    print("Entering /chat route")
    user_query = request.form.get('query', '').strip()
    receipt_image = request.files.get('receipt_image')
    action = request.form.get('action', '')
    print(f"Processing POST request with query: {user_query}, action: {action}, image: {receipt_image}")

    response = ""
    if receipt_image and receipt_image.filename:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], receipt_image.filename)
        receipt_image.save(image_path)
        print(f"Image saved to: {image_path}")
        extracted_text = extract_text_from_image(image_path)
        if "Error" in extracted_text or not extracted_text.strip():
            response = "Sorry, I couldn’t read the receipt. Please upload a clearer image or type the details manually."
        else:
            categorization_prompt = f"""
            {SYSTEM_PROMPT}
            User uploaded a receipt with the following details:
            {extracted_text}
            Please:
            1. Identify and list individual expense items (e.g., item name, amount).
            2. Categorize each item (e.g., groceries, dining, utilities).
            3. Provide a total amount if possible.
            4. Summarize the receipt in a concise format.
            """
            response = generate_response(categorization_prompt)
        try:
            os.remove(image_path)
            print(f"Deleted temporary image: {image_path}")
        except Exception as e:
            print(f"Error deleting temporary image: {e}")
        session['messages'].append({"text": "Receipt uploaded", "is_user": True})
        session['messages'].append({"text": response, "is_user": False})
        save_chat("Receipt uploaded", response)
    elif user_query:
        session['messages'].append({"text": user_query, "is_user": True})
        response = generate_response(user_query)
        session['messages'].append({"text": response, "is_user": False})
        save_chat(user_query, response)
    else:
        session['messages'].append({"text": "Please provide a query or upload a receipt.", "is_user": False})
    return render_template('index.html', messages=session['messages'], show_past=False)

@app.route('/view_past')
def view_past():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    print("Entering /view_past route")
    chats = get_all_chats()
    if not chats:
        print("No chats found in database.")
        return render_template('index.html', messages=[{"text": "No past chats available.", "is_user": False}], show_past=True)
    formatted_chats = []
    for chat in chats:
        chat_id, user_message, ai_response, timestamp = chat
        formatted_chats.append({"text": user_message, "is_user": True})
        formatted_chats.append({"text": f"{ai_response}, Time - {timestamp}", "is_user": False})
    print(f"Formatted chats for display: {formatted_chats}")
    return render_template('index.html', messages=formatted_chats, show_past=True)

if __name__ == "__main__":
    if not init_db():  # Attempt to initialize, but don't crash if it fails
        print("Database initialization failed at startup, proceeding without database (limited functionality)")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)