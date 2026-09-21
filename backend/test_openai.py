import os
from openai import OpenAI


def main() -> None:
    groq_api_key = os.getenv("GROQ_API_KEY")

    if not groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not set.")

    client = OpenAI(
        api_key=groq_api_key,
        base_url="https://api.groq.com/openai/v1",
    )

    response = client.responses.create(
        model="openai/gpt-oss-20b",
        input=(
            "Introduce yourself to me in a friendly way. "
            "Your name is NOVA."
        ),
    )

    print(response.output_text)


if __name__ == "__main__":
    main()
