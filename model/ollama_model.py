
from langchain_ollama import ChatOllama
import time
def get_llm(model_name: str = "gpt-oss:20b", temperature: float = 0.0) -> ChatOllama:
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
        base_url="http://192.168.100.100:11434",
    )


def test_llm_inference(prompt: str):
    llm = get_llm()
    print(f"Prompt Length: {len(prompt)} characters")

    start_time = time.time()
    response = llm.invoke(prompt)
    end_time = time.time()

    print("\n--- LLM Response ---")
    print(response.content.strip())

    duration = end_time - start_time
    print(f"\n🕒 Inference Time: {duration:.2f} seconds")

if __name__ == "__main__":
    test_prompt = """
    you are very good
"""

    test_llm_inference(test_prompt)