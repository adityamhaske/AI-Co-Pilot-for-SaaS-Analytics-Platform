import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.session import get_db, Base
from app.db.models import User, Tenant
from app.core.security import get_password_hash

SQLALCHEMY_DATABASE_URL = "sqlite:///./test_override.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="session", autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    del app.dependency_overrides[get_db]

@pytest.fixture
def test_user(db_session):
    # Ensure tenant exists
    tenant = db_session.query(Tenant).filter(Tenant.id == "tenant_test").first()
    if not tenant:
        tenant = Tenant(id="tenant_test", name="Test Tenant")
        db_session.add(tenant)
        db_session.commit()
    
    user = db_session.query(User).filter(User.email == "test@test.com").first()
    if not user:
        user = User(
            id="user_test",
            tenant_id=tenant.id,
            email="test@test.com",
            hashed_password=get_password_hash("password123"),
            role="viewer"
        )
        db_session.add(user)
        db_session.commit()
    return user
