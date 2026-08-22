"""Commit message pool and selection engine for Auto Commit Bot.

Generates varied, truthful commit messages that accurately describe
the actual change (updating activity data in .auto-commit/).
Uses weighted sampling with recency penalty to avoid repetition.
"""

import random as _random
from dataclasses import dataclass
from typing import List, Optional

# Default message pool — all messages truthfully describe the actual change
_DEFAULT_MESSAGES = [
    # chore
    ("chore", "update activity log"),
    ("chore", "refresh automation state"),
    ("chore", "sync activity data"),
    ("chore", "update project activity"),
    ("chore", "refresh project state"),
    ("chore", "update automation record"),
    ("chore", "routine activity update"),
    ("chore", "update tracking data"),

    # docs
    ("docs", "refresh activity metadata"),
    ("docs", "update activity notes"),
    ("docs", "update development log"),
    ("docs", "refresh project metadata"),

    # maintenance
    ("maintenance", "update activity record"),
    ("maintenance", "routine project update"),
    ("maintenance", "refresh activity data"),
    ("maintenance", "update project state"),

    # refactor
    ("refactor", "tidy activity metadata"),
    ("refactor", "clean up activity log"),

    # test
    ("test", "update test records"),
    ("test", "refresh test data"),
    ("test", "validate project state"),
]


@dataclass
class MessageEntry:
    """A commit message with its category and description."""
    category: str
    description: str

    def format(self, prefix_override: Optional[str] = None) -> str:
        """Format as 'category: description'."""
        cat = prefix_override if prefix_override else self.category
        return f"{cat}: {self.description}"


class MessageGenerator:
    """
    Generates varied commit messages with recency penalty.

    Tracks recent message usage to avoid consecutive duplicates and
    reduce repetition over short windows.
    """

    def __init__(
        self,
        rng: Optional[_random.Random] = None,
        prefix_override: Optional[str] = None,
        custom_messages: Optional[List[tuple]] = None,
    ):
        self._rng = rng or _random.Random()
        self._prefix_override = prefix_override

        pool = custom_messages if custom_messages else _DEFAULT_MESSAGES
        self._messages = [MessageEntry(cat, desc) for cat, desc in pool]
        self._pool_size = len(self._messages)

        # Recency tracking: index → number of turns since last used
        # Higher recency = higher selection weight
        self._recency = {i: self._pool_size for i in range(self._pool_size)}
        self._last_index: Optional[int] = None

    def generate(self) -> str:
        """
        Generate a single commit message.

        Uses weighted sampling where recently used messages have lower weight.
        Guarantees no consecutive duplicate messages.
        """
        weights = []
        for i in range(self._pool_size):
            # Base weight from recency (more recent = lower weight)
            w = max(1, self._recency[i])
            # Block the last-used message entirely to prevent consecutive dupes
            if i == self._last_index and self._pool_size > 1:
                w = 0
            weights.append(w)

        # Weighted selection
        indices = list(range(self._pool_size))
        chosen_index = self._rng.choices(indices, weights=weights, k=1)[0]

        # Update recency: reset chosen to 0, increment everything else
        for i in range(self._pool_size):
            if i == chosen_index:
                self._recency[i] = 0
            else:
                self._recency[i] = min(self._recency[i] + 1, self._pool_size)

        self._last_index = chosen_index

        entry = self._messages[chosen_index]
        return entry.format(self._prefix_override)

    def generate_batch(self, count: int) -> List[str]:
        """Generate multiple commit messages, each avoiding the previous."""
        return [self.generate() for _ in range(count)]

    def reset(self) -> None:
        """Reset recency tracking."""
        self._recency = {i: self._pool_size for i in range(self._pool_size)}
        self._last_index = None
