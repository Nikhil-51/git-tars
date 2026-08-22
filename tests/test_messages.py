"""Tests for the commit message generator."""

import random
import pytest

from auto_commit.messages import MessageGenerator


class TestMessageGeneration:
    """Test commit message generation."""

    def test_generates_non_empty_message(self):
        gen = MessageGenerator()
        msg = gen.generate()
        assert len(msg) > 0
        assert ":" in msg  # Should be in "category: description" format

    def test_no_consecutive_duplicates(self):
        gen = MessageGenerator(rng=random.Random(42))
        messages = gen.generate_batch(50)

        for i in range(1, len(messages)):
            assert messages[i] != messages[i - 1], (
                f"Consecutive duplicate at index {i}: {messages[i]}"
            )

    def test_message_diversity(self):
        gen = MessageGenerator(rng=random.Random(42))
        messages = gen.generate_batch(20)

        unique = len(set(messages))
        # Should have reasonable diversity
        assert unique >= 5

    def test_prefix_override(self):
        gen = MessageGenerator(prefix_override="feat")
        msg = gen.generate()
        assert msg.startswith("feat:")

    def test_seed_reproducibility(self):
        gen1 = MessageGenerator(rng=random.Random(42))
        gen2 = MessageGenerator(rng=random.Random(42))

        msgs1 = gen1.generate_batch(10)
        msgs2 = gen2.generate_batch(10)

        assert msgs1 == msgs2

    def test_reset_clears_recency(self):
        gen = MessageGenerator(rng=random.Random(42))
        gen.generate_batch(10)
        gen.reset()

        # After reset, all messages should have equal weight again
        # Just verify it doesn't error
        msg = gen.generate()
        assert len(msg) > 0

    def test_batch_count(self):
        gen = MessageGenerator()
        messages = gen.generate_batch(5)
        assert len(messages) == 5

    def test_all_messages_describe_actual_changes(self):
        """Messages should describe updates/maintenance, not fake features."""
        gen = MessageGenerator(rng=random.Random(42))
        messages = gen.generate_batch(50)

        forbidden_words = ["implement", "feature", "add new", "build", "create"]
        for msg in messages:
            msg_lower = msg.lower()
            for word in forbidden_words:
                assert word not in msg_lower, (
                    f"Message '{msg}' falsely claims feature work"
                )
