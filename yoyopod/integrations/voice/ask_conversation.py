"""Bounded Ask conversation history for the voice worker boundary."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from yoyopod.integrations.voice.worker_contract import VoiceWorkerAskTurn


_EXIT_PHRASES = {
    "exit ask",
    "go back",
    "stop asking",
    "stop ask",
    "leave ask",
    "close ask",
}


@dataclass(slots=True)
class AskConversationState:
    """Track recent Ask turns in the normalized worker contract shape."""

    max_turns: int = 4
    max_text_chars: int = 480
    _turns: list[tuple[str, str]] = field(default_factory=list)

    def reset(self) -> None:
        """Clear all stored Ask conversation turns."""

        self._turns.clear()

    def append(self, question: str, answer: str) -> None:
        """Store one user/assistant turn and keep only the latest full turns."""

        self._turns.append((self._trim(question), self._trim(answer)))
        max_turns = self._effective_max_turns()
        if len(self._turns) > max_turns:
            self._turns = self._turns[-max_turns:]

    def history_for_worker(self) -> list[VoiceWorkerAskTurn]:
        """Return the stored conversation as ordered worker role/text turns."""

        history: list[VoiceWorkerAskTurn] = []
        for question, answer in self._turns:
            history.append(VoiceWorkerAskTurn(role="user", text=question))
            history.append(VoiceWorkerAskTurn(role="assistant", text=answer))
        return history

    def is_exit_request(self, text: str) -> bool:
        """Return whether spoken text exactly matches a normalized Ask exit phrase."""

        return self._normalize_exit_phrase(text) in _EXIT_PHRASES

    def _trim(self, text: str) -> str:
        return re.sub(r"\s+", " ", text.strip())[: self._effective_max_text_chars()]

    def _effective_max_turns(self) -> int:
        return max(1, int(self.max_turns))

    def _effective_max_text_chars(self) -> int:
        return max(1, int(self.max_text_chars))

    @staticmethod
    def _normalize_exit_phrase(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())


__all__ = ["AskConversationState"]
