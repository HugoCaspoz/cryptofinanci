import asyncio
from hashlib import sha256
import json

from .facts import VERSION, build_facts
from .provider import OpenAIProvider


class ExplanationBusy(Exception):
    pass


class ExplanationService:
    def __init__(self, settings, store, provider=None):
        self.settings, self.store = settings, store
        self.provider = provider
        if self.provider is None and settings.explainer_provider == "openai" and settings.openai_api_key and settings.openai_model:
            self.provider = OpenAIProvider(settings.openai_api_key, settings.openai_model)
        self.lock = asyncio.Lock()

    async def explain(self, record, strategy, evaluation, style, check_access):
        facts = build_facts(record, strategy, evaluation, style)
        provider_name = "openai" if self.provider else "local"
        model = self.settings.openai_model if self.provider else None
        key = sha256(json.dumps({"version": VERSION, "id": record["id"], "facts": facts,
            "style": style, "provider": provider_name, "model": model}, sort_keys=True, allow_nan=False).encode()).hexdigest()
        cached = await asyncio.to_thread(self.store.get_explanation, key)
        await check_access()
        if cached:
            return cached | {"cached": True}
        if self.lock.locked():
            raise ExplanationBusy()
        async with self.lock:
            # Access is rechecked just before any external call, even after a cache read.
            await check_access()
            fallback = None
            order = [fact["id"] for fact in facts]
            if self.provider:
                try:
                    order = await asyncio.to_thread(self.provider.plan, facts, style)
                except Exception:
                    fallback = "No se pudo usar el proveedor; se muestra una explicación local basada en los mismos datos."
                    provider_name, model = "local", None
            elif self.settings.explainer_provider == "openai":
                fallback = "OpenAI no está completamente configurado; se muestra la explicación local."
            by_id = {fact["id"]: fact for fact in facts}
            result = {"version": VERSION, "decision_id": record["id"], "style": style,
                "provider": provider_name, "model": model, "fallback_reason": fallback,
                "paragraphs": [{"fact_id": identity, "text": by_id[identity]["text"], "source": by_id[identity]["source"]}
                               for identity in order], "cached": False}
            await check_access()
            if fallback is None:
                result = await asyncio.to_thread(self.store.save_explanation, key, record["id"], result)
            await check_access()
            return result
