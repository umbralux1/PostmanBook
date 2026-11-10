"""Учебный набор тикетов ученика (глава 3: методы, пагинация, 409).

Набор фиксированный, чтобы задания были детерминированы: порядок = порядок
id, поэтому при `limit=10` тикет «SMS code not received» (14-й) всегда на 2-й странице.
Тексты — на английском (решение владельца) и одни для обеих языковых версий:
`expected` заданий у языков общий.
"""

from datetime import UTC, datetime

from sqlmodel import Session, col, delete

from app.models import Ticket, User

SMS_TICKET_TITLE = "SMS code not received"

# (title, priority, status, description)
SEED_TICKETS: tuple[tuple[str, str, str, str], ...] = (
    ("Cannot log in to my account", "high", "open", "Says 'Wrong password', but it is correct."),
    ("Password reset email not received", "medium", "open", "Checked the Spam folder."),
    ("Error 500 when paying by card", "high", "in_progress", "Money charged, no order created."),
    ("How do I change my email?", "low", "closed", "Answered with instructions."),
    ("Order list loads slowly", "medium", "open", "About 30 seconds in the evening."),
    ("Charged twice", "high", "open", "The customer clicked 'Pay' twice."),
    ("Cannot download invoice PDF", "low", "open", "The 'Download' button does nothing."),
    ("Order history disappeared", "medium", "in_progress", "After the app update."),
    ("Wrong delivery address", "medium", "closed", "Address fixed manually."),
    ("Promo code does not work", "low", "open", "Says 'Promo code is invalid'."),
    ("App crashes on startup", "high", "open", "Android 14, version 3.2.1."),
    ("Cannot attach a file to a request", "low", "open", "PNG file, 12 MB."),
    ("Order status is not updating", "medium", "open", "'Packing' for three days."),
    (SMS_TICKET_TITLE, "high", "open", "The confirmation code never arrives by SMS."),
    ("Notifications arrive twice", "low", "in_progress", "Both push and email, twice each."),
    ("Error 403 in the account", "medium", "open", "The 'Documents' section is unavailable."),
    ("Bank transfer payment fails", "high", "open", "The bank says 'Transaction declined'."),
    ("How do I delete my account?", "low", "closed", "Sent a link to the deletion form."),
    ("Wrong total in the cart", "medium", "open", "The discount was not applied."),
    ("Link from the email does not open", "low", "open", "Page '404 Not Found'."),
    ("Catalog search is slow", "medium", "open", "Search takes over 10 seconds."),
    (
        "Bonus points deducted without an order",
        "medium",
        "in_progress",
        "500 points gone yesterday.",
    ),
    ("Interface language does not change", "low", "open", "Stays RU after choosing EN."),
)


def seed_tickets(session: Session, owner: str) -> None:
    """Создать ученику учебный набор (без commit)."""
    now = datetime.now(UTC)
    for title, priority, status, description in SEED_TICKETS:
        session.add(
            Ticket(
                title=title,
                priority=priority,
                status=status,
                description=description,
                owner=owner,
                created_at=now,
                updated_at=now,
            )
        )


def ensure_seeded(session: Session, user: User) -> None:
    """Выдать набор при первом обращении ученика (повторно — только через reset)."""
    if user.tickets_seeded:
        return
    seed_tickets(session, user.student_code)
    user.tickets_seeded = True
    session.add(user)
    session.commit()


def reset_tickets(session: Session, user: User) -> None:
    """Удалить все тикеты ученика и создать набор заново."""
    session.exec(delete(Ticket).where(col(Ticket.owner) == user.student_code))
    seed_tickets(session, user.student_code)
    user.tickets_seeded = True
    session.add(user)
    session.commit()
