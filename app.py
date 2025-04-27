from flask import Flask, request, render_template, session, redirect, url_for
from flask_session import Session
import google.generativeai as genai
import sqlite3
import os
from datetime import datetime
import hashlib
from PIL import Image
import pytesseract
import io

app = Flask(__name__)

# Configure session
app.config["SESSION_PERMANENT"] = False
app.config["SESSION_TYPE"] = "filesystem"
Session(app)

# Configure upload folder
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Load API key from environment variable (hardcoded for now, consider using os.getenv)
api_key = "AIzaSyDMz8KbMluDCKlBmm-13L8xRHvoTtTgwHo"

# Configure Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel('models/gemini-2.0-flash')

# System prompt to enforce scope
SYSTEM_PROMPT = """
You are an AI-based expense categorizer. Respond to queries about categorizing expenses or tracking financial management with helpful suggestions. Use natural, human-like language for out-of-scope queries, such as 'Hmm, I'm not really equipped to answer that—I'm all about expense tracking!', use more answers like this for out of scope queries'
"""

# Explicitly set database path (consider using relative path or environment variable)
DB_PATH = r"C:\Users\d2vv8\OneDrive\Desktop\INT428\trackit_chats.db"

# Set Tesseract path (adjust for your system)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Create chats table
        c.execute('''CREATE TABLE IF NOT EXISTS chats
                     (chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      user_message TEXT,
                      ai_response TEXT,
                      timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        # Create users table
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                      username TEXT UNIQUE,
                      password TEXT)''')
        conn.commit()
        print(f"Database initialized successfully at {DB_PATH}")
    except sqlite3.Error as e:
        print(f"Database initialization error: {e}")
    finally:
        conn.close()

def save_chat(user_message, ai_response):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute("INSERT INTO chats (user_message, ai_response) VALUES (?, ?)", (user_message, ai_response))
        conn.commit()
        last_id = c.lastrowid
        c.execute("SELECT * FROM chats WHERE chat_id = ?", (last_id,))
        verify = c.fetchone()
        print(f"Chat saved successfully with ID {last_id}: User - {user_message}, AI - {ai_response}, Verified: {verify}")
    except sqlite3.Error as e:
        print(f"Error saving chat: {e}")
    finally:
        conn.close()

def get_all_chats():
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        c.execute("SELECT chat_id, user_message, ai_response, timestamp FROM chats")
        chats = c.fetchall()
        print(f"Retrieved {len(chats)} chats from view_past: {chats}")
        return chats
    except sqlite3.Error as e:
        print(f"Error retrieving chats: {e}")
        return []
    finally:
        conn.close()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def register_user(username, password):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        hashed_password = hash_password(password)
        c.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, hashed_password))
        conn.commit()
        print(f"User {username} registered successfully")
    except sqlite3.IntegrityError:
        print(f"Username {username} already exists")
        return False
    except sqlite3.Error as e:
        print(f"Error registering user: {e}")
        return False
    finally:
        conn.close()
    return True

def login_user(username, password):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        c = conn.cursor()
        hashed_password = hash_password(password)
        c.execute("SELECT user_id FROM users WHERE username = ? AND password = ?", (username, hashed_password))
        user = c.fetchone()
        if user:
            return user[0]  # Return user_id
        return None
    except sqlite3.Error as e:
        print(f"Error logging in: {e}")
        return None
    finally:
        conn.close()

def extract_text_from_image(image_file):
    try:
        # Open image using Pillow
        img = Image.open(image_file)
        # Convert to grayscale
        img = img.convert('L')
        # Binarize the image (black and white) to improve contrast
        img = img.point(lambda x: 0 if x < 128 else 255, '1')
        # Extract text using pytesseract
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
    return render_template('index.html', messages=session['messages'], show_past=False)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        user_id = login_user(username, password)
        if user_id:
            session['user_id'] = user_id
            return redirect(url_for('home'))
        return render_template('login.html', error="Invalid username or password")
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if register_user(username, password):
            return redirect(url_for('login'))
        return render_template('register.html', error="Username already exists")
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session['messages'] = []
    return redirect(url_for('login'))

@app.route('/chat', methods=['POST'])
def chat():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    user_query = request.form.get('query', '').strip()
    receipt_image = request.files.get('receipt_image')
    action = request.form.get('action', '')
    print(f"Processing POST request with query: {user_query}, action: {action}, image: {receipt_image}")

    # Initialize response message
    response = ""

    if receipt_image and receipt_image.filename:
        # Save the uploaded image temporarily
        image_path = os.path.join(app.config['UPLOAD_FOLDER'], receipt_image.filename)
        receipt_image.save(image_path)
        print(f"Image saved to: {image_path}")

        # Extract text from the image
        extracted_text = extract_text_from_image(image_path)
        
        if "Error" in extracted_text or not extracted_text.strip():
            response = "Sorry, I couldn’t read the receipt. Please upload a clearer image or type the details manually."
        else:
            # Generate categorization prompt
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
        
        # Clean up the saved image
        try:
            os.remove(image_path)
            print(f"Deleted temporary image: {image_path}")
        except Exception as e:
            print(f"Error deleting temporary image: {e}")

        session['messages'].append({"text": "Receipt uploaded", "is_user": True})
        session['messages'].append({"text": response, "is_user": False})
        save_chat("Receipt uploaded", response)
    
    elif user_query:
        # Handle text query as before
        session['messages'].append({"text": user_query, "is_user": True})
        response = generate_response(user_query)
        session['messages'].append({"text": response, "is_user": False})
        save_chat(user_query, response)
    
    else:
        # No input provided
        session['messages'].append({"text": "Please provide a query or upload a receipt.", "is_user": False})

    return render_template('index.html', messages=session['messages'], show_past=False)

@app.route('/view_past')
def view_past():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    print(f"Viewing past chats, action parameter: view_past")
    chats = get_all_chats()
    if not chats:
        print("No chats found in database.")
        return render_template('index.html', messages=[{"text": "No past chats available.", "is_user": False}], show_past=True)
    # Format chats to include is_user flag for user/AI differentiation
    formatted_chats = []
    for chat in chats:
        chat_id, user_message, ai_response, timestamp = chat
        # Add user message
        formatted_chats.append({"text": user_message, "is_user": True})
        # Add AI response
        formatted_chats.append({"text": f"{ai_response}, Time - {timestamp}", "is_user": False})
    print(f"Formatted chats for display: {formatted_chats}")
    return render_template('index.html', messages=formatted_chats, show_past=True)

if __name__ == '__main__':
    init_db()
    app.run(debug=True)