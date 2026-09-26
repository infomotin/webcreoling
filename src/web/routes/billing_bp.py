"""
Billing Blueprint — SSLCommerz checkout, callbacks (success/fail/cancel/IPN)
and subscription plan purchase for logged-in users.
"""

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, session as flask_session

from src.storage.database import get_db_session
from src.storage.repositories import (
    SubscriptionPlanRepository,
    PaymentRepository,
    UserRepository,
)
from src.web.auth import login_required, get_current_user
from src.integrations import payment_service
from src.integrations.config_service import get_payment_config, get_mail_config

billing_bp = Blueprint("billing", __name__)


def _finalize_payment(tran_id: str, val_result: dict) -> dict:
    """Mark the transaction and activate the entitlement (idempotent)."""
    with get_db_session() as db:
        pay_repo = PaymentRepository(db)
        plan_repo = SubscriptionPlanRepository(db)
        tx = pay_repo.get_by_tran_id(tran_id)
        if tx is None:
            return {"ok": False, "error": "Transaction not found"}

        if tx.status == "VALID":
            return {"ok": True, "already": True, "tx": tx.to_dict()}

        if not val_result.get("ok"):
            new_status = "FAILED" if val_result.get("status") not in ("CANCELLED", "FAILED") else val_result.get("status")
            pay_repo.update_transaction(tx, status=new_status if new_status in ("FAILED", "CANCELLED") else "FAILED",
                                        raw_response=val_result.get("raw"))
            return {"ok": False, "status": tx.status, "tx": tx.to_dict()}

        pay_repo.update_transaction(
            tx,
            status="VALID",
            payment_method=val_result.get("payment_method") or "",
            bank_tran_id=val_result.get("bank_tran_id"),
            risk_level=val_result.get("risk_level"),
            raw_response=val_result.get("raw"),
        )
        plan = plan_repo.get_by_id(tx.plan_id) if tx.plan_id else None
        if plan and tx.user_id:
            pay_repo.activate_subscription(tx.user_id, plan, transaction=tx)

        tx_dict = tx.to_dict()
        user_id = tx.user_id
        amount = tx.amount

    # Confirmation mail (best effort)
    if user_id:
        try:
            with get_db_session() as db:
                user = UserRepository(db).get_by_id(user_id)
                if user and user.email and get_mail_config().get("enabled", True):
                    from src.integrations.mail_service import send_mail
                    send_mail(
                        db, user.email,
                        "পেমেন্ট সফল | Payment Confirmed — দি ডেইলি এআই আলো",
                        f"<div style='font-family:Arial,sans-serif'>"
                        f"<h2 style='color:#059669'>✅ পেমেন্ট সফল হয়েছে</h2>"
                        f"<p>Transaction: <b>{tx_dict.get('tran_id')}</b></p>"
                        f"<p>Amount: <b>{amount} {get_payment_config().get('currency', 'BDT')}</b></p>"
                        f"<p>আপনার সাবস্ক্রিপশন সক্রিয় হয়েছে। / Your subscription is now active.</p></div>",
                        f"Payment successful. Transaction: {tx_dict.get('tran_id')} Amount: {amount}",
                        purpose="payment_confirmation",
                    )
        except Exception:
            pass

    return {"ok": True, "tx": tx_dict}


@billing_bp.route("/plans")
def plans_view():
    """Public subscription plans page with checkout buttons."""
    with get_db_session() as db:
        plans = SubscriptionPlanRepository(db).all(active_only=True)
        user = get_current_user()
        my_sub = None
        history = []
        if user:
            pay_repo = PaymentRepository(db)
            my_sub = pay_repo.active_subscription(user.id)
            history = pay_repo.transactions_for_user(user.id, limit=10)
    return render_template(
        "billing_plans.html",
        plans=plans,
        my_subscription=my_sub,
        transactions=history,
        payment_cfg=get_payment_config(),
    )


@billing_bp.route("/checkout", methods=["POST"])
@login_required
def checkout_view():
    user = get_current_user()
    plan_id = request.form.get("plan_id", type=int)
    with get_db_session() as db:
        plan = SubscriptionPlanRepository(db).get_by_id(plan_id) if plan_id else None
        if plan is None or not plan.is_active:
            flash("প্ল্যান পাওয়া যায়নি / Plan not found.", "danger")
            return redirect(url_for("billing.plans_view"))

        pay_repo = PaymentRepository(db)
        tran_id = payment_service.build_transaction_id(user.id)
        tx = pay_repo.create_transaction(
            tran_id=tran_id,
            user_id=user.id,
            plan_id=plan.id,
            amount=plan.price,
            currency=plan.currency or "BDT",
            status="PENDING",
        )

        root = request.url_root.rstrip("/")
        customer = {
            "name": user.username,
            "email": user.email or "user@example.com",
            "phone": getattr(user, "phone", None) or "01700000000",
        }
        result = payment_service.create_session(
            amount=plan.price,
            tran_id=tran_id,
            success_url=f"{root}{url_for('billing.success_view')}",
            fail_url=f"{root}{url_for('billing.fail_view')}",
            cancel_url=f"{root}{url_for('billing.cancel_view')}",
            ipn_url=f"{root}{url_for('billing.ipn_view')}",
            customer=customer,
            product_name=f"{plan.name_en or plan.name} ({plan.duration_days} days)",
        )

        if not result.get("ok"):
            pay_repo.update_transaction(tx, status="FAILED", raw_response=result.get("raw"))
            flash(f"গেটওয়ে ত্রুটি / Gateway error: {result.get('error')}", "danger")
            return redirect(url_for("billing.plans_view"))

        pay_repo.update_transaction(tx, session_key=result.get("session_key"))
        gateway_url = result["gateway_url"]

    return redirect(gateway_url)


@billing_bp.route("/success")
def success_view():
    tran_id = request.args.get("tran_id", "")
    val_id = request.args.get("val_id", "")
    val_result = payment_service.validate_payment(val_id) if val_id else {"ok": False, "status": "NO_VAL_ID"}
    outcome = _finalize_payment(tran_id, val_result) if tran_id else {"ok": False, "error": "Missing tran_id"}
    return render_template("billing_result.html", success=outcome.get("ok", False),
                           tran_id=tran_id, outcome=outcome, view="success")


@billing_bp.route("/fail")
def fail_view():
    tran_id = request.args.get("tran_id", "")
    if tran_id:
        with get_db_session() as db:
            pay_repo = PaymentRepository(db)
            tx = pay_repo.get_by_tran_id(tran_id)
            if tx and tx.status == "PENDING":
                pay_repo.update_transaction(tx, status="FAILED")
    return render_template("billing_result.html", success=False,
                           tran_id=tran_id, outcome={"status": "FAILED"}, view="fail")


@billing_bp.route("/cancel")
def cancel_view():
    tran_id = request.args.get("tran_id", "")
    if tran_id:
        with get_db_session() as db:
            pay_repo = PaymentRepository(db)
            tx = pay_repo.get_by_tran_id(tran_id)
            if tx and tx.status == "PENDING":
                pay_repo.update_transaction(tx, status="CANCELLED")
    return render_template("billing_result.html", success=False,
                           tran_id=tran_id, outcome={"status": "CANCELLED"}, view="cancel")


@billing_bp.route("/ipn", methods=["GET", "POST"])
def ipn_view():
    """Instant Payment Notification endpoint (server-to-server)."""
    data = request.values
    tran_id = data.get("tran_id") or data.get("trans_id") or ""
    val_id = data.get("val_id") or ""
    bank_tran_id = data.get("bank_tran_id") or ""
    status = (data.get("status") or "").upper()

    if val_id:
        val_result = payment_service.validate_payment(val_id)
    elif status:
        val_result = {"ok": status == "VALID", "status": status, "raw": dict(data)}
    else:
        val_result = payment_service.ipn_validate(trans_id=tran_id, bank_tran_id=bank_tran_id, val_id=val_id)

    outcome = _finalize_payment(tran_id, val_result) if tran_id else {"ok": False, "error": "Missing tran_id"}
    return jsonify({"received": True, "result": outcome.get("ok"), "detail": outcome})
