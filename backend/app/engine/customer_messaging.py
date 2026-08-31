"""Drafts the customer-facing update sent at the "customer updated" stage.

Hard constraint: the draft is built from the *already-executed* recovery
action's own target/response data only. The prompt never sees pending
actions, other hypotheses, or internal rationale, so there's no path for it
to reference something that hasn't actually happened yet.
"""
from app.llm.client import LLMUnavailable, chat_json
from app.models.action import ActionRequest
from app.models.case import Customer


async def draft_customer_message(customer: Customer, recovery_action: ActionRequest) -> str:
    label = recovery_action.target.get("label", "a resolution")
    cost = float(recovery_action.target.get("estimated_cost_usd", 0) or 0)
    first_name = (customer.display_name or "there").split(" ")[0]

    try:
        data = await chat_json(
            system=(
                "You write short, warm customer-service messages for a retail brand. "
                "You will be given exactly one action that was already completed for this "
                "customer. Confirm only that action, in 2-4 sentences. Never mention internal "
                "process, other options considered, or anything not explicitly given to you. "
                'Respond as JSON: {"message": str}'
            ),
            user=f"Customer first name: {first_name}\nCompleted action: {label}\nValue: ${cost:.2f}",
        )
        message = data.get("message")
        if message:
            return message
    except LLMUnavailable:
        pass

    cost_clause = f" (${cost:.2f})" if cost else ""
    return (
        f"Hi {first_name}, thanks for your patience while we looked into this. "
        f"We've completed the following on your order: {label}{cost_clause}. "
        "If anything still looks off, just reply and we'll take another look."
    )
