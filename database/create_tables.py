# This script creates the database tables defined in the models.py file.

from models import Base
from db import engine

Base.metadata.create_all(bind=engine)

