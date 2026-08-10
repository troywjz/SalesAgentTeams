from app.agents.base import BaseLLMAgent


class MemoryAgent(BaseLLMAgent):
    name = "memory_agent"
    prompt_file = "memory_agent.md"
    output_kind = "json"
    temperature = 0.1
    max_tokens = 1200
