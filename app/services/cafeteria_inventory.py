"""Stock posting within a transaction that locks cafeteria sites."""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import HTTPException
from sqlalchemy import func

from app.db.models.cafeteria import CafeteriaLot, CafeteriaMovement
from app.services.stock_orders import business_date


ZERO = Decimal(0)


def require(condition, message, status=400):
    if not condition:
        raise HTTPException(status, message)


def on_hand(db, site, item):
    quantity, value = db.query(func.sum(CafeteriaMovement.quantity), func.sum(CafeteriaMovement.value)).join(
        CafeteriaLot, CafeteriaMovement.lot_id == CafeteriaLot.id
    ).filter(CafeteriaLot.site == site, CafeteriaLot.item_id == item).one()
    return quantity or ZERO, value or ZERO


def movements(db, lines):
    return db.query(CafeteriaMovement).filter(
        CafeteriaMovement.line_id.in_([line.id for line in lines])
    ).order_by(CafeteriaMovement.id).all()


def post(db, actor, line, lot, quantity, value, reverses=None):
    require(lot.quantity + quantity >= 0, "批次库存不足")
    lot.quantity += quantity
    db.add(CafeteriaMovement(line_id=line.id, lot_id=lot.id, quantity=quantity, value=value,
                            reverses_id=reverses, actor_id=actor.id))


def receive(db, actor, site, line, quantity, value, source=None):
    if not quantity:
        return
    lot = CafeteriaLot(site=site, item_id=line.item_id, source_line_id=line.id,
                       source_lot_id=source.id if source else None,
                       expiry=source.expiry if source else line.expiry, quantity=ZERO)
    db.add(lot)
    db.flush()
    post(db, actor, line, lot, quantity, value)


def amount(quantity, price):
    return (quantity * price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def issue(db, actor, site, line, quantity, *, include_expired=False):
    available, value = on_hand(db, site, line.item_id)
    require(available >= quantity, f"{line.name}库存不足")
    total_cost = value if quantity == available else value * quantity / available
    remaining = quantity
    lots = db.query(CafeteriaLot).filter_by(site=site, item_id=line.item_id).filter(
        CafeteriaLot.quantity > ZERO,
    ).order_by(CafeteriaLot.expiry.is_(None), CafeteriaLot.expiry, CafeteriaLot.id).all()
    for lot in lots:
        if not include_expired and lot.expiry and lot.expiry < date.fromisoformat(business_date()):
            continue
        used = min(lot.quantity, remaining)
        cost = total_cost if used == remaining else (total_cost * used / remaining).quantize(Decimal("0.00000001"))
        post(db, actor, line, lot, -used, -cost)
        remaining -= used
        total_cost -= cost
        if not remaining:
            return
    require(not remaining, f"{line.name}可用批次不足")
