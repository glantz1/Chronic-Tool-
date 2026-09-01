from sqlalchemy import create_engine, text

NEON_URL = "postgresql://neondb_owner:npg_2wIqHou6gmyK@ep-fragrant-dust-ax9hfa0o-pooler.c-4.us-east-2.aws.neon.tech/neondb?sslmode=require"

engine = create_engine(NEON_URL)

with engine.begin() as conn:
    conn.execute(text("ALTER TABLE schools ADD COLUMN IF NOT EXISTS owner_id INTEGER;"))
    print("Checked/Added owner_id column in Neon PostgreSQL.")

    admin_result = conn.execute(text("SELECT id FROM users WHERE role = 'admin' LIMIT 1;")).fetchone()
    
    if not admin_result:
        print("ALERT: Admin account not found in Neon database.")
    else:
        admin_id = admin_result[0]
        schools_result = conn.execute(text("SELECT COUNT(*) FROM schools;")).scalar()
        print(f"STATUS: Found {schools_result} existing schools in Neon database.")
        
        if schools_result > 0:
            conn.execute(text("UPDATE schools SET owner_id = :admin_id WHERE owner_id IS NULL;"), {"admin_id": admin_id})
            first_school = conn.execute(text("SELECT id FROM schools LIMIT 1;")).scalar()
            conn.execute(text("UPDATE users SET school_id = :school_id WHERE id = :admin_id AND school_id IS NULL;"), 
                         {"school_id": first_school, "admin_id": admin_id})
            print("SUCCESS: Linked all orphan schools to your SuperAdmin account!")
