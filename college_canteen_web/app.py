from flask import Flask, render_template, request, redirect, url_for, session, send_from_directory
import mysql.connector
import bcrypt
import pandas as pd
import os
from functools import wraps
from decimal import Decimal # <--- CRITICAL: For precise financial math

# Set Matplotlib backend *before* importing pyplot or seaborn
import matplotlib
matplotlib.use('Agg') 
import matplotlib.pyplot as plt
import seaborn as sns

app = Flask(__name__)
app.secret_key = 'canteen_secret_key'

# Directory to save charts
# Use app.root_path to correctly locate the static/charts directory
CHART_DIR = os.path.join(app.root_path, 'static', 'charts')
if not os.path.exists(CHART_DIR):
    os.makedirs(CHART_DIR)

# Hardcoded Admin Credentials (Uses dynamic hashing for reliable login)
ADMIN_EMAIL = 'admin@canteen.com'
ADMIN_PASSWORD_PASSWORD = 'adminpass'
# Generate the hash once on startup
ADMIN_PASSWORD_HASH = bcrypt.hashpw(ADMIN_PASSWORD_PASSWORD.encode('utf-8'), bcrypt.gensalt(12))

# ----------------- DATABASE CONNECTION -----------------
# Ensure the database 'college_canteen' exists and credentials are correct
try:
    con = mysql.connector.connect(
        host="localhost",
        user="root",
        password="123456",
        database="college_canteen",
        charset='utf8',
        use_unicode=True 
    )
    cursor = con.cursor(dictionary=True)
except mysql.connector.Error as err:
    print(f"Database connection error: {err}")
    # In a real app, you'd handle this more gracefully
    exit(1)


# ----------------- HELPER FUNCTIONS -----------------
def generate_profit_chart():
    """Fetches order data, calculates profit, and generates a bar chart."""
    
    # Query: Total revenue grouped by menu item
    cursor.execute("""
        SELECT m.item_name, COALESCE(SUM(m.price * oi.quantity), 0) AS total_revenue
        FROM order_items oi
        JOIN menu m ON oi.item_id = m.item_id
        GROUP BY m.item_name
        ORDER BY total_revenue DESC
    """)
    data = cursor.fetchall()
    
    if not data:
        return None 
    
    df = pd.DataFrame(data)
    
    # Generate Chart
    plt.figure(figsize=(10, 6))
    if not df.empty:
        sns.barplot(x='item_name', y='total_revenue', data=df, palette='viridis')
        plt.title('Total Revenue by Menu Item')
        plt.xlabel('Menu Item')
        plt.ylabel('Total Revenue (₹)')
        plt.xticks(rotation=45, ha='right')
        plt.tight_layout()
        
        # Save Chart
        # Use the relative path to CHART_DIR since we are accessing it via /static
        chart_path = os.path.join(app.root_path, CHART_DIR, 'profit_chart.png')
        plt.savefig(chart_path)
        plt.close() # Important: Close the figure to free memory
        # Return the path relative to the static folder
        return 'charts/profit_chart.png'
    return None

def admin_required(f):
    """Decorator to check if the current user is logged in as Admin."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'is_admin' not in session or not session['is_admin']:
            return redirect(url_for('admin_login'))
        return f(*args, **kwargs)
    return decorated_function

# ----------------- STUDENT ROUTES -----------------
@app.route('/')
def home():
    return render_template('index.html')

# ---------- Registration ----------
@app.route('/register', methods=['POST'])
def register():
    name = request.form['name']
    email = request.form['email']
    password = request.form['password']

    cursor.execute("SELECT * FROM students WHERE email = %s", (email,))
    if cursor.fetchone():
        return "⚠️ Email already registered!"

    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
    cursor.execute(
        "INSERT INTO students (name, email, password) VALUES (%s, %s, %s)",
        (name, email, hashed.decode('utf-8'))
    )
    con.commit()
    return redirect(url_for('home'))

# ---------- Login (Student) ----------
@app.route('/login', methods=['POST'])
def login():
    email = request.form['email']
    password = request.form['password']

    cursor.execute("SELECT * FROM students WHERE email = %s", (email,))
    user = cursor.fetchone()

    if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        session['student_id'] = user['student_id']
        session['student_name'] = user['name']
        session['is_admin'] = False
        return redirect(url_for('menu')) 
    else:
        # User requested to remove admin link from this error
        return "❌ Invalid student credentials! Please check your email and password."

# ---------- Menu Page ----------
@app.route('/menu')
def menu():
    if 'student_id' not in session:
        return redirect(url_for('home'))
    cursor.execute("SELECT * FROM menu")
    items = cursor.fetchall()
    return render_template('menu.html', items=items, student=session['student_name'])

# ---------- Place Order (FINALIZED TRANSACTIONAL LOGIC) ----------
@app.route('/order', methods=['POST'])
def order():
    if 'student_id' not in session:
        return redirect(url_for('home'))

    student_id = session.get('student_id')
    
    # 1. Collect and validate items
    selected_items = []
    for key, value in request.form.items():
        if key.startswith("quantity_"):
            try:
                quantity = int(value)
                if quantity > 0:
                    item_id = int(key.split("_")[1])
                    selected_items.append((item_id, quantity))
            except ValueError:
                continue

    if not selected_items:
        return "⚠️ Please select 1 or more items to order!", 400

    # 2. Start Transaction
    try:
        # A. Insert initial order record to get the ID. DO NOT COMMIT YET.
        # Note: We are not setting total_cost or order_items_list yet, leaving them NULL temporarily.
        cursor.execute("INSERT INTO orders (student_id) VALUES (%s)", (student_id,))
        new_order_id = cursor.lastrowid
        
        total_order_cost = Decimal(0) 
        ordered_items_details = []
        
        # B. Process items, calculate cost, and insert order_items
        for item_id, quantity in selected_items:
            
            # Fetch item price
            cursor.execute("SELECT item_name, price FROM menu WHERE item_id = %s", (item_id,))
            item = cursor.fetchone()

            if item:
                # Use Decimal for item price from DB
                item_price = Decimal(str(item['price'])) 
                item_name = item['item_name']
                
                item_cost = item_price * quantity
                total_order_cost += item_cost 

                # Insert into order_items
                cursor.execute("INSERT INTO order_items (order_id, item_id, quantity) VALUES (%s, %s, %s)",
                               (new_order_id, item_id, quantity))

                ordered_items_details.append(f"{item_name} x {quantity}")
            else:
                 # If item not found, raise an exception to trigger rollback
                 raise Exception(f"Item ID {item_id} not found.")

        # C. CRITICAL STEP: Update the orders table with the calculated total cost and item list
        order_items_string = ", ".join(ordered_items_details)
        cursor.execute("""
            UPDATE orders 
            SET total_cost = %s, order_items_list = %s
            WHERE order_id = %s
        """, (total_order_cost, order_items_string, new_order_id))

        # D. Final Commit: Commit the entire transaction only after all order_items and the orders table update succeed
        con.commit()
        
        return redirect(url_for('orders'))

    except Exception as e:
        # If any query fails, rollback everything to prevent incomplete records (NULLs)
        con.rollback() 
        print(f"Error processing order: {e}")
        return "❌ An error occurred while placing your order. All changes rolled back. Please try again.", 500


# ---------- View Orders (CRASH FIX REMAINS) ----------
@app.route('/orders')
def orders():
    if 'student_id' not in session:
        return redirect(url_for('home'))

    # NOTE: Using the stored total_cost and order_items_list columns instead of recalculating via JOIN/SUM/GROUP_CONCAT
    # This is more efficient now that the data is stored correctly on order placement.
    # We still use COALESCE in case of old, malformed data in the DB.
    cursor.execute("""
        SELECT 
            order_id,
            COALESCE(order_items_list, 'N/A - Data Missing') AS order_items_list,
            COALESCE(total_cost, 0.00) AS total,
            order_time
        FROM orders 
        WHERE student_id = %s
        ORDER BY order_time DESC
    """, (session['student_id'],))

    order_list = cursor.fetchall()

    for o in order_list:
        # Ensure total is float for display
        o['total'] = float(o['total']) 
        o['order_items_list'] = str(o['order_items_list']) 

    return render_template('orders.html', orders=order_list, student=session['student_name'])

# ---------- Logout (Student) ----------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ----------------- ADMIN ROUTES -----------------

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        error = None
        
        try:
             # Admin login check using the dynamically generated hash
             if email == ADMIN_EMAIL and bcrypt.checkpw(password.encode('utf-8'), ADMIN_PASSWORD_HASH):
                 session['is_admin'] = True
                 session['student_name'] = 'Admin'
                 return redirect(url_for('admin_dashboard'))
             else:
                 error = "Invalid admin credentials. Please check your email and password."
        except ValueError:
             # This handles cases where the hash might be corrupted, though unlikely here
             error = "An error occurred during password validation."

        return render_template('admin_login.html', error=error)
    return render_template('admin_login.html')

@app.route('/admin')
@admin_required
def admin_dashboard():
    # 1. Get stats
    cursor.execute("SELECT COUNT(*) AS total_orders FROM orders")
    total_orders = cursor.fetchone()['total_orders']

    cursor.execute("SELECT COUNT(*) AS total_items FROM menu")
    total_menu_items = cursor.fetchone()['total_items']
    
    cursor.execute("SELECT COUNT(*) AS total_students FROM students")
    total_students = cursor.fetchone()['total_students']
    
    # Query: SUM of stored total_cost in the orders table
    cursor.execute("""
        SELECT COALESCE(SUM(total_cost), 0) AS total_revenue
        FROM orders
    """)
    revenue_result = cursor.fetchone()
    total_revenue = float(revenue_result['total_revenue']) if revenue_result['total_revenue'] else 0.00

    # 2. Generate and get chart path
    chart_file = generate_profit_chart()
    
    # 3. Fetch menu for management
    cursor.execute("SELECT * FROM menu")
    menu_items = cursor.fetchall()

    return render_template('admin_dashboard.html', 
                            total_orders=total_orders,
                            total_menu_items=total_menu_items,
                            total_students=total_students, 
                            total_revenue=total_revenue,
                            menu_items=menu_items,
                            chart_file=chart_file)

@app.route('/admin/add_item', methods=['POST'])
@admin_required
def admin_add_item():
    name = request.form['name']
    price = request.form['price']
    
    try:
        cursor.execute("INSERT INTO menu (item_name, price) VALUES (%s, %s)", (name, price))
        con.commit()
    except Exception as e:
        print(f"Error adding item: {e}")
    
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/remove_item/<int:item_id>')
@admin_required
def admin_remove_item(item_id):
    try:
        # NOTE: Deleting from order_items must happen first due to foreign key constraints
        cursor.execute("DELETE FROM order_items WHERE item_id = %s", (item_id,))
        cursor.execute("DELETE FROM menu WHERE item_id = %s", (item_id,))
        con.commit()
    except Exception as e:
        print(f"Error removing item: {e}")

    return redirect(url_for('admin_dashboard'))

@app.route('/admin/logout')
def admin_logout():
    session.pop('is_admin', None)
    session.pop('student_name', None)
    return redirect(url_for('home'))

# ---------- RUN SERVER ----------
if __name__ == '__main__':
    # Print admin credentials for easy debugging
    print("-" * 50)
    print("✨ Canteen App Initialized")
    print(f"   Admin Email: {ADMIN_EMAIL}")
    print(f"   Admin Password: {ADMIN_PASSWORD_PASSWORD}")
    print("-" * 50)
    app.run(debug=True)
