import traceback
from typing import Optional

from fastapi import APIRouter, Depends, Header
from opentelemetry import trace
from sqlalchemy.orm import Session

from core.log import logger
from core.mayar_service import MayarService
from core.otel_metrics import (
    payment_created_counter,
    payment_status_counter,
    payment_webhook_counter,
)
from core.telemetry import amount_bucket, get_tracer
from core.responses import (
    BadRequest,
    Forbidden,
    InternalServerError,
    Ok,
    Unauthorized,
    common_response,
)
from core.security import get_user_from_token, oauth2_scheme
from models import get_db_sync
from models.Payment import PaymentStatus
from models.Ticket import Ticket as TicketModel
from models.User import User as UserModel
from models.Voucher import Voucher as VoucherModel
from repository import (
    payment as paymentRepo,
)
from repository import (
    ticket as ticketRepo,
)
from repository import (
    voucher as voucherRepo,
)
from schemas.common import (
    BadRequestResponse,
    ForbiddenResponse,
    InternalServerErrorResponse,
    UnauthorizedResponse,
)
from schemas.payment import (
    CreatePaymentRequest,
    CreatePaymentResponse,
    DetailPaymentResponse,
    PaymentListResponse,
    VoucherInfo,
    VoucherValidateResponse,
)
from schemas.payment import (
    Ticket as TicketSchema,
)
from schemas.payment import (
    User as UserSchema,
)
from schemas.payment import (
    Voucher as VoucherSchema,
)
from settings import (
    FRONTEND_BASE_URL,
    MAYAR_API_KEY,
    MAYAR_BASE_URL,
    MAYAR_WEBHOOK_SECRET,
)

router = APIRouter(prefix="/payment", tags=["Payment"])

tracer = get_tracer("payment")


async def close_unpaid_payments_with_mayar(
    db: Session,
    user_id: str,
    exclude_payment_id: str,
    mayar_service: MayarService,
) -> int:
    with tracer.start_as_current_span("payment.close_unpaid_batch") as span:
        payments_to_close = paymentRepo.get_payments_by_user_id(
            db=db,
            user_id=user_id,
            status=PaymentStatus.UNPAID,
            exclude_payment_id=exclude_payment_id,
        )

        closed_count = 0
        for payment in payments_to_close:
            if payment.mayar_id:
                try:
                    await mayar_service.close_payment(payment_id=payment.mayar_id)
                    logger.info(
                        f"Closed payment {payment.id} in Mayar (mayar_id: {payment.mayar_id})"
                    )
                except Exception as e:
                    logger.error(f"Failed to close payment {payment.id} in Mayar: {e}")

            paymentRepo.update_payment(
                db=db,
                payment=payment,
                status=PaymentStatus.CLOSED,
                is_commit=False,
            )
            closed_count += 1

        span.set_attribute("payment.close_count", closed_count)
        return closed_count


@router.get(
    "/voucher/validate",
    responses={
        "200": {"model": VoucherValidateResponse},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def validate_voucher(
    code: str,
    db: Session = Depends(get_db_sync),
    token: str = Depends(oauth2_scheme),
):
    try:
        user = get_user_from_token(db=db, token=token)
        if user is None:
            return common_response(Unauthorized(message="Unauthorized"))

        if not user.email:
            return common_response(
                BadRequest(
                    message="Users must complete their email address first. Please update your profile."
                )
            )

        voucher = voucherRepo.get_voucher_by_code(db=db, code=code)

        if not voucher:
            return common_response(BadRequest(message="Invalid voucher code."))

        if not voucher.is_active:
            return common_response(BadRequest(message="Voucher is no longer valid."))

        if voucher.quota <= 0:
            return common_response(
                BadRequest(message="Voucher quota has been exhausted.")
            )

        if voucher.email_whitelist:
            whitelist = voucher.email_whitelist.get("emails", [])

            whitelist_normalized = {
                e.strip().lower() for e in whitelist if isinstance(e, str)
            }
            user_email_normalized = user.email.strip().lower()
            if (
                whitelist_normalized
                and user_email_normalized not in whitelist_normalized
            ):
                return common_response(
                    BadRequest(message="You are not authorized to use this voucher.")
                )

        return common_response(
            Ok(
                data=VoucherValidateResponse(
                    code=voucher.code,
                    value=voucher.value,
                    type=voucher.type,
                ).model_dump(mode="json")
            )
        )

    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in validate_voucher: {e}")
        return common_response(InternalServerError(error="Internal Server Error"))


@router.post(
    "/",
    responses={
        "200": {"model": CreatePaymentResponse},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def create_payment(
    request: CreatePaymentRequest,
    db: Session = Depends(get_db_sync),
    token: str = Depends(oauth2_scheme),
):
    span = tracer.start_span("payment.create")
    span_context = trace.use_span(span, end_on_exit=True)
    span_context.__enter__()
    try:
        user = get_user_from_token(db=db, token=token)
        if user is None:
            return common_response(Unauthorized(message="Unauthorized"))

        if not user.email:
            return common_response(
                BadRequest(
                    message="Users must complete their email address first. Please update your profile."
                )
            )

        if not user.phone:
            return common_response(
                BadRequest(
                    message="Users must complete their phone number first. Please update your profile."
                )
            )

        checked_payment = paymentRepo.get_user_paid_payment(
            db=db,
            user_id=str(user.id),
        )
        if checked_payment:
            return common_response(
                BadRequest(message="You have already made a paid payment.")
            )

        ticket = ticketRepo.get_active_ticket_by_id(db=db, ticket_id=request.ticket_id)
        if not ticket:
            db.rollback()
            return common_response(BadRequest(message="Ticket not found."))

        if ticket.is_sold_out:
            db.rollback()
            return common_response(BadRequest(message="Ticket is sold out."))

        voucher = None
        voucher_participant_type = None
        if request.voucher_code:
            voucher, error_msg = voucherRepo.validate_and_use_voucher(
                db=db, code=request.voucher_code, user_email=user.email
            )
            if error_msg or voucher is None:
                db.rollback()
                return common_response(
                    BadRequest(message=error_msg or "Invalid voucher code.")
                )

            if voucher.type:
                voucher_participant_type = voucher.type

        amount = ticket.price
        if voucher:
            # Apply voucher discount to amount, maximum to 0
            amount = max(0, amount - voucher.value)

        description = ticket.description or ticket.name
        status = PaymentStatus.UNPAID

        payment = paymentRepo.create_payment(
            db=db,
            user_id=str(user.id),
            amount=amount,
            ticket_id=str(ticket.id),
            description=description,
            status=status,
            voucher_id=str(voucher.id) if voucher else None,
            is_commit=False,
        )
        span.set_attribute("payment.id", str(payment.id))
        span.set_attribute("ticket.id", str(ticket.id))
        span.set_attribute("payment.amount_bucket", amount_bucket(amount))
        span.set_attribute("payment.has_voucher", voucher is not None)

        if amount <= 0:
            user.participant_type = (
                voucher_participant_type or ticket.user_participant_type
            )
            db.add(user)
            paymentRepo.update_payment(
                db=db,
                payment=payment,
                status=PaymentStatus.PAID,
            )
            db.commit()
            db.refresh(payment)

            span.set_attribute("payment.status", str(payment.status))
            payment_created_counter.add(
                1,
                {
                    "ticket.name": ticket.name,
                    "has_voucher": str(voucher is not None),
                },
            )
            return common_response(
                Ok(
                    data=CreatePaymentResponse(
                        id=str(payment.id),
                        payment_link=None,
                        created_at=payment.created_at,
                        amount=payment.amount,
                        description=payment.description,
                        ticket=TicketSchema(
                            id=str(ticket.id),
                            name=ticket.name,
                            participant_type=ticket.user_participant_type,
                        ),
                        voucher=VoucherSchema(
                            code=voucher.code,
                            value=voucher.value,
                            participant_type=voucher.type,
                        )
                        if voucher
                        else None,
                    ).model_dump(mode="json")
                )
            )

        mayar_service = MayarService(api_key=MAYAR_API_KEY, base_url=MAYAR_BASE_URL)

        try:
            customer_name = user.username
            if user.first_name or user.last_name:
                customer_name = (
                    f"{user.first_name or ''} {user.last_name or ''}".strip()
                )

            with tracer.start_as_current_span("mayar.create_payment"):
                mayar_response = await mayar_service.create_payment(
                    ticket=ticket,
                    customer_email=user.email,
                    customer_name=customer_name,
                    customer_phone=user.phone,
                    tx_internal_id=str(payment.id),
                    voucher=voucher,
                )

            data = mayar_response.get("data", {})
            payment_link = data.get("link", "")
            mayar_id = data.get("id", "")
            mayar_transaction_id = data.get("transactionId", "")
        except Exception as e:
            db.rollback()
            logger.error(f"Error creating payment in Mayar: {e}")
            return common_response(
                InternalServerError(
                    error="Failed to make a payment on Mayar. Please try again."
                )
            )

        paymentRepo.update_payment(
            db=db,
            payment=payment,
            payment_link=payment_link,
            mayar_id=mayar_id,
            mayar_transaction_id=mayar_transaction_id,
        )

        db.commit()
        db.refresh(payment)

        span.set_attribute("payment.status", str(payment.status))
        payment_created_counter.add(
            1,
            {
                "ticket.name": ticket.name,
                "has_voucher": str(voucher is not None),
            },
        )
        return common_response(
            Ok(
                data=CreatePaymentResponse(
                    id=str(payment.id),
                    payment_link=payment.payment_link,
                    created_at=payment.created_at,
                    amount=payment.amount,
                    description=payment.description,
                    ticket=TicketSchema(
                        id=str(ticket.id),
                        name=ticket.name,
                        participant_type=ticket.user_participant_type,
                    ),
                    voucher=VoucherSchema(
                        code=voucher.code,
                        value=voucher.value,
                        participant_type=voucher.type,
                    )
                    if voucher
                    else None,
                ).model_dump(mode="json")
            )
        )
    except Exception as e:
        db.rollback()
        traceback.print_exc()
        logger.error(f"Error in create_payment: {e}")
        return common_response(InternalServerError(error="Internal Server Error"))
    finally:
        span_context.__exit__(None, None, None)


@router.get(
    "/",
    responses={
        "200": {"model": PaymentListResponse},
        "401": {"model": UnauthorizedResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def list_payments(
    db: Session = Depends(get_db_sync),
    token: str = Depends(oauth2_scheme),
):
    try:
        user = get_user_from_token(db=db, token=token)
        if user is None:
            return common_response(Unauthorized(message="Unauthorized"))

        payments = paymentRepo.get_payments_by_user_id(db=db, user_id=str(user.id))

        results = []

        for payment in payments:
            payment_link: Optional[str] = payment.payment_link
            if payment.status == PaymentStatus.PAID:
                payment_link = (
                    f"{FRONTEND_BASE_URL}/auth/user-ticket"
                    if FRONTEND_BASE_URL
                    else None
                )
            elif payment.status == PaymentStatus.CLOSED:
                payment_link = None

            results.append(
                DetailPaymentResponse(
                    id=str(payment.id),
                    user=UserSchema(
                        id=str(user.id),
                        first_name=user.first_name,
                        last_name=user.last_name,
                        t_shirt_size=user.t_shirt_size,
                    ),
                    payment_link=payment_link,
                    status=payment.status,
                    created_at=payment.created_at,
                    paid_at=payment.paid_at,
                    closed_at=payment.closed_at,
                    amount=payment.amount,
                    description=payment.description,
                    ticket=TicketSchema(
                        id=str(payment.ticket.id),
                        name=payment.ticket.name,
                        participant_type=payment.ticket.user_participant_type,
                    ),
                    voucher=(
                        VoucherInfo(
                            value=payment.voucher.value,
                            participant_type=payment.voucher.type,
                        )
                        if payment.voucher
                        else None
                    ),
                    participant_type=(
                        payment.voucher.type
                        if payment.voucher and payment.voucher.type
                        else payment.ticket.user_participant_type
                    ),
                )
            )

        return common_response(
            Ok(data=PaymentListResponse(results=results).model_dump(mode="json"))
        )
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in list_payments: {e}")
        return common_response(
            InternalServerError(error=f"Internal Server Error: {str(e)}")
        )


@router.get(
    "/{payment_id}",
    responses={
        "200": {"model": DetailPaymentResponse},
        "400": {"model": BadRequestResponse},
        "401": {"model": UnauthorizedResponse},
        "403": {"model": ForbiddenResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def get_payment_detail(
    payment_id: str,
    db: Session = Depends(get_db_sync),
    token: str = Depends(oauth2_scheme),
):
    try:
        user = get_user_from_token(db=db, token=token)
        if user is None:
            return common_response(Unauthorized(message="Unauthorized"))

        payment = paymentRepo.get_payment_by_id(db=db, payment_id=payment_id)

        if not payment:
            return common_response(BadRequest(message="Payment not found"))

        if str(payment.user_id) != str(user.id):
            return common_response(
                Forbidden(
                    custom_response={
                        "message": "You do not have access to this payment"
                    }
                )
            )

        mayar_service = MayarService(api_key=MAYAR_API_KEY, base_url=MAYAR_BASE_URL)
        try:
            if payment.mayar_id and payment.status == PaymentStatus.UNPAID:
                with tracer.start_as_current_span("mayar.get_payment_status"):
                    mayar_status_response = await mayar_service.get_payment_status(
                        payment_id=payment.mayar_id
                    )
                data = mayar_status_response.get("data", {})
                transaction_status = data.get("status", "").lower()

                status_mapping = {
                    "unpaid": PaymentStatus.UNPAID,
                    "paid": PaymentStatus.PAID,
                    "closed": PaymentStatus.CLOSED,
                }
                status = status_mapping.get(transaction_status, PaymentStatus.UNPAID)

                if status != payment.status:
                    if status == PaymentStatus.PAID:
                        ticket: TicketModel = payment.ticket
                        voucher: VoucherModel = payment.voucher

                        if voucher and voucher.type:
                            user.participant_type = voucher.type
                        else:
                            user.participant_type = ticket.user_participant_type
                        db.add(user)

                        closed_count = await close_unpaid_payments_with_mayar(
                            db=db,
                            user_id=str(user.id),
                            exclude_payment_id=payment_id,
                            mayar_service=mayar_service,
                        )
                        if closed_count > 0:
                            logger.info(
                                f"Closed {closed_count} other unpaid payment(s) for user {user.id}"
                            )

                    paymentRepo.update_payment(
                        db=db,
                        payment=payment,
                        status=status,
                    )
                    db.commit()
                    db.refresh(payment)
        except Exception as e:
            logger.error(f"Error fetching payment status from Mayar: {e}")

        payment_link: Optional[str] = payment.payment_link
        if payment.status == PaymentStatus.PAID:
            payment_link = (
                f"{FRONTEND_BASE_URL}/auth/user-ticket" if FRONTEND_BASE_URL else None
            )
        elif payment.status == PaymentStatus.CLOSED:
            payment_link = None

        return common_response(
            Ok(
                data=DetailPaymentResponse(
                    id=str(payment.id),
                    user=UserSchema(
                        id=str(user.id),
                        first_name=user.first_name,
                        last_name=user.last_name,
                        t_shirt_size=user.t_shirt_size,
                    ),
                    payment_link=payment_link,
                    status=payment.status,
                    created_at=payment.created_at,
                    paid_at=payment.paid_at,
                    closed_at=payment.closed_at,
                    amount=payment.amount,
                    description=payment.description,
                    ticket=TicketSchema(
                        id=str(payment.ticket.id),
                        name=payment.ticket.name,
                        participant_type=payment.ticket.user_participant_type,
                    ),
                    voucher=(
                        VoucherInfo(
                            value=payment.voucher.value,
                            participant_type=payment.voucher.type,
                        )
                        if payment.voucher
                        else None
                    ),
                    participant_type=(
                        payment.voucher.type
                        if payment.voucher and payment.voucher.type
                        else payment.ticket.user_participant_type
                    ),
                ).model_dump(mode="json")
            )
        )

    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in get_payment_detail: {e}")
        return common_response(
            InternalServerError(error=f"Internal Server Error: {str(e)}")
        )


@router.post(
    "/webhook",
    responses={
        "200": {"description": "Webhook processed successfully"},
        "400": {"model": BadRequestResponse},
        "500": {"model": InternalServerErrorResponse},
    },
)
async def payment_webhook(
    request: dict,
    db: Session = Depends(get_db_sync),
    x_callback_token: str = Header(None, alias="x-callback-token"),
):
    try:
        if not x_callback_token:
            return common_response(
                BadRequest(message="Missing X-Callback-Token header")
            )

        if x_callback_token != MAYAR_WEBHOOK_SECRET:
            return common_response(BadRequest(message="Invalid request token"))

        event = request.get("event")
        data = request.get("data", {})
        if event == "payment.received" and data:
            with tracer.start_as_current_span("payment.webhook") as webhook_span:
                payment_webhook_counter.add(1, {"event": event})
                webhook_span.set_attribute("webhook.event", event)
                mayar_id = data.get("id")
                mayar_transaction_id = data.get("transactionId")
                transaction_status = data.get("status", "").lower()

                if not mayar_id and not mayar_transaction_id:
                    return common_response(
                        BadRequest(message="id or transactionId is required")
                    )

                status_mapping = {"success": PaymentStatus.PAID}

                status = status_mapping.get(transaction_status, PaymentStatus.UNPAID)

                payment = None
                if mayar_transaction_id:
                    payment = paymentRepo.get_payment_by_mayar_transaction_id(
                        db=db, mayar_transaction_id=mayar_transaction_id
                    )

                if not payment and mayar_id:
                    payment = paymentRepo.get_payment_by_mayar_id(
                        db=db, mayar_id=mayar_id
                    )

                if not payment:
                    logger.warning(
                        f"Payment not found for mayar_id: {mayar_id}, transactionId: {mayar_transaction_id}"
                    )
                    return common_response(BadRequest(message="Payment not found"))

                status_before = str(payment.status)
                webhook_span.set_attribute("payment.id", str(payment.id))
                webhook_span.set_attribute("payment.status_before", status_before)

                paymentRepo.update_payment(
                    db=db,
                    payment=payment,
                    status=status,
                    mayar_id=mayar_id,
                    mayar_transaction_id=mayar_transaction_id,
                    is_commit=False,
                )
                user: UserModel = payment.user
                ticket: TicketModel = payment.ticket
                voucher: VoucherModel = payment.voucher

                if status == PaymentStatus.PAID:
                    if voucher and voucher.type:
                        user.participant_type = voucher.type
                    else:
                        user.participant_type = ticket.user_participant_type
                    db.add(user)

                    mayar_service = MayarService(
                        api_key=MAYAR_API_KEY, base_url=MAYAR_BASE_URL
                    )
                    closed_count = await close_unpaid_payments_with_mayar(
                        db=db,
                        user_id=str(user.id),
                        exclude_payment_id=str(payment.id),
                        mayar_service=mayar_service,
                    )
                    if closed_count > 0:
                        logger.info(
                            f"Closed {closed_count} other unpaid payment(s) for user {user.id}"
                        )

                db.commit()
                webhook_span.set_attribute("payment.status_after", str(status))
                payment_status_counter.add(
                    1,
                    {"from_status": status_before, "to_status": str(status)},
                )
                logger.info(
                    f"Payment {payment.id} updated to status {status} via webhook"
                )

        return common_response(Ok(data={"message": "Webhook processed successfully"}))
    except Exception as e:
        traceback.print_exc()
        logger.error(f"Error in payment_webhook: {e}")
        return common_response(
            InternalServerError(error=f"Internal Server Error: {str(e)}")
        )
