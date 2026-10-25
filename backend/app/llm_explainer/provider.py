"""Optional OpenAI editor. It can order existing facts, never author actions or numbers."""
import json
from urllib.request import Request, urlopen

from .models import ExplanationPlan


class OpenAIProvider:
    def __init__(self, api_key, model, timeout=12, transport=None):
        self.api_key, self.model, self.timeout = api_key, model, timeout
        self.transport = transport or urlopen

    def plan(self, facts, style):
        identities = [fact["id"] for fact in facts]
        body = {"model": self.model, "store": False, "max_output_tokens": 1200,
            "instructions": "Eres un editor de explicaciones de poker en español. No decides estrategias, no calculas "
                "equity ni EV, no añades hechos. Ordena las frases suministradas para explicar contexto, estrategia, "
                "comparación y límites. Incluye todos los hechos required=true. Conserva juntas las frecuencias baseline "
                "y explotativas. Solo puedes devolver identificadores existentes, sin repetirlos. "
                "En simple prioriza claridad; en advanced incluye también los detalles técnicos disponibles.",
            "input": json.dumps({"style": style, "facts": facts}, ensure_ascii=False),
            "text": {"format": {"type": "json_schema", "name": "explanation_plan", "strict": True,
                "schema": {"type": "object", "properties": {"fact_ids": {"type": "array",
                    "items": {"type": "string", "enum": identities}}},
                    "required": ["fact_ids"], "additionalProperties": False}}}}
        request = Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"}, method="POST")
        with self.transport(request, timeout=self.timeout) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError("Response too large")
        result = json.loads(raw)
        if result.get("status") != "completed":
            raise ValueError("Incomplete explanation")
        messages = [block["text"] for item in result.get("output", []) if item.get("type") == "message"
                    for block in item.get("content", []) if block.get("type") == "output_text"]
        if len(messages) != 1:
            raise ValueError("Missing explanation plan")
        plan = ExplanationPlan.model_validate_json(messages[0]).fact_ids
        required = {fact["id"] for fact in facts if fact["required"]}
        if len(plan) != len(set(plan)) or not set(plan) <= set(identities) or not required <= set(plan):
            raise ValueError("Ungrounded explanation plan")
        return plan
