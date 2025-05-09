from flask import Flask, request, render_template, session, redirect, url_for, g
from flask_session import Session
import google.generativeai as genai
import psycopg2
from psycopg2 import sql
import os
from datetime import datetime
import hashlib
from dotenv import load_dotenv

app = Flask(__name__)

# Configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_FILE_DIR"] = "/tmp/flask_session"
app.config["SESSION_FILE_THRESHOLD"] = 500
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-here")
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
You are an AI-based expense categorizer. Respond to queries about categorizing expenses or tracking financial management with helpful suggestions. Use natural, human-like language for out-of-scope queries, such as 'Hmm, I'm not really equipped to answer that—I'm all about expense tracking!'
"""

def init_db():
    conn = None
    try:
        print(f"Attempting to initialize database: host={DB_HOST}, dbname={DB_NAME}, user={DB_USER}, port={DB_PORT}")
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            connect_timeout=10
        )
        c = conn.cursor()
        # Create tables if they don't exist
        c.execute('''CREATE TABLE IF NOT EXISTS chats
                     (chat_id SERIAL PRIMARY KEY,
                      user_id INTEGER,
                      user_message TEXT,
                      ai_response TEXT,
                      timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id SERIAL PRIMARY KEY,
                      username TEXT UNIQUE,
                      password TEXT)''')
        # Check and add user_id column if missing
        c.execute("SELECT column_name FROM information_schema.columns WHERE table_name='chats' AND column_name='user_id'")
        if not c.fetchone():
            c.execute("ALTER TABLE chats ADD COLUMN user_id INTEGER")
            print("Added user_id column to chats table")
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

def save_chat(user_id, user_message, ai_response):
    conn = None
    try:
        print(f"Attempting to save chat for user_id={user_id}: user_message={user_message}, ai_response={ai_response}")
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            connect_timeout=10
        )
        c = conn.cursor()
        c.execute("INSERT INTO chats (user_id, user_message, ai_response) VALUES (%s, %s, %s)", (user_id, user_message, ai_response))
        conn.commit()
        c.execute("SELECT chat_id FROM chats WHERE chat_id = currval(pg_get_serial_sequence('chats', 'chat_id'))")
        last_id = c.fetchone()[0]
        print(f"Chat saved successfully with ID {last_id}")
    except Exception as e:
        print(f"Error saving chat: {e}")
    finally:
        if conn is not None:
            conn.close()

def get_all_chats(user_id):
    conn = None
    try:
        print(f"Attempting to retrieve chats for user_id={user_id}")
        conn = psycopg2.connect(
            host=DB_HOST,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASS,
            port=DB_PORT,
            connect_timeout=10
        )
        c = conn.cursor()
        c.execute("SELECT chat_id, user_message, ai_response, timestamp FROM chats WHERE user_id = %s ORDER BY timestamp DESC LIMIT 50", (user_id,))
        chats = c.fetchall()
        print(f"Retrieved {len(chats)} chats for user_id={user_id}: {chats}")
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
        print(f"Attempting to register user: username={username}")
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
        print(f"Attempting to login user: username={username}")
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

def generate_response(query, image_path=None):
    try:
        print(f"Generating response for query: {query}, image_path: {image_path}")
        parts = [{"text": f"{SYSTEM_PROMPT}\nUser query: {query}"}]
        if image_path:
            print(f"Uploading image to Gemini API: {image_path}")
            uploaded_file = genai.upload_file(image_path, mime_type="image/jpeg")
            parts.append({
                "file_data": {
                    "file_uri": uploaded_file.uri,
                    "mime_type": "image/jpeg"
                }
            })
            parts[0]["text"] += "\nPlease categorize the expenses from this receipt image."
        response = model.generate_content(parts)
        print(f"Generated response: {response.text}")
        return response.text
    except Exception as e:
        print(f"Error in generate_response: {e}")
        return f"Error: {e}"

@app.route('/')
def home():
    if 'user_id' not in session:
        print("No user_id in session, redirecting to login")
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
            print(f"Login successful, session set for user_id {user_id}, redirecting to home")
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
    print(f"Logging out user with user_id {session.get('user_id')}")
    session.pop('user_id', None)
    session['messages'] = []
    print("User logged out, redirecting to login")
    return redirect(url_for('login'))

@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session:
        print("No user_id in session, redirecting to login")
        return redirect(url_for('login'))
    user_id = session['user_id']
    print(f"Entering /chat route for user_id {user_id}")
    user_query = request.form.get('query', '').strip()
    receipt_image = request.files.get('receipt_image')
    action = request.form.get('action', '')
    print(f"Processing POST request with query: {user_query}, action: {action}, image: {receipt_image}")

    response = ""
    if receipt_image and receipt_image.filename:
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], receipt_image.filename)
        receipt_image.save(image_path)
        print(f"Image saved to: {image_path}")
        response = generate_response("Receipt uploaded", image_path=image_path)
        session['messages'].append({"text": "Receipt uploaded", "is_user": True})
        session['messages'].append({"text": response, "is_user": False})
        save_chat(user_id, "Receipt uploaded", response)
        try:
            os.remove(image_path)
            print(f"Deleted temporary image: {image_path}")
        except Exception as e:
            print(f"Error deleting temporary image: {e}")
    elif user_query:
        session['messages'].append({"text": user_query, "is_user": True})
        response = generate_response(user_query)
        session['messages'].append({"text": response, "is_user": False})
        save_chat(user_id, user_query, response)
    else:
        session['messages'].append({"text": "Please provide a query or upload a receipt.", "is_user": False})
    return render_template('index.html', messages=session['messages'], show_past=False)

@app.route('/view_past')
def view_past():
    if 'user_id' not in session:
        print("No user_id in session, redirecting to login")
        return redirect(url_for('login'))
    user_id = session['user_id']
    print(f"Entering /view_past route for user_id {user_id}")
    chats = get_all_chats(user_id)
    if not chats:
        print("No chats found for user.")
        return render_template('index.html', messages=[{"text": "No past chats available.", "is_user": False}], show_past=True)
    formatted_chats = []
    for chat in chats:
        chat_id, user_message, ai_response, timestamp = chat
        formatted_chats.append({"text": user_message, "is_user": True})
        formatted_chats.append({"text": f"{ai_response}, Time - {timestamp}", "is_user": False})
    print(f"Formatted chats for display: {formatted_chats}")
    return render_template('index.html', messages=formatted_chats, show_past=True)

if __name__ == "__main__":
    if not init_db():
        print("Database initialization failed at startup, proceeding without database (limited functionality)")
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)