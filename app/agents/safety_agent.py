from app.agents.base import BaseLLMAgent


class SafetyAgent(BaseLLMAgent):
    name = "safety_agent"
    prompt_file = "safety_agent.md"
    output_kind = "json"
    temperature = 0.1
    max_tokens = 600
