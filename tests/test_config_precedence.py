# -*- coding: utf-8 -*-
"""Tests for .env precedence over stale process environment variables."""

import os
import tempfile
import unittest
from pathlib import Path

from src.config import Config


class ConfigPrecedenceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.env_path = Path(self.temp_dir.name) / ".env"
        self.env_path.write_text(
            "\n".join(
                [
                    "OPENAI_API_KEY=sk-from-env-file-1234567890",
                    "OPENAI_BASE_URL=https://ai.novacode.top/v1",
                    "OPENAI_MODEL=gpt-5.4",
                    "OPENAI_API_STYLE=responses",
                    "TAVILY_API_KEYS=tvly-file-key-1,tvly-file-key-2",
                    "GEMINI_API_KEY=",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        os.environ["ENV_FILE"] = str(self.env_path)
        os.environ["OPENAI_API_KEY"] = "sk-stale-process-key"
        os.environ["OPENAI_BASE_URL"] = "https://example.invalid/v1"
        os.environ["OPENAI_MODEL"] = "stale-model"
        os.environ["OPENAI_API_STYLE"] = "chat_completions"
        os.environ["TAVILY_API_KEYS"] = "tvly-stale-process-key"
        os.environ["GEMINI_API_KEY"] = "stale-gemini-key"
        Config.reset_instance()

    def tearDown(self) -> None:
        Config.reset_instance()
        os.environ.pop("ENV_FILE", None)
        os.environ.pop("OPENAI_API_KEY", None)
        os.environ.pop("OPENAI_BASE_URL", None)
        os.environ.pop("OPENAI_MODEL", None)
        os.environ.pop("OPENAI_API_STYLE", None)
        os.environ.pop("TAVILY_API_KEYS", None)
        os.environ.pop("GEMINI_API_KEY", None)
        self.temp_dir.cleanup()

    def test_env_file_wins_for_llm_and_search_settings(self) -> None:
        config = Config._load_from_env()

        self.assertEqual(config.openai_api_key, "sk-from-env-file-1234567890")
        self.assertEqual(config.openai_base_url, "https://ai.novacode.top/v1")
        self.assertEqual(config.openai_model, "gpt-5.4")
        self.assertEqual(config.openai_api_style, "responses")
        self.assertEqual(config.tavily_api_keys, ["tvly-file-key-1", "tvly-file-key-2"])
        self.assertIsNone(config.gemini_api_key)


if __name__ == "__main__":
    unittest.main()
