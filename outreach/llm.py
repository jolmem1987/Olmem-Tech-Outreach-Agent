from __future__ import annotations

from typing import TypeVar

from openai import OpenAI
from pydantic import BaseModel

from outreach.config import get_settings

T = TypeVar("T", bound=BaseModel)


class StructuredLLM:
    def __init__(self) -> None:
        settings = get_settings()
        self.model = settings.openai_model
        self.client = OpenAI(api_key=settings.openai_api_key)

    def parse(self, *, instructions: str, input_text: str, schema: type[T]) -> T:
        response = self.client.responses.parse(
            model=self.model,
            instructions=instructions,
            input=input_text,
            text_format=schema,
        )
        for output in response.output:
            if output.type != "message":
                continue
            for item in output.content:
                if item.type == "output_text" and item.parsed is not None:
                    return item.parsed
        raise RuntimeError("The model did not return a valid structured response")
