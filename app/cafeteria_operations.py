"""HTTP interface for cafeteria catalogs, inventory and documents."""

import csv
import hashlib
import io
import json
from decimal import Decimal
from urllib.parse import quote
from datetime import date
from typing import Literal

from fastapi import Depends, File, Form, Header, Query, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.auth import utcnow
from app.db import get_db
from app.db.models import User
from app.db.models.cafeteria import (
    CafeteriaDocument as Document, CafeteriaEvent as Event, CafeteriaItem as Item,
    CafeteriaLine as Line, CafeteriaLot as Lot, CafeteriaMovement as Movement, CafeteriaRequest as Receipt,
    CafeteriaSite as Site, CafeteriaSupplier as Supplier, CafeteriaFile as StoredFile, CafeteriaMeal as Meal,
)
from app.services.cafeteria_access import SITES, cafeteria_jobs
from app.services.cafeteria_documents import (
    CREATE_JOBS, ISSUERS, ActionInput, DocumentInput, LineInput, create, lines_for, remaining, transition,
)
from app.services.cafeteria_inventory import require
from app.services.cafeteria_meals import PRICES, csv_rows, parse


class ItemInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    unit: Literal["斤", "个", "瓶", "袋", "桶", "箱", "包", "升"]
    spec: str = Field(default="", max_length=120)
    category: str = Field(default="其他食品类", min_length=1, max_length=40)


class SupplierInput(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_type: Literal["有名商户", "无名固定菜商", "临时菜商"]
    location: str = Field(default="", max_length=120)
    contact: str = Field(default="", max_length=120)


def columns(row, names):
    return {name: getattr(row, name) for name in names.split()}


def register_operations(app, require_user):
    prefix = "/api/cafeteria/{site}"

    def authorize(db, request, site, *, write=False):
        require(site in SITES, "食堂不存在", 404)
        if write and request.session.get("user_id"):
            # One ordered lock for both sites also serializes transfers and shared catalogs.
            db.query(Site).filter(Site.code.in_(SITES)).order_by(Site.code).with_for_update().all()
        user = require_user(request, db)
        jobs = cafeteria_jobs(user, site)
        require(jobs, "没有此食堂权限", 403)
        return user, jobs

    def mutate(db, user, key, scope, payload, operation):
        require(key.strip(), "缺少请求编号")
        digest = hashlib.sha256((scope + payload.model_dump_json()).encode()).hexdigest()
        old = db.get(Receipt, (user.id, key))
        if old:
            require(old.digest == digest, "此请求编号已使用", 409)
            return old.response
        result = operation()
        db.add(Receipt(user_id=user.id, key=key, digest=digest, response=result))
        db.commit()
        return result

    @app.get(prefix + "/catalog")
    def catalog(site: str, request: Request, db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site)
        users = []
        if "store" in jobs:
            candidates = db.query(User).filter(User.deleted_at.is_(None), User.is_active.is_(True)).all()
            users = [{"id": user.id, "name": user.display_name} for user in candidates
                     if cafeteria_jobs(user, site) & ISSUERS]
        return {
            "items": [columns(row, "id name unit spec category") for row in db.query(Item).order_by(Item.name, Item.id)],
            "suppliers": [columns(row, "id name source_type location contact") for row in db.query(Supplier).order_by(Supplier.name)],
            "recipients": users,
            "createKinds": [kind for kind, allowed in CREATE_JOBS.items() if jobs & allowed],
        }

    @app.post(prefix + "/items")
    def items(site: str, payload: list[ItemInput], request: Request, db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site, write=True)
        require(jobs & {"admin", "manager"} or len(payload) == 1 and jobs & {"buyer", "store", "kitchen", "supervisor"},
                "没有物资目录维护权限", 403)
        require(0 < len(payload) <= 2000, "导入行数无效")
        count = 0
        for row in payload:
            values = {key: value.strip() for key, value in row.model_dump().items()}
            require(values["name"], "物资名称不能为空")
            if not db.query(Item.id).filter_by(**{key: values[key] for key in ("name", "unit", "spec")}).first():
                db.add(Item(**values))
                db.flush()
                count += 1
        db.commit()
        return {"count": count}

    @app.post(prefix + "/suppliers")
    def suppliers(site: str, payload: list[SupplierInput], request: Request, db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site, write=True)
        require(jobs & {"admin", "manager"} or len(payload) == 1 and jobs & {"buyer", "supervisor"},
                "没有供应商维护权限", 403)
        require(0 < len(payload) <= 2000, "导入行数无效")
        count = 0
        for row in payload:
            values = {key: value.strip() for key, value in row.model_dump().items()}
            require(values["name"] and (row.source_type == "有名商户" or values["location"]), "请填写商户名称及所需位置")
            if not db.query(Supplier.id).filter_by(**values).first():
                db.add(Supplier(**values))
                db.flush()
                count += 1
        db.commit()
        return {"count": count}

    @app.get(prefix + "/inventory")
    def inventory(site: str, request: Request, db: Session = Depends(get_db)):
        authorize(db, request, site)
        values = db.query(Lot.item_id, func.sum(Movement.value)).join(
            Movement, Movement.lot_id == Lot.id,
        ).filter(Lot.site == site).group_by(Lot.item_id).all()
        lots = db.query(Lot, Line, Supplier.name).join(Line, Lot.source_line_id == Line.id).outerjoin(
            Supplier, Supplier.id == Line.supplier_id,
        ).filter(
            Lot.site == site, Lot.quantity > 0,
        ).order_by(Line.name, Lot.expiry.is_(None), Lot.expiry, Lot.id).all()
        return {
            "values": dict(values),
            "lots": [{**columns(lot, "id item_id quantity expiry source_lot_id"),
                      **columns(line, "name unit spec"), "supplier": supplier} for lot, line, supplier in lots],
        }

    @app.get(prefix + "/documents")
    def documents(site: str, request: Request, db: Session = Depends(get_db),
                  page: int = Query(1, ge=1), status: str = "", kind: str = ""):
        authorize(db, request, site)
        query = db.query(Document).filter(or_(Document.site == site, Document.destination == site))
        if status:
            query = query.filter_by(status=status)
        if kind:
            query = query.filter_by(kind=kind)
        rows = query.order_by(Document.id.desc()).offset((page - 1) * 50).limit(51).all()
        return {"more": len(rows) > 50, "documents": [
            columns(row, "id site destination kind status business_date parent_id original_id")
            for row in rows[:50]
        ]}

    @app.get(prefix + "/documents/{doc_id}")
    def detail(site: str, doc_id: int, request: Request, db: Session = Depends(get_db)):
        user, jobs = authorize(db, request, site)
        doc = db.get(Document, doc_id)
        require(doc and site in {doc.site, doc.destination}, "单据不存在", 404)
        lines = lines_for(db, doc)
        available = remaining(db, doc, lines) if doc.kind == "purchase" else {}
        events = db.query(Event, User.display_name).outerjoin(User, Event.actor_id == User.id).filter(
            Event.document_id == doc.id,
        ).order_by(Event.id).all()
        return {
            **columns(doc, "id site destination kind status business_date parent_id original_id note version purchase_method"),
            "mine": doc.created_by == user.id, "buyer": doc.buyer_id == user.id,
            "recipient": doc.target_id == user.id, "jobs": sorted(jobs),
            "lines": [{**columns(line, "id item_id name unit spec quantity accepted book price supplier_id expiry voucher"),
                       "remaining": available.get(line.id)} for line in lines],
            "files": [{"id": file_id, "name": name} for file_id, name in db.query(StoredFile.id, StoredFile.name)
                      .filter_by(document_id=doc.id).order_by(StoredFile.id)],
            "events": [{**columns(event, "action detail created_at"), "actor": name} for event, name in events],
        }

    @app.post(prefix + "/documents")
    def create_document(site: str, payload: DocumentInput, request: Request, db: Session = Depends(get_db),
                        key: str = Header(alias="Idempotency-Key", max_length=100)):
        user, jobs = authorize(db, request, site, write=True)
        require(jobs & CREATE_JOBS[payload.kind], "没有此业务权限", 403)
        return mutate(db, user, key, f"{site}/create", payload, lambda: create(db, user, site, payload))

    @app.post(prefix + "/documents/{doc_id}/actions")
    def action(site: str, doc_id: int, payload: ActionInput, request: Request, db: Session = Depends(get_db),
               key: str = Header(alias="Idempotency-Key", max_length=100)):
        user, jobs = authorize(db, request, site, write=True)
        require(jobs - {"finance", "admin"}, "没有此业务权限", 403)
        return mutate(db, user, key, f"{site}/{doc_id}", payload, lambda: transition(db, user, site, doc_id, payload))


    def file_content(upload):
        data = upload.file.read(8 * 1024 * 1024 + 1)
        require(0 < len(data) <= 8 * 1024 * 1024, "文件不得超过 8 MB", 413)
        return data

    intake_fields = {
        "items": (("名称", "name"), ("分类", "category"), ("单位", "unit"), ("规格", "spec")),
        "suppliers": (("名称", "name"), ("类型", "source_type"), ("位置", "location"), ("联系方式", "contact")),
        "opening": (("物资名称", "name"), ("单位", "unit"), ("规格", "spec"), ("数量", "quantity"),
                    ("单价", "price"), ("到期日期", "expiry")),
    }

    @app.get(prefix + "/intake/{kind}/template")
    def intake_template(site: str, kind: Literal["items", "suppliers", "opening"],
                        request: Request, db: Session = Depends(get_db)):
        authorize(db, request, site)
        output = io.StringIO()
        csv.writer(output).writerow([label for label, _ in intake_fields[kind]])
        return Response("\ufeff" + output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": f"attachment; filename=cafeteria-{kind}.csv"})

    @app.post(prefix + "/intake/{kind}/preview")
    def intake_preview(site: str, kind: Literal["items", "suppliers", "opening"],
                       request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site)
        require("store" in jobs if kind == "opening" else jobs & {"admin", "manager"}, "没有导入权限", 403)
        try:
            source = csv_rows(file_content(file))
        except (ValueError, csv.Error):
            require(False, "无法读取 CSV 文件")
        fields = intake_fields[kind]
        expected = [label for label, _ in fields]
        if kind == "opening" and source and source[0][0:1] == ["名称"]:
            source[0][0] = "物资名称"
        require(source and source[0] == expected, "CSV 表头与模板不符")
        model = ItemInput if kind == "items" else SupplierInput
        rows, seen = [], set()
        for line_no, line in enumerate(source[1:], 2):
            if not any(line):
                continue
            require(len(line) == len(fields), f"第 {line_no} 行列数与模板不符")
            values = {name: value.strip() for (_, name), value in zip(fields, line)}
            try:
                if kind == "opening":
                    item = db.query(Item).filter_by(**{key: values[key] for key in ("name", "unit", "spec")}).one_or_none()
                    require(item, f"第 {line_no} 行物资未匹配目录")
                    require(item.id not in seen, f"第 {line_no} 行物资重复")
                    require(not db.query(Lot.id).filter_by(site=site, item_id=item.id).first(),
                            f"第 {line_no} 行物资已有库存记录")
                    parsed = LineInput(item_id=item.id, quantity=values["quantity"], price=values["price"],
                                       expiry=values["expiry"] or None)
                    require(parsed.quantity > 0, f"第 {line_no} 行数量必须大于零")
                    seen.add(item.id)
                    rows.append({**parsed.model_dump(mode="json"), "name": item.name, "spec": item.spec, "unit": item.unit})
                else:
                    rows.append(model.model_validate(values).model_dump())
            except ValueError:
                require(False, f"第 {line_no} 行的数量、单价、日期或目录字段无效")
        require(0 < len(rows) <= (200 if kind == "opening" else 2000), "导入行数无效")
        return {"rows": rows}

    def store_file(db, user, site, upload, data, content_type, doc_id=None):
        record = StoredFile(site=site, document_id=doc_id, uploader_id=user.id,
                            name=(upload.filename or "文件")[:200], content_type=content_type, content=data)
        db.add(record)
        db.flush()
        return record

    @app.post(prefix + "/documents/{doc_id}/files")
    def upload_file(site: str, doc_id: int, request: Request, file: UploadFile = File(...),
                    db: Session = Depends(get_db),
                    key: str | None = Header(default=None, alias="Idempotency-Key", max_length=100)):
        user, jobs = authorize(db, request, site, write=True)
        require(jobs & {"buyer", "store", "kitchen", "supervisor", "manager"}, "没有上传权限", 403)
        doc = db.get(Document, doc_id)
        require(doc and doc.site == site, "单据不存在", 404)
        data = file_content(file)
        fingerprint = f"{site}/{doc.id}/file/{file.filename}".encode() + data
        digest = hashlib.sha256(fingerprint).hexdigest()
        old = db.get(Receipt, (user.id, key)) if key else None
        if old:
            require(old.digest == digest, "此请求编号已使用", 409)
            return old.response
        require(doc.status not in {"completed", "rejected", "cancelled", "reversed"}, "单据已结束")
        signatures = {b"%PDF-": "application/pdf", b"\xff\xd8\xff": "image/jpeg",
                      b"\x89PNG\r\n\x1a\n": "image/png"}
        content_type = next((kind for signature, kind in signatures.items() if data.startswith(signature)), None)
        if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
            content_type = "image/webp"
        require(content_type, "只支持有效的 JPEG、PNG、WebP 或 PDF")
        record = store_file(db, user, site, file, data, content_type, doc.id)
        result = {"id": record.id}
        db.add(Event(document_id=doc.id, actor_id=user.id, action="upload", detail=record.name))
        if key:
            db.add(Receipt(user_id=user.id, key=key, digest=digest, response=result))
        db.commit()
        return result

    meal_read = {"admin", "manager", "supervisor", "finance"}
    meal_write = {"admin", "manager", "supervisor"}

    @app.get(prefix + "/files/{file_id}")
    def download_file(site: str, file_id: int, request: Request, db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site)
        file = db.get(StoredFile, file_id)
        require(file, "文件不存在", 404)
        if file.document_id:
            doc = db.get(Document, file.document_id)
            require(doc and site in {doc.site, doc.destination}, "文件不存在", 404)
        else:
            require(file.site == site and jobs & meal_read, "文件不存在", 404)
        return Response(file.content, media_type=file.content_type, headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(file.name, safe='')}",
            "X-Content-Type-Options": "nosniff", "Cache-Control": "no-store",
        })

    def check_meals(site, rows, start=None, end=None):
        require(site != "jiyang" or all(row["meal"] != "早餐" for row in rows), "济阳不供早餐")
        if start and end:
            require(start <= end, "结算日期范围无效")
            require(all(not row["date"] or start.isoformat() <= row["date"] <= end.isoformat() for row in rows),
                    "数据日期超出结算周期")

    @app.get(prefix + "/meals")
    def meals(site: str, request: Request, db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site)
        require(jobs & meal_read, "没有月结权限", 403)
        return {"records": [
            {**columns(row, "id month version period_start period_end mode locked_at file_id comment"),
             "total": sum(Decimal(item["price"]) * item["count"] for item in row.rows)}
            for row in db.query(Meal).filter_by(site=site).order_by(Meal.month.desc(), Meal.version.desc())
        ]}

    @app.get(prefix + "/meals/{meal_id}")
    def meal_detail(site: str, meal_id: int, request: Request, db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site)
        require(jobs & meal_read, "没有月结权限", 403)
        row = db.get(Meal, meal_id)
        require(row and row.site == site, "月结不存在", 404)
        return columns(row, "id month version period_start period_end rows locked_at file_id comment")

    @app.post(prefix + "/meal-preview")
    def preview_meal(site: str, request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site)
        require(jobs & meal_write, "没有月结录入权限", 403)
        mode, rows = parse(file.filename or "", file_content(file))
        check_meals(site, rows)
        return {"mode": mode, "rows": rows}

    @app.post(prefix + "/meals")
    def import_meal(site: str, request: Request, file: UploadFile = File(...),
                    month: date = Form(...), period_start: date = Form(...), period_end: date = Form(...),
                    comment: str = Form("", max_length=1000), db: Session = Depends(get_db)):
        user, jobs = authorize(db, request, site, write=True)
        require(jobs & meal_write, "没有月结录入权限", 403)
        data = file_content(file)
        mode, rows = parse(file.filename or "", data)
        check_meals(site, rows, period_start, period_end)
        label = month.strftime("%Y-%m")
        previous = db.query(Meal).filter_by(site=site, month=label).order_by(Meal.version.desc()).all()
        digest = hashlib.sha256(json.dumps([period_start.isoformat(), period_end.isoformat(),
                                            sorted(rows, key=lambda row: (row["date"] or "", row["meal"]))],
                                           sort_keys=True).encode()).hexdigest()
        require(not any(row.locked_at for row in previous), "该月已锁定")
        require(not any(row.digest == digest for row in previous), "该批数据已经导入")
        require(comment.strip() or not previous and all(Decimal(row["price"]) == PRICES[row["meal"]] for row in rows),
                "更正导入或餐费不同于默认标准时，必须填写原因")
        source = store_file(db, user, site, file, data, "application/octet-stream")
        row = Meal(site=site, month=label, version=previous[0].version + 1 if previous else 1,
                   period_start=period_start, period_end=period_end, mode=mode, rows=rows, digest=digest,
                   comment=comment, file_id=source.id, created_by=user.id)
        db.add(row)
        db.flush()
        result = {"id": row.id}
        db.commit()
        return result

    @app.post(prefix + "/meals/{meal_id}/lock")
    def lock_meal(site: str, meal_id: int, request: Request, db: Session = Depends(get_db)):
        user, jobs = authorize(db, request, site, write=True)
        require(jobs & {"manager", "supervisor"}, "没有月结锁定权限", 403)
        row = db.get(Meal, meal_id)
        require(row and row.site == site, "月结不存在", 404)
        latest = db.query(Meal).filter_by(site=site, month=row.month).order_by(Meal.version.desc()).first()
        require(latest.id == row.id and not row.locked_at, "只能锁定最新未锁定版本")
        row.locked_at = utcnow()
        row.locked_by = user.id
        db.commit()
        return {"ok": True}

    @app.get(prefix + "/export")
    def export(site: str, request: Request, db: Session = Depends(get_db)):
        _, jobs = authorize(db, request, site)
        require(jobs & meal_read, "没有导出权限", 403)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["单号", "日期", "类型", "状态", "物资", "规格", "单位", "数量", "实收", "单价"])
        for doc in db.query(Document).filter(or_(Document.site == site, Document.destination == site)).order_by(Document.id):
            for line in lines_for(db, doc):
                entered = [line.name, line.spec, line.unit]
                safe = ["'" + value if value.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value for value in entered]
                writer.writerow([doc.id, doc.business_date, doc.kind, doc.status, *safe,
                                 line.quantity, line.accepted, line.price])
        return Response("\ufeff" + output.getvalue(), media_type="text/csv",
                        headers={"Content-Disposition": "attachment; filename=cafeteria.csv", "Cache-Control": "no-store"})
