from app.agents.base import BaseLLMAgent


class ConversationAgent(BaseLLMAgent):
    name = "conversation_agent"
    prompt_file = "conversation_agent.md"
    output_kind = "json"
    temperature = 0.6
    max_tokens = 800
