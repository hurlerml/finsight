"""Seed system categories and default keyword rules."""

from sqlmodel import Session, select

from app.models import Category, CategoryRule
from app.services.secure_labels import (
    decode_category,
    decode_rule,
    insert_category_payload,
    insert_rule_payload,
)
from app.services.secure_data import ENCRYPTION_VERSION, encrypt_payload, private_name_index
from sqlalchemy import update

# Hex mirrors frontend theme (index.css --cat-*). UI reads CSS vars; DB kept in sync for API.
SEED_CATEGORIES: list[tuple[str, str, str, str, str, str]] = [
    ("Housing", "housing", "#b8cbee", "housing", "house", "Rent, utilities, home maintenance, and other costs of living at home."),
    ("Groceries", "groceries", "#bfd4ae", "groceries", "basket", "Food and everyday household goods bought primarily for use at home."),
    ("Dining", "dining", "#e7c6ae", "dining", "utensils", "Restaurants, cafés, bars, take-away food, and food delivery."),
    ("Mobility", "mobility", "#b4d3e6", "mobility", "car", "Public transport, fuel, vehicle costs, taxis, parking, and local travel."),
    ("Health", "health", "#e7c2d0", "health", "heart", "Medical care, pharmacies, therapy, health insurance, and health-related purchases."),
    ("Subscriptions", "subscriptions", "#c9bee0", "subscriptions", "repeat", "Recurring digital or physical services and memberships."),
    ("Shopping", "shopping", "#d6c3df", "shopping", "bag", "Physical goods such as clothing, electronics, furniture, and general retail purchases."),
    ("Leisure & Culture", "leisure", "#add2c5", "leisure", "culture", "Experiences and entertainment such as cinema, theatre, concerts, games, and hobbies."),
    ("Travel", "travel", "#b8cbee", "travel", "plane", "Trips away from home, including accommodation, flights, and travel services."),
    ("Family & Personal", "family", "#e7c2d0", "family", "users", "Personal care, gifts, family support, and other personal expenses."),
    ("Education & Work", "education", "#b6d5d0", "education", "education", "Courses, books, training, work equipment, and professional services."),
    ("Savings & Investments", "savings", "#b7d5c3", "savings", "savings", "Money moved into savings, brokerage accounts, investments, or other wealth-building products."),
    ("Finance & Government", "finance", "#c8c9c5", "finance", "finance", "Bank fees, taxes, public authorities, insurance not covered elsewhere, and financial services."),
    ("Income", "income", "#b8d2a9", "income", "income", "Salary, refunds, interest, dividends, and other incoming money."),
    ("Other", "other", "#c7ccd0", "other", "other", "Transactions that do not fit a more specific category after reasonable investigation."),
]

# Keyword rules for booking text (merchant names + common bank purpose words).
SEED_RULES: list[tuple[str, str, bool, int]] = [
    ("income", "gehalt", False, 10),
    ("income", "lohn", False, 10),
    ("income", "salary", False, 10),
    ("housing", "miete", False, 20),
    ("housing", "rent", False, 20),
    ("housing", "nebenkosten", False, 20),
    ("groceries", "rewe", False, 30),
    ("groceries", "aldi", False, 30),
    ("groceries", "lidl", False, 30),
    ("groceries", "edeka", False, 30),
    ("mobility", "db bahn", False, 40),
    ("mobility", "deutsche bahn", False, 40),
    ("mobility", "uber", False, 40),
    ("mobility", "shell", False, 40),
    ("subscriptions", "spotify", False, 50),
    ("subscriptions", "netflix", False, 50),
    ("subscriptions", "apple.com/bill", False, 50),
    ("subscriptions", "apl*apple", False, 50),
    ("dining", "lieferando", False, 60),
    ("dining", "mcdonald", False, 60),
    ("shopping", "amazon", False, 70),
    ("health", "apotheke", False, 80),
    ("health", "pharmacy", False, 80),
    ("travel", "hotel", False, 85),
    ("travel", "airbnb", False, 85),
    ("travel", "booking.com", False, 85),
    ("travel", "lufthansa", False, 85),
    ("education", "udemy", False, 90),
    ("education", "coursera", False, 90),
    ("finance", "finanzamt", False, 95),
    ("finance", "kontofuehrung", False, 95),
]


def seed_categories(
    session: Session,
    dek: bytes | None = None,
    *,
    commit: bool = True,
) -> None:
    """Ensure system categories/rules exist.

    Without a DEK (startup while vault locked) this is a no-op — private label
    data can only be written after unlock. Call again from vault setup/unlock
    with the DEK before the encryption audit.
    """
    if dek is None:
        return

    slug_to_id: dict[str, int] = {}
    for name, slug, color, color_key, icon, description in SEED_CATEGORIES:
        existing = session.exec(select(Category).where(Category.slug == slug)).first()
        if existing is None:
            row = insert_category_payload(
                session,
                dek,
                name=name,
                slug=slug,
                color=color,
                color_key=color_key,
                icon=icon,
                description=description,
                is_system=True,
            )
            slug_to_id[slug] = row.id  # type: ignore[assignment]
            continue

        if existing.id is None:
            continue
        if existing.encrypted_payload is None:
            session.execute(
                update(Category)
                .where(Category.id == existing.id)
                .values(
                    encrypted_payload=encrypt_payload(
                        dek,
                        domain="category",
                        record_id=existing.id,
                        payload={
                            "name": name,
                            "description": description,
                            "color": color,
                            "color_key": color_key,
                            "icon": icon,
                        },
                    ),
                    encryption_version=ENCRYPTION_VERSION,
                    name_blind=private_name_index(dek, "category", name),
                    is_system=True,
                )
            )
            session.flush()
        else:
            private = decode_category(existing, dek)
            if existing.is_system and (
                private.color != color
                or private.color_key != color_key
                or private.icon != icon
                or private.description != description
            ):
                session.execute(
                    update(Category)
                    .where(Category.id == existing.id)
                    .values(
                        encrypted_payload=encrypt_payload(
                            dek,
                            domain="category",
                            record_id=existing.id,
                            payload={
                                "name": private.name or name,
                                "description": description,
                                "color": color,
                                "color_key": color_key,
                                "icon": icon,
                            },
                        ),
                        encryption_version=ENCRYPTION_VERSION,
                        name_blind=private_name_index(
                            dek, "category", private.name or name
                        ),
                    )
                )
                session.flush()
                session.expire(existing)
        slug_to_id[slug] = existing.id

    session.flush()

    existing_rules = list(session.exec(select(CategoryRule)).all())
    existing_patterns: set[tuple[int, str]] = set()
    for rule in existing_rules:
        if rule.encrypted_payload is None or rule.id is None:
            continue
        private = decode_rule(rule, dek)
        existing_patterns.add((private.category_id, private.pattern.lower()))

    for slug, pattern, is_regex, priority in SEED_RULES:
        cat_id = slug_to_id.get(slug)
        if cat_id is None:
            continue
        if (cat_id, pattern.lower()) in existing_patterns:
            continue
        insert_rule_payload(
            session,
            dek,
            category_id=cat_id,
            pattern=pattern,
            is_regex=is_regex,
            priority=priority,
        )
    if commit:
        session.commit()
    else:
        session.flush()
