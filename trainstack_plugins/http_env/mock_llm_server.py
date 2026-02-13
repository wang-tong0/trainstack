import os
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, Field

app = FastAPI(title="Trainstack Mock LLM", version="0.1.0")


class GenerateRequest(BaseModel):
    text: str
    sampling_params: dict[str, Any] = Field(default_factory=dict)
    return_logprob: bool = False


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/generate")
async def generate(_: GenerateRequest) -> dict[str, Any]:
    text = os.getenv("TRAINSTACK_MOCK_LLM_TEXT", "<answer>42</answer>\n")
    return {
        "text": text,
        "meta_info": {
            "finish_reason": {"type": "stop"},
        },
    }


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("TRAINSTACK_MOCK_LLM_HOST", "127.0.0.1")
    port = int(os.getenv("TRAINSTACK_MOCK_LLM_PORT", "18081"))
    uvicorn.run(app, host=host, port=port)
