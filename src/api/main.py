from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from src.db.engine import close_db, init_db
from src.services.payment_service import PaymentService, parse_cloudpayments_payload

logger = logging.getLogger(__name__)

app = FastAPI(title="Contact Reminder Bot Webhooks", version="1.0.0")


@app.on_event("startup")
async def on_startup() -> None:
    await init_db()


@app.on_event("shutdown")
async def on_shutdown() -> None:
    await close_db()


@app.get("/health")
async def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/webhooks/cloudpayments/check")
async def cloudpayments_check(request: Request) -> JSONResponse:
    raw_body = await request.body()
    payload = parse_cloudpayments_payload(raw_body, request.headers.get("content-type"))

    try:
        service = PaymentService()
        code = await service.process_check_webhook(
            payload=payload,
            raw_body=raw_body,
            headers=request.headers,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception:
        logger.exception("CloudPayments CHECK webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

    return JSONResponse({"code": code})


@app.post("/webhooks/cloudpayments/pay")
async def cloudpayments_pay(request: Request) -> JSONResponse:
    raw_body = await request.body()
    payload = parse_cloudpayments_payload(raw_body, request.headers.get("content-type"))

    try:
        service = PaymentService()
        await service.process_pay_webhook(
            payload=payload,
            raw_body=raw_body,
            headers=request.headers,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception:
        logger.exception("CloudPayments PAY webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

    return JSONResponse({"code": 0})


@app.post("/webhooks/cloudpayments/fail")
async def cloudpayments_fail(request: Request) -> JSONResponse:
    raw_body = await request.body()
    payload = parse_cloudpayments_payload(raw_body, request.headers.get("content-type"))

    try:
        service = PaymentService()
        await service.process_fail_webhook(
            payload=payload,
            raw_body=raw_body,
            headers=request.headers,
        )
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    except Exception:
        logger.exception("CloudPayments FAIL webhook processing failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed")

    return JSONResponse({"code": 0})
