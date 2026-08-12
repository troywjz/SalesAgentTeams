from app.agents.base import BaseLLMAgent


class KnowledgeAgent(BaseLLMAgent):
    name = "knowledge_agent"
    prompt_file = "knowledge_agent.md"
    output_kind = "json"
    temperature = 0.1
    max_tokens = 1200
