
from langchain_ollama import ChatOllama

def get_llm(model_name: str = "mistral:7b-instruct", temperature: float = 0.0) -> ChatOllama:
    """
    Returns a configured ChatOllama model.

    Args:
        model_name (str): The Ollama model name to use (default: mistral:7b).
        temperature (float): Sampling temperature (default: 0 for deterministic).

    Returns:
        ChatOllama: A LangChain-compatible LLM client.
    """
    return ChatOllama(
        model=model_name,
        temperature=temperature,
    )


