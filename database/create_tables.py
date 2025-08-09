# This script creates the database tables defined in the models.py file.

from models import Base
from db import engine

Base.metadata.create_all(bind=engine)

#  # reset_db.py

# from db import engine
# from models import Base

# # Drop all existing tables
# Base.metadata.drop_all(bind=engine)

# # Recreate fresh tables
# Base.metadata.create_all(bind=engine)

# print("Database tables dropped and recreated.")
