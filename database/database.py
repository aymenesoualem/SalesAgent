import psycopg2
from psycopg2.errors import DuplicateTable, UniqueViolation

import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from utils.phone import normalize_phone_number

# Database connection parameters
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "ThomGroupSupport_db"
DB_USER = "agent"
DB_PASSWORD = "sales"

def create_tables():
    create_table_query = """
    DROP TABLE IF EXISTS support_tickets CASCADE;
    DROP TABLE IF EXISTS orders CASCADE;
    DROP TABLE IF EXISTS stores CASCADE;
    DROP TABLE IF EXISTS products CASCADE;
    DROP TABLE IF EXISTS customers CASCADE;

    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        brand VARCHAR(50) NOT NULL,
        name VARCHAR(100) NOT NULL,
        category VARCHAR(50) NOT NULL,
        material VARCHAR(50) NOT NULL,
        price NUMERIC(10, 2) NOT NULL,
        in_stock BOOLEAN NOT NULL DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS stores (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        city VARCHAR(50) NOT NULL,
        address VARCHAR(150) NOT NULL,
        phone VARCHAR(20) NOT NULL,
        opening_hours VARCHAR(100) NOT NULL
    );

    -- A phone number can be shared by more than one known customer (e.g. a
    -- household line), so phone_number is not unique on its own; the
    -- (full_name, phone_number) pair is, so re-adding the same customer is a no-op.
    CREATE TABLE IF NOT EXISTS customers (
        id SERIAL PRIMARY KEY,
        full_name VARCHAR(150) NOT NULL,
        phone_number VARCHAR(20) NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (full_name, phone_number)
    );
    CREATE INDEX IF NOT EXISTS idx_customers_phone_number ON customers (phone_number);

    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        order_number VARCHAR(20) UNIQUE NOT NULL,
        customer_name VARCHAR(100) NOT NULL,
        phone_number VARCHAR(20) NOT NULL,
        product_reference VARCHAR(30) NOT NULL,
        product_name VARCHAR(255) NOT NULL,
        status VARCHAR(30) NOT NULL,
        estimated_delivery DATE
    );
    CREATE INDEX IF NOT EXISTS idx_orders_phone_number ON orders (phone_number);

    CREATE TABLE IF NOT EXISTS support_tickets (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        phone_number VARCHAR(15) NOT NULL,
        issue_type VARCHAR(50) NOT NULL,
        priority INTEGER NOT NULL CHECK (priority BETWEEN 1 AND 5),
        summary TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    return create_table_query

def populate_products():
    sample_products_query = """
    INSERT INTO products (brand, name, category, material, price, in_stock)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    """
    sample_products = [
        ("Histoire d'Or", "Solitaire Ring 18K Gold", "Ring", "Gold", 450.00, True),
        ("Marc Orian", "Classic Wedding Band", "Ring", "Gold", 320.00, True),
        ("AGATHA", "Heart Pendant Necklace", "Necklace", "Silver", 89.00, True),
        ("Stroili", "Pearl Drop Earrings", "Earrings", "Silver", 65.00, False),
        ("Ti Sento", "Milano Chain Bracelet", "Bracelet", "Silver", 75.00, True),
        ("Calvin Klein", "Minimalist Watch", "Watch", "Stainless Steel", 199.00, True),
    ]
    return sample_products_query, sample_products

def populate_stores():
    sample_stores_query = """
    INSERT INTO stores (name, city, address, phone, opening_hours)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    """
    sample_stores = [
        ("Histoire d'Or Châtelet", "Paris", "10 Rue de Rivoli, 75001 Paris", "+33 1 23 45 67 89", "Mon-Sat 10:00-19:00"),
        ("Marc Orian Part-Dieu", "Lyon", "Centre Commercial Part-Dieu, 69003 Lyon", "+33 4 56 78 90 12", "Mon-Sat 10:00-20:00"),
        ("AGATHA Saint-Ferréol", "Marseille", "22 Rue Saint-Ferréol, 13001 Marseille", "+33 4 91 23 45 67", "Mon-Sat 10:00-19:00"),
        ("Stroili Duomo", "Milan", "Piazza del Duomo 5, 20122 Milano", "+39 02 12 34 567", "Mon-Sat 10:00-19:30"),
    ]
    return sample_stores_query, sample_stores

def populate_customers():
    sample_customers_query = """
    INSERT INTO customers (full_name, phone_number)
    VALUES (%s, %s)
    ON CONFLICT (full_name, phone_number) DO NOTHING;
    """
    sample_customers = [
        ("Sylvie Garrido", normalize_phone_number("0033786775314")),
        ("Arnaud Dupond", normalize_phone_number("0033786346735")),
        ("Stéphanie Dupuis", normalize_phone_number("0033786346735")),
        ("Lucas Fournier", normalize_phone_number("0033786346735")),
        ("Hatim ZINE EL ABIDINE", normalize_phone_number("00212660321523")),
        ("Aymene Soualem", normalize_phone_number("00212660214570")),
    ]
    return sample_customers_query, sample_customers

def populate_orders():
    sample_orders_query = """
    INSERT INTO orders (order_number, customer_name, phone_number, product_reference, product_name, status, estimated_delivery)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    """
    sample_orders = [
        ("958324522190", "Sylvie Garrido", normalize_phone_number("0033786775314"), "13280066909R00",
         "Collier Or Jaune 375/1000 Maille Alternée 1/3 Largeur 4.4mm 50cm", "En préparation", None),
        ("951234567890", "Arnaud Dupond", normalize_phone_number("0033786346735"), "70580224153R00",
         "Montre Ice Watch Smart Fit 3.0 Plastique Noir Connectee Rectangulaire 36,3Mm Bracelet Silicone Noir 025277",
         "Expédition", None),
        ("951234435933", "Stéphanie Dupuis", normalize_phone_number("0033786346735"), "61440139376R00",
         "Bracelet Jourdan Homme Acier Aghate Noire Bracelet Ciur", "Expédition", None),
        ("959834662290", "Lucas Fournier", normalize_phone_number("0033786346735"), "50460118133R00",
         "Bracelet Argent Blanc 925/1000 Céramique Noire Ovale Pavage Oxydes De Zirconium Maille Forcat 15.5+3cm",
         "Livrée", None),
        ("957634623780", "Hatim ZINE EL ABIDINE", normalize_phone_number("00212660321523"), "13180226187R00",
         "Creoles Rectangles Or Jaune 375/1000 Fil Rond Diametre 5.8*10.8Mm", "En préparation", None),
        ("953344556677", "Aymene Soualem", normalize_phone_number("00212660214570"), "40450078522R00",
         "Bracelet Or Jaune 375/1000 Maille Gourmette 18cm", "Expédition", None),
    ]
    return sample_orders_query, sample_orders

def populate_support_tickets():
    sample_tickets_query = """
    INSERT INTO support_tickets (name, phone_number, issue_type, priority, summary)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    """
    sample_tickets = [
        ("Omar Laabidi", "+212612345678", "Repair", 3, "Customer's ring needs resizing, referred to Paris Châtelet store."),
    ]
    return sample_tickets_query, sample_tickets

def create_and_populate_tables():
    try:
        connection = psycopg2.connect(
            host=DB_HOST,
            port=DB_PORT,
            database=DB_NAME,
            user=DB_USER,
            password=DB_PASSWORD
        )
        connection.autocommit = True
        cursor = connection.cursor()

        print("Creating tables...")
        cursor.execute(create_tables())
        print("Tables created.")

        print("Inserting product data...")
        product_query, products_data = populate_products()
        cursor.executemany(product_query, products_data)
        print("Products inserted.")

        print("Inserting store data...")
        store_query, stores_data = populate_stores()
        cursor.executemany(store_query, stores_data)
        print("Stores inserted.")

        print("Inserting customer data...")
        customer_query, customers_data = populate_customers()
        cursor.executemany(customer_query, customers_data)
        print("Customers inserted.")

        print("Inserting order data...")
        order_query, orders_data = populate_orders()
        cursor.executemany(order_query, orders_data)
        print("Orders inserted.")

        print("Inserting support ticket data...")
        ticket_query, tickets_data = populate_support_tickets()
        cursor.executemany(ticket_query, tickets_data)
        print("Support tickets inserted.")

    except (DuplicateTable, UniqueViolation) as err:
        print("Database error:", err)
    except psycopg2.Error as e:
        print("PostgreSQL error:", e)
    finally:
        if 'cursor' in locals():
            cursor.close()
        if 'connection' in locals():
            connection.close()
        print("PostgreSQL connection closed.")

if __name__ == "__main__":
    create_and_populate_tables()
