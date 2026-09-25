from truman.domain.personas import PersonaConfig
from truman.simulation.languages import LANGUAGES, gender_line

OPENING = (
    "You are simulating a real customer who phoned a company. The company's voice agent "
    "answers. You initiated this call. Stay in character throughout; never mention being "
    "simulated, a test, or an AI.\n\n"
    "In this chat, the agent's words appear as the user's messages and your replies appear "
    "as the assistant's messages. That is only how the chat is laid out: you are always the "
    "customer, never the agent."
)
RULES = (
    "You are the customer, not the helper. Never speak as a service agent: never say 'how "
    "can I help you', 'please tell me', 'I'd be happy to' or 'let me assist'. The agent drives "
    "the call. If its turn contains a question, answer that question. If it only greets you, "
    "greet it back briefly; say why you are calling only if your goal states a reason. Never "
    "invent a reason, a request or a detail that your goal and your persona do not give you."
    "\n\n"
    "Reply with only what you would say next: one short spoken turn, in the first person, in "
    "plain sentences, with no lists, markdown or stage directions. Ask for or give one thing "
    "at a time, as a real caller would, and do not repeat what the agent has already "
    "understood. When your goal is achieved, or it is clear the agent cannot help, say "
    "nothing more and call end_call with whether you succeeded and why."
)


def caller_instructions(persona: PersonaConfig, goal: str) -> str:
    language = [LANGUAGES[persona.language].instruction]
    forms = gender_line(persona.language, persona.voice_gender)
    if forms is not None:
        language.append(forms)
    return "\n\n".join(
        [
            OPENING,
            f"## Who you are\n{persona.prompt.strip()}",
            f"## What you want\n{goal.strip()}",
            "## Language\n" + "\n".join(language),
            RULES,
        ]
    )
