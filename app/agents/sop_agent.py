from app.agents.base import BaseLLMAgent


class SOPAgent(BaseLLMAgent):
    name = "sop_agent"
    prompt_file = "sop_agent.md"
    output_kind = "json"
    temperature = 0.2
    max_tokens = 1200
