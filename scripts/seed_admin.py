from app.database import SessionLocal
from app.auth import hash_password
from app.models import User, Role

db = SessionLocal()
admin = User(
    email="admin@edu.com",
    name="Admin",
    role=Role.admin,
    hashed_pw=hash_password("adminpassword"),
    is_active=True,
)
db.add(admin)
db.commit()
print(f"Admin created: {admin.id}")
db.close()