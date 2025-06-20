import psycopg2
from psycopg2.errors import DuplicateTable, UniqueViolation

# Database connection parameters
DB_HOST = "localhost"
DB_PORT = 5432
DB_NAME = "CarDealership_db"
DB_USER = "agent"
DB_PASSWORD = "sales"

def create_tables():
    create_table_query = """
    DROP TABLE IF EXISTS leads CASCADE;
    DROP TABLE IF EXISTS cars CASCADE;

    CREATE TABLE IF NOT EXISTS cars (
        id SERIAL PRIMARY KEY,
        make VARCHAR(50) NOT NULL,
        model VARCHAR(50) NOT NULL,
        year INTEGER NOT NULL,
        price NUMERIC(10, 2) NOT NULL,
        type VARCHAR(50) NOT NULL,
        available BOOLEAN NOT NULL DEFAULT TRUE
    );

    CREATE TABLE IF NOT EXISTS leads (
        id SERIAL PRIMARY KEY,
        name VARCHAR(100) NOT NULL,
        phone_number VARCHAR(15) UNIQUE NOT NULL,
        lead_source VARCHAR(50),
        interest_score INTEGER NOT NULL CHECK (interest_score BETWEEN 1 AND 5),
        call_summary TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    return create_table_query

def populate_cars():
    sample_cars_query = """
    INSERT INTO cars (make, model, year, price, available, type)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    """
    sample_cars = [
        ("Toyota", "Corolla", 2021, 18000.00, True, "Sedan"),
        ("Honda", "Civic", 2022, 20000.00, True, "Sedan"),
        ("Ford", "Focus", 2020, 16000.00, True, "Hatchback"),
        ("Tesla", "Model 3", 2023, 35000.00, True, "Electric"),
        ("BMW", "3 Series", 2021, 30000.00, True, "Luxury Sedan"),
        ("Mercedes", "C-Class", 2022, 32000.00, False, "Luxury Sedan"),
    ]
    return sample_cars_query, sample_cars

def populate_leads():
    sample_leads_query = """
    INSERT INTO leads (name, phone_number, lead_source, interest_score, call_summary)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT DO NOTHING;
    """
    sample_leads = [
        ("Omar Laabidi", "+212612345678", "Website", 4, "Customer called and showed strong interest in Toyota Corolla."),

    ]
    return sample_leads_query, sample_leads

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

        print("Inserting car data...")
        car_query, cars_data = populate_cars()
        cursor.executemany(car_query, cars_data)
        print("Cars inserted.")

        print("Inserting lead data...")
        lead_query, leads_data = populate_leads()
        cursor.executemany(lead_query, leads_data)
        print("Leads inserted.")

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
