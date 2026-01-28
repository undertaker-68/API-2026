from dataclasses import dataclass

@dataclass(frozen=True)
class StatusMap:
    awaiting_packaging: str = "ffb88772-9fd0-11ee-0a80-0641000f3d5f"
    awaiting_deliver: str = "ffbc9d6b-9fd0-11ee-0a80-0641000f3d62"
    delivering: str = "ffbe5466-9fd0-11ee-0a80-0641000f3d64"
    delivered: str = "ffc02196-9fd0-11ee-0a80-0641000f3d66"
    cancelled_client_ozon: str = "ffc1c72c-9fd0-11ee-0a80-0641000f3d68"
    cancelled_seller: str = "f0eb0431-48e1-11ef-0a80-038300102a70"

STATUSES = StatusMap()

ALLOWED_OZON_STATUSES = {
    "awaiting_packaging",
    "awaiting_deliver",
    "delivering",
    "delivered",
    "cancelled",
}

def ms_state_id_for_ozon_status(ozon_status: str, cancellation_initiator: str | None) -> str | None:
    if ozon_status == "awaiting_packaging":
        return STATUSES.awaiting_packaging
    if ozon_status == "awaiting_deliver":
        return STATUSES.awaiting_deliver
    if ozon_status == "delivering":
        return STATUSES.delivering
    if ozon_status == "delivered":
        return STATUSES.delivered
    if ozon_status == "cancelled":
        if (cancellation_initiator or "").upper() == "SELLER":
            return STATUSES.cancelled_seller
        return STATUSES.cancelled_client_ozon
    return None
