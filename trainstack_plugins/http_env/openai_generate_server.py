import os
from typing import Any

from fastapi import FastAPI, HTTPException
from openai import OpenAI
from pydantic import BaseModel, Field

app = FastAPI(title="Trainstack OpenAI Generate Proxy", version="0.1.0")


class GenerateRequest(BaseModel):
    text: str
    sampling_params: dict[str, Any] = Field(default_factory=dict)
    return_logprob: bool = False


def _make_client() -> OpenAI:
    api_key = os.getenv("API_KEY") or os.getenv("CHUTES_API_KEY")
    if not api_key:
        raise RuntimeError("missing API_KEY or CHUTES_API_KEY")
    base_url = os.getenv("TRAINSTACK_OPENAI_BASE_URL", "https://llm.chutes.ai/v1")
    return OpenAI(api_key=api_key, base_url=base_url)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate")
async def generate(req: GenerateRequest) -> dict[str, Any]:
    model = os.getenv("TRAINSTACK_OPENAI_MODEL", "zai-org/GLM-4.7-Flash")
    temperature = float(req.sampling_params.get("temperature", 0.0))
    max_tokens = int(req.sampling_params.get("max_new_tokens", 256))

    try:
        client = _make_client()
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": req.text}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = (resp.choices[0].message.content or "").strip()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"openai proxy failed: {exc}") from exc

    return {
        "text": text,
        "meta_info": {
            "finish_reason": {"type": "stop"},
        },
    }


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("TRAINSTACK_OPENAI_PROXY_HOST", "0.0.0.0")
    port = int(os.getenv("TRAINSTACK_OPENAI_PROXY_PORT", "18081"))
    uvicorn.run(app, host=host, port=port)

