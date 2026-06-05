from fastapi.testclient import TestClient
from models import engine, db, get_db_sync, get_db_sync_for_test
from models.Ticket import Ticket
from models.User import User
from models.Payment import Payment, PaymentStatus
from models.Token import Token
from models.Voucher import Voucher
from main import app
import alembic.config
import uuid
from unittest import TestCase
from datetime import datetime, timedelta
from pytz import timezone
from core.security import generate_hash_password
from settings import TZ, SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES
import jwt


class TestTicket(TestCase):
    @classmethod
    def setUpClass(cls):
        alembic_args = ["upgrade", "head"]
        alembic.config.main(argv=alembic_args)

    def setUp(self):
        self.connection = engine.connect()
        self.trans = self.connection.begin()
        self.session = db(
            bind=self.connection, join_transaction_mode="create_savepoint"
        )

        # Create test ticket
        self.ticket = Ticket(
            id=uuid.uuid4(),
            name="Test Ticket",
            price=123456,
            user_participant_type="In Person",
            is_sold_out=False,
            is_active=True,
            description="Ini deskripsi test ticket",
        )
        self.session.add(self.ticket)
        self.session.commit()

        # Create test user
        self.test_user = User(
            username="ticketuser",
            email="ticket@example.com",
            phone="+628123456789",
            first_name="Test",
            last_name="User",
            password=generate_hash_password("password"),
            is_active=True,
            participant_type="In Person",
        )
        self.session.add(self.test_user)
        self.session.commit()

        # Create test token
        expire = datetime.now(tz=timezone(TZ)) + timedelta(
            minutes=float(ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        payload = {
            "id": str(self.test_user.id),
            "username": self.test_user.username,
            "exp": expire,
        }
        token_str = jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)
        test_token_model = Token(
            user_id=self.test_user.id, token=token_str, expired_at=expire
        )
        self.session.add(test_token_model)
        self.session.commit()
        self.test_token = token_str

        app.dependency_overrides[get_db_sync] = get_db_sync_for_test(db=self.session)
        self.client = TestClient(app)

    def tearDown(self):
        self.session.close()
        self.trans.rollback()
        self.connection.close()

    def test_list_ticket(self):
        response = self.client.get("/ticket/")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        ordered_ticket = self.session.query(Ticket).order_by(Ticket.order.asc()).all()
        ordered_ticket = [x.name for x in ordered_ticket]
        ordered_result = [x["name"] for x in data["results"]]
        self.assertListEqual(ordered_result, ordered_ticket)

    def test_get_my_ticket_without_payment(self):
        response = self.client.get(
            "/ticket/me", headers={"Authorization": f"Bearer {self.test_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"] is None
        assert data["message"] == "No ticket purchased yet"

    def test_get_my_ticket_with_payment_no_voucher(self):
        # Create paid payment
        now = datetime.now(tz=timezone(TZ))
        payment = Payment(
            user_id=self.test_user.id,
            ticket_id=self.ticket.id,
            amount=123456,
            status=PaymentStatus.PAID,
            description="Test payment",
            payment_link="https://test.com/pay",
            mayar_id="test-mayar-id",
            mayar_transaction_id="test-tx-id",
            created_at=now,
            paid_at=now,
        )
        self.session.add(payment)
        self.session.commit()

        response = self.client.get(
            "/ticket/me", headers={"Authorization": f"Bearer {self.test_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"] is not None
        assert data["message"] == "Ticket retrieved successfully"
        assert data["data"]["ticket"]["name"] == "Test Ticket"
        assert data["data"]["ticket"]["price"] == 123456
        assert data["data"]["ticket"]["participant_type"] == "In Person"
        assert data["data"]["payment"]["amount"] == 123456
        assert data["data"]["payment"]["voucher"] is None
        assert data["data"]["participant_type"] == "In Person"

    def test_get_my_ticket_with_payment_and_voucher(self):
        # Create voucher
        voucher = Voucher(
            code="TEST50",
            value=50000,
            type="student",
            quota=10,
            is_active=True,
        )
        self.session.add(voucher)
        self.session.commit()

        # Create paid payment with voucher
        now = datetime.now(tz=timezone(TZ))
        payment = Payment(
            user_id=self.test_user.id,
            ticket_id=self.ticket.id,
            voucher_id=voucher.id,
            amount=73456,  # 123456 - 50000
            status=PaymentStatus.PAID,
            description="Test payment with voucher",
            payment_link="https://test.com/pay",
            mayar_id="test-mayar-id",
            mayar_transaction_id="test-tx-id",
            created_at=now,
            paid_at=now,
        )
        self.session.add(payment)
        self.session.commit()

        # Update user participant type based on voucher
        self.test_user.participant_type = "student"
        self.session.add(self.test_user)
        self.session.commit()

        response = self.client.get(
            "/ticket/me", headers={"Authorization": f"Bearer {self.test_token}"}
        )
        assert response.status_code == 200
        data = response.json()
        assert data["data"] is not None
        assert data["message"] == "Ticket retrieved successfully"
        assert data["data"]["ticket"]["name"] == "Test Ticket"
        assert data["data"]["ticket"]["price"] == 123456
        assert data["data"]["payment"]["amount"] == 73456
        assert data["data"]["payment"]["voucher"] is not None
        assert data["data"]["payment"]["voucher"]["value"] == 50000
        assert data["data"]["payment"]["voucher"]["participant_type"] == "student"
        assert data["data"]["participant_type"] == "student"

    def test_get_my_ticket_unauthorized(self):
        response = self.client.get("/ticket/me")
        assert response.status_code == 401

    def test_get_my_ticket_with_invalid_token(self):
        response = self.client.get(
            "/ticket/me", headers={"Authorization": "Bearer invalid-token"}
        )
        assert response.status_code == 401
