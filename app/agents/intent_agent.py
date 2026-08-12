from app.agents.base import BaseLLMAgent


class IntentAgent(BaseLLMAgent):
    name = "intent_agent"
    prompt_file = "intent_agent.md"
    output_kind = "json"
    temperature = 0.1
    max_tokens = 400
