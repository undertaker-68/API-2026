from dataclasses import dataclass

@dataclass(frozen=True)
class ManagedService:
    key: str
    title: str
    unit: str

SERVICES = {
    "ozon_ms": ManagedService("ozon_ms", "Ozon → МойСклад (FBS)", "ozon_ms_sync.service"),
    "tg_bot": ManagedService("tg_bot", "Telegram API Bot", "tg_api_bot.service"),
}
