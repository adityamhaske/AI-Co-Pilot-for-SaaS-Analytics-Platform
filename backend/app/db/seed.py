import random
from datetime import datetime, timedelta
from faker import Faker
from app.db.session import SessionLocal, engine
from app.db.models import Base, Tenant, User, Customer, Subscription, Invoice, UsageEvent
from app.core.security import get_password_hash

fake = Faker()

def seed_db():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Create 3 tenants
    tenants = []
    for _ in range(3):
        tenant = Tenant(id=f"tenant_{fake.uuid4()[:8]}", name=fake.company())
        db.add(tenant)
        tenants.append(tenant)
    
    # Create fixed test tenant
    test_tenant = Tenant(id="tenant_test", name="Test Tenant")
    db.add(test_tenant)
    tenants.append(test_tenant)
    db.commit()

    # Create users for each tenant
    roles = ["admin", "analyst", "viewer"]
    for tenant in tenants:
        if tenant.id == "tenant_test":
            for role in roles:
                user = User(
                    id=f"user_{role}",
                    tenant_id=tenant.id,
                    email=f"{role}@test.com",
                    hashed_password=get_password_hash("password123"),
                    role=role
                )
                db.add(user)
        else:
            for role in roles:
                user = User(
                    id=f"user_{fake.uuid4()[:8]}",
                    tenant_id=tenant.id,
                    email=f"{role}@{tenant.name.lower().replace(' ', '')}.com",
                    hashed_password=get_password_hash("password123"),
                    role=role
                )
                db.add(user)
    db.commit()

    # Create customers, subscriptions, invoices, usage events
    for tenant in tenants:
        for _ in range(10): # 10 customers per tenant
            customer = Customer(
                id=f"cust_{fake.uuid4()[:8]}",
                tenant_id=tenant.id,
                name=fake.company(),
                segment=random.choice(["enterprise", "smb", "midmarket"])
            )
            db.add(customer)
            db.commit()

            # Create subscription
            start_date = fake.date_between(start_date='-2y', end_date='-1m')
            is_active = random.choice([True, False])
            sub = Subscription(
                id=f"sub_{fake.uuid4()[:8]}",
                tenant_id=tenant.id,
                customer_id=customer.id,
                mrr=round(random.uniform(100, 5000), 2),
                start_date=start_date,
                end_date=None if is_active else start_date + timedelta(days=random.randint(30, 300)),
                status="active" if is_active else "canceled"
            )
            db.add(sub)

            # Create invoices
            for _ in range(random.randint(1, 12)):
                inv = Invoice(
                    id=f"inv_{fake.uuid4()[:8]}",
                    tenant_id=tenant.id,
                    customer_id=customer.id,
                    amount=sub.mrr,
                    issue_date=fake.date_between(start_date='-1y', end_date='today'),
                    status=random.choice(["paid", "paid", "paid", "unpaid"])
                )
                db.add(inv)

            # Create usage events
            for _ in range(random.randint(10, 50)):
                event = UsageEvent(
                    id=f"evt_{fake.uuid4()[:8]}",
                    tenant_id=tenant.id,
                    customer_id=customer.id,
                    event_type=random.choice(["login", "report_run", "export", "dashboard_view"]),
                    timestamp=fake.date_time_between(start_date='-1y', end_date='now')
                )
                db.add(event)
    
    db.commit()
    db.close()
    print("Database seeded successfully.")

if __name__ == "__main__":
    seed_db()
