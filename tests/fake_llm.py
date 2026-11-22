"""A stand-in for the Anthropic client so the agent graph can be tested without an API key."""
from types import SimpleNamespace as NS


class FakeMessages:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def _role(self, system):
        for name in ("PLANNER", "RETRIEVER", "REASONER", "VALIDATOR", "TICKET"):
            if f"You are the {name} agent" in system:
                return name.lower()
        return "other"

    def parse(self, **kw):
        role = self._role(kw["system"])
        self.calls.append((role, kw))
        out = self.script[role](kw)
        return NS(stop_reason="end_turn", parsed_output=kw["output_format"](**out), content=[])

    def create(self, **kw):
        role = self._role(kw["system"])
        self.calls.append((role, kw))
        result = self.script[role](kw)
        if isinstance(result, str):
            return NS(stop_reason="end_turn", content=[NS(type="text", text=result)])
        return result


class FakeClient:
    def __init__(self, script):
        self.beta = NS(messages=FakeMessages(script))

    @property
    def calls(self):
        return self.beta.messages.calls
