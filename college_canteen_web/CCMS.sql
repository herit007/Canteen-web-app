-- Drop old database if exists
DROP DATABASE IF EXISTS college_canteen;

-- Create new database
CREATE DATABASE IF NOT EXISTS college_canteen;
USE college_canteen;

-- Table for students (users)
CREATE TABLE students (
    student_id INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100),
    email VARCHAR(100) UNIQUE,
    password VARCHAR(100)
);

-- Table for menu items
CREATE TABLE menu (
    item_id INT AUTO_INCREMENT PRIMARY KEY,
    item_name VARCHAR(100),
    price DECIMAL(6,2)
);

-- Table for orders (one row per order)
CREATE TABLE orders (
    order_id INT AUTO_INCREMENT PRIMARY KEY,
    student_id INT NOT NULL,
    total_cost DECIMAL(6,2),          -- <--- NEW: Added column for total order cost
    order_items_list VARCHAR(255),    -- <--- NEW: Added column for item list summary
    order_time DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Table for order items (one row per item in an order)
CREATE TABLE order_items (
    order_item_id INT AUTO_INCREMENT PRIMARY KEY,
    order_id INT NOT NULL,
    item_id INT NOT NULL,
    quantity INT NOT NULL
);

-- ---------- Add Foreign Keys using ALTER TABLE ----------
ALTER TABLE orders
ADD CONSTRAINT fk_orders_student
FOREIGN KEY (student_id) REFERENCES students(student_id);

ALTER TABLE order_items
ADD CONSTRAINT fk_orderitems_order
FOREIGN KEY (order_id) REFERENCES orders(order_id);

ALTER TABLE order_items
ADD CONSTRAINT fk_orderitems_menu
FOREIGN KEY (item_id) REFERENCES menu(item_id);

-- ---------- Insert some food items ----------
INSERT INTO menu (item_name, price) VALUES
('Samosa', 15.00),
('Vada Pav', 20.00),
('Tea', 10.00),
('Coffee', 25.00),
('Noodles', 60.00),
('Pizza Slice', 75.00),
('Fresh Juice', 40.00);
