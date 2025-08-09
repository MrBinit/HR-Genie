from db import engine
from models import Base

# Drop all existing tables
Base.metadata.drop_all(bind=engine)

# Recreate fresh tables
Base.metadata.create_all(bind=engine)

print("Database tables dropped and recreated.")
