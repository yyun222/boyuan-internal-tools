"""Cafeteria document commands and state transitions."""

from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.db.models.cafeteria import (
    CafeteriaDocument as Document, CafeteriaEvent as Event, CafeteriaItem as Item,
    CafeteriaLine as Line, CafeteriaLot as Lot, CafeteriaMovement as Movement, CafeteriaSupplier as Supplier,
)
from app.db.models import User
from app.services.cafeteria_access import SITES, cafeteria_jobs
from app.services.cafeteria_inventory import amount, issue, movements, on_hand, post, receive, require
from app.services.stock_orders import business_date

APPROVERS = {"manager", "supervisor"}
CREATE_JOBS = {
    "purchase": {"kitchen", "buyer", *APPROVERS},
    "opening": {"store"}, "issue": {"store"}, "transfer": {"store"},
    "count": {"store", "supervisor"}, "loss": {"store", "kitchen", "supervisor"},
    "return": {"store", "buyer"}, "correction": {"store", "kitchen", "buyer", *APPROVERS},
}
ISSUERS = {"kitchen", *APPROVERS}


class LineInput(BaseModel):
    item_id: int
    quantity: Decimal = Field(ge=0, le=10**9, decimal_places=4)
    spec: str | None = Field(default=None, max_length=120)
    price: Decimal | None = Field(default=None, gt=0, le=10**9, decimal_places=4)
    supplier_id: int | None = None
    request_line_id: int | None = None
    expiry: date | None = None
    voucher: str = Field(default="", max_length=1000)


class DocumentInput(BaseModel):
    kind: Literal["purchase", "opening", "issue", "transfer", "count", "loss", "return", "correction"]
    business_date: date
    destination: str | None = None
    target_id: int | None = None
    original_id: int | None = None
    note: str = Field(default="", max_length=1000)
    lines: list[LineInput] = Field(default_factory=list, max_length=200)


class ActionInput(BaseModel):
    action: Literal["approve", "reject", "purchase", "receive", "confirm_issue", "receive_transfer", "close", "cancel"]
    version: int = Field(gt=0)
    note: str = Field(default="", max_length=1000)
    lines: list[LineInput] = Field(default_factory=list, max_length=200)
    accepted: dict[int, Decimal] = Field(default_factory=dict, max_length=200)
    verified: bool = False
    keep_remaining: bool = False
    purchase_date: date | None = None
    purchase_method: Literal["市场采购", "供应商配送"] = "市场采购"


def lines_for(db, document):
    return db.query(Line).filter_by(document_id=document.id).order_by(Line.id).all()


def record(db, user, doc, action, detail=""):
    db.add(Event(document_id=doc.id, actor_id=user.id, action=action, detail=detail))


def add_line(db, doc, data, *, purchase=False):
    item = db.get(Item, data.item_id)
    require(item is not None, "物资不存在")
    require(doc.kind == "count" or data.quantity > 0, "数量必须大于零")
    if purchase:
        require(data.price is not None and data.supplier_id and db.get(Supplier, data.supplier_id),
                "请填写有效的单价和供应商")
    elif doc.kind == "opening":
        require(data.price is not None, "期初库存必须填写单价")
    row = Line(document_id=doc.id, item_id=item.id, name=item.name, unit=item.unit,
               spec=item.spec if data.spec is None else data.spec, quantity=data.quantity,
               price=data.price if purchase or doc.kind == "opening" else None,
               expiry=data.expiry, supplier_id=data.supplier_id if purchase else None,
               request_line_id=data.request_line_id if purchase else None, voucher=data.voucher if purchase else "")
    if doc.kind == "count":
        row.book = on_hand(db, doc.site, item.id)[0]
    db.add(row)


def create(db, actor, site, payload):
    jobs = cafeteria_jobs(actor, site)
    require(jobs & CREATE_JOBS[payload.kind], "没有此业务权限", 403)
    kind = payload.kind
    if kind in {"correction", "opening", "count", "loss", "return"}:
        require(payload.note.strip(), "请填写原因")
    if kind == "transfer":
        require(payload.destination in SITES and payload.destination != site, "请选择调入食堂")
    if kind == "issue":
        target = db.get(User, payload.target_id) if payload.target_id else None
        require(target and target.id != actor.id and target.is_active and target.deleted_at is None
                and cafeteria_jobs(target, site) & ISSUERS, "请选择另一名本食堂领用人")
    doc = Document(site=site, kind=kind, business_date=payload.business_date, note=payload.note,
                   destination=payload.destination if kind == "transfer" else None,
                   target_id=payload.target_id if kind == "issue" else None, created_by=actor.id,
                   status="issue_pending" if kind == "issue" else "approval")
    if kind == "correction":
        require(payload.original_id, "请选择原单")
        original = db.get(Document, payload.original_id)
        require(original and original.site == site and original.status == "completed"
                and original.kind not in {"purchase", "correction"}, "原单不可冲销")
        if original.destination:
            require("manager" in jobs and "manager" in cafeteria_jobs(actor, original.destination),
                    "跨食堂调拨由公司负责人冲销", 403)
        require(not db.query(Document.id).filter_by(original_id=original.id, status="approval").first(),
                "原单已有待审批冲销")
        doc.original_id = original.id
    else:
        require(payload.lines and len({line.item_id for line in payload.lines}) == len(payload.lines),
                "请添加物资并合并重复行")
    db.add(doc)
    db.flush()
    if kind != "correction":
        for row in payload.lines:
            if kind == "opening":
                require(not db.query(Lot.id).filter_by(site=site, item_id=row.item_id).first(), "物资已有库存记录")
            add_line(db, doc, row)
    record(db, actor, doc, "create", payload.note)
    return {"id": doc.id}


def remaining(db, doc, lines):
    used = {}
    for request_line_id, quantity in db.query(Line.request_line_id, Line.quantity).join(
        Document, Line.document_id == Document.id
    ).filter(Document.parent_id == doc.id):
        used[request_line_id] = used.get(request_line_id, 0) + quantity
    return {line.id: max(Decimal(0), line.quantity - line.closed_quantity - used.get(line.id, 0)) for line in lines}


def purchase(db, actor, doc, requested, data):
    require(data.lines, "请填写采购明细")
    available = remaining(db, doc, requested)
    by_id = {line.id: line for line in requested}
    actual = {}
    amended = False
    for row in data.lines:
        base = by_id.get(row.request_line_id)
        require(base is not None, "采购明细必须关联本申请的物资")
        actual[base.id] = actual.get(base.id, 0) + row.quantity
        amended |= row.item_id != base.item_id or (row.spec is not None and row.spec != base.spec)
    amended |= any(actual.get(line_id, 0) != planned for line_id, planned in available.items())
    require(not amended or data.note.strip(), "请说明本次采购差异")
    batch = Document(site=doc.site, kind="batch", status="receipt", created_by=actor.id,
                     buyer_id=actor.id, parent_id=doc.id, business_date=data.purchase_date or date.fromisoformat(business_date()),
                     note=data.note, purchase_method=data.purchase_method)
    db.add(batch)
    db.flush()
    for row in data.lines:
        add_line(db, batch, row, purchase=True)
    open_qty = {line_id: max(0, quantity - actual.get(line_id, 0)) for line_id, quantity in available.items()}
    if data.keep_remaining and any(open_qty.values()):
        doc.status = "purchasing"
    else:
        for line in requested:
            line.closed_quantity += open_qty[line.id]
        doc.status = "batch_pending"
    record(db, actor, batch, "purchase", data.note)
    return batch.id


def finish_request(db, parent):
    db.flush()
    if parent.status == "batch_pending" and not db.query(Document.id).filter(
        Document.parent_id == parent.id, Document.status == "receipt"
    ).first():
        parent.status = "completed"
        parent.version += 1


def approve(db, actor, doc, lines):
    if doc.kind == "purchase":
        doc.status = "purchasing"
        return
    if doc.kind == "correction":
        original = db.get(Document, doc.original_id)
        require(original.status == "completed", "原单已经变更")
        if original.destination:
            require("manager" in cafeteria_jobs(actor, doc.site), "跨食堂调拨由公司负责人冲销", 403)
        original_lines = lines_for(db, original)
        # Remove the destination receipt before returning the source stock.
        copied = {}
        for source in original_lines:
            line = Line(document_id=doc.id, item_id=source.item_id, name=source.name,
                        unit=source.unit, spec=source.spec, quantity=source.quantity,
                        accepted=source.accepted, price=source.price, supplier_id=source.supplier_id,
                        expiry=source.expiry, voucher=source.voucher)
            db.add(line)
            copied[source.id] = line
        db.flush()
        for movement in reversed(movements(db, original_lines)):
            lot = db.get(Lot, movement.lot_id)
            post(db, actor, copied[movement.line_id], lot, -movement.quantity,
                 -movement.value, reverses=movement.id)
        original.status = "reversed"
        original.version += 1
        record(db, actor, original, "reversed", str(doc.id))
    for line in lines:
        if doc.kind == "opening":
            require(not db.query(Lot.id).filter_by(site=doc.site, item_id=line.item_id).first(), "物资已有库存记录")
            receive(db, actor, doc.site, line, line.quantity, amount(line.quantity, line.price))
        elif doc.kind == "count":
            current, value = on_hand(db, doc.site, line.item_id)
            require(current == line.book, "盘点后库存已变化，请重新盘点")
            delta = line.quantity - current
            if delta > 0:
                require(current > 0, "盘盈缺少成本依据")
                receive(db, actor, doc.site, line, delta, delta * value / current)
            elif delta < 0:
                issue(db, actor, doc.site, line, -delta, include_expired=True)
        else:
            issue(db, actor, doc.site, line, line.quantity, include_expired=doc.kind in {"loss", "return"})
    doc.status = "transit" if doc.kind == "transfer" else "completed"


def transition(db, actor, site, doc_id, data):
    doc = db.get(Document, doc_id)
    action = data.action
    require(doc and (doc.destination if action == "receive_transfer" else doc.site) == site, "单据不存在", 404)
    require(doc.version == data.version, "单据已变更，请刷新", 409)
    jobs = cafeteria_jobs(actor, site)
    lines = lines_for(db, doc)
    result = {"id": doc.id}
    if action in {"approve", "reject"}:
        require(jobs & APPROVERS and actor.id != doc.created_by, "审批必须由另一名有权限人员办理", 403)
        require(doc.status == "approval", "当前状态不能审批")
        if action == "approve":
            approve(db, actor, doc, lines)
        else:
            require(data.note.strip(), "请填写退回原因")
            doc.status = "rejected"
    elif action in {"purchase", "close"}:
        require("buyer" in jobs, "仅采购员可以登记采购", 403)
        require(doc.kind == "purchase" and doc.status == "purchasing", "当前状态不能登记采购")
        if action == "purchase":
            result["batchId"] = purchase(db, actor, doc, lines, data)
        else:
            require(data.note.strip() and db.query(Document.id).filter_by(parent_id=doc.id).first(),
                    "请填写结束原因，并先登记至少一批采购")
            available = remaining(db, doc, lines)
            for line in lines:
                line.closed_quantity += available[line.id]
            doc.status = "batch_pending"
            finish_request(db, doc)
    elif action == "receive":
        require("store" in jobs and actor.id != doc.buyer_id, "采购人不能验收自己的采购", 403)
        require(doc.status == "receipt" and data.verified and set(data.accepted) == {line.id for line in lines},
                "请现场核对并填写各项实收数量")
        for line in lines:
            quantity = data.accepted[line.id]
            require(quantity.is_finite() and 0 <= quantity <= line.quantity
                    and quantity == quantity.quantize(Decimal("0.0001")), "实收数量无效")
            require(quantity == line.quantity or data.note.strip(), "请填写验收差异原因")
            line.accepted = quantity
            receive(db, actor, site, line, quantity, amount(quantity, line.price))
        doc.receiver_id = actor.id
        doc.status = "completed"
        finish_request(db, db.get(Document, doc.parent_id))
    elif action == "confirm_issue":
        require(actor.id == doc.target_id and jobs & ISSUERS, "仅指定领用人可以确认", 403)
        require(doc.status == "issue_pending", "当前状态不能领用")
        for line in lines:
            issue(db, actor, site, line, line.quantity)
        doc.status = "completed"
    elif action == "receive_transfer":
        require("store" in jobs and actor.id != doc.created_by, "请由调入食堂另一名仓管确认", 403)
        require(doc.status == "transit", "当前状态不能接收")
        by_id = {line.id: line for line in lines}
        for movement in movements(db, lines):
            lot = db.get(Lot, movement.lot_id)
            receive(db, actor, site, by_id[movement.line_id], -movement.quantity, -movement.value, lot)
        doc.receiver_id = actor.id
        doc.status = "completed"
    else:
        require(actor.id == doc.created_by, "只能撤销本人发起的单据", 403)
        require(doc.status in {"approval", "issue_pending", "rejected"} and data.note.strip(), "当前无法撤销或缺少原因")
        doc.status = "cancelled"
    doc.version += 1
    record(db, actor, doc, action, data.note)
    return result
