"""Offline LLM transport tests; config and HTTP are replaced before use."""
import contextlib
import importlib.util
import io
import pathlib
import sys
import types
import unittest
from unittest.mock import Mock, patch


CONFIG = types.ModuleType("config")
CONFIG.LLM_ENDPOINT = ""
CONFIG.LLM_API_KEY = "fictional-test-key"
CONFIG.LLM_MODEL = "fictional-model"
CONFIG.LLM_TIMEOUT = 25
CONFIG.LLM_NORMALIZE_ENDPOINT = ""
CONFIG.LLM_NORMALIZE_API_KEY = ""
CONFIG.LLM_NORMALIZE_MODEL = "normalization-model"
CONFIG.LLM_NORMALIZE_TIMEOUT = 9
CONFIG.STT_SYSTEM_PROMPT = "format transcript"
CONFIG.DEFAULT_TRANSLATE_EN_PROMPT = "translate"
CONFIG.DEFAULT_AI_TASK_PROMPT = "task"
CONFIG.DEFAULT_AI_TASK_EN_PROMPT = "task in English"
CONFIG.DEFAULT_IDEA_PROMPT = "idea prompt"
CONFIG.DEFAULT_IDEA_EN_PROMPT = "idea in English"
CONFIG.DEFAULT_MK_POST_PROMPT = "make a post"
CONFIG.DEFAULT_MK_POST_EN_PROMPT = "make an English post"

path = pathlib.Path(__file__).resolve().parents[1] / "src" / "llm_normalizer.py"
spec = importlib.util.spec_from_file_location("transport_normalizer", path)
LLM = importlib.util.module_from_spec(spec)
with patch.dict(sys.modules, {"config": CONFIG}):
    spec.loader.exec_module(LLM)


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.output = io.StringIO()
        self.redirect = contextlib.redirect_stdout(self.output)
        self.redirect.__enter__()
        self.reply = Mock(ok=True, status_code=200)
        self.reply.json.return_value = {
            "choices": [{"message": {"content": "Formatted transcript."}, "finish_reason": "stop"}]
        }
        self.real_post = LLM.requests.post
        self.post_patch = patch.object(LLM.requests, "post", return_value=self.reply)
        self.post = self.post_patch.start()
        self.normalizer = LLM.LLMNormalizer()
        CONFIG.LLM_API_KEY = "fictional-test-key"

    def tearDown(self):
        self.post_patch.stop()
        self.redirect.__exit__(None, None, None)

    def test_external_http_is_rejected_before_any_request(self):
        for endpoint in (
            "http://provider.example/v1/chat/completions",
            "http://192.168.1.10:11434/v1/chat/completions",
            "http://0.0.0.0:11434/v1/chat/completions",
            "http://[::]:11434/v1/chat/completions",
        ):
            with self.subTest(endpoint=endpoint):
                CONFIG.LLM_ENDPOINT = endpoint
                self.assertEqual(self.normalizer.normalize("original transcript"), "original transcript")
                self.post.assert_not_called()
        self.assertIn("HTTPS", self.output.getvalue())
        self.assertNotIn(CONFIG.LLM_API_KEY, self.output.getvalue())
        self.assertNotIn("original transcript", self.output.getvalue())

    def test_https_sends_transcript_with_existing_auth_and_timeout(self):
        CONFIG.LLM_ENDPOINT = "https://provider.example/v1/chat/completions"
        self.assertEqual(self.normalizer.normalize("original transcript"), "Formatted transcript.")
        args, kwargs = self.post.call_args
        self.assertEqual(args, (CONFIG.LLM_ENDPOINT,))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer fictional-test-key")
        self.assertEqual(kwargs["timeout"], 25)
        self.assertEqual(kwargs["json"]["messages"][1]["content"], "Raw transcript to process:\noriginal transcript")
        self.assertFalse(kwargs.get("allow_redirects", True))
        self.assertNotEqual(kwargs.get("verify"), False)

    def test_failure_warnings_are_english_and_preserve_dictated_language(self):
        original = "Original dictation"
        for endpoint in ("", "http://provider.example/v1"):
            with self.subTest(endpoint=endpoint):
                CONFIG.LLM_ENDPOINT = endpoint
                result = self.normalizer.normalize_result(original)
                self.assertFalse(result.succeeded)
                self.assertEqual(result.text, original)
                self.assertTrue(result.warning.isascii())
        CONFIG.LLM_ENDPOINT = "https://provider.example/v1"
        self.post.side_effect = LLM.requests.exceptions.Timeout("fictional")
        result = self.normalizer.normalize_result(original)
        self.assertEqual(result.text, original)
        self.assertTrue(result.warning.isascii())

    def test_idea_mode_sends_idea_prompt_and_extended_tokens(self):
        CONFIG.LLM_ENDPOINT = "https://provider.example/v1/chat/completions"
        self.assertEqual(self.normalizer.normalize("raw thoughts", idea=True), "Formatted transcript.")
        kwargs = self.post.call_args.kwargs
        self.assertEqual(kwargs["json"]["messages"][0]["content"], "idea prompt")
        self.assertEqual(kwargs["json"]["max_tokens"], 2048)

    def test_mk_post_uses_post_prompt_and_english_variant(self):
        CONFIG.LLM_ENDPOINT = "https://provider.example/v1/chat/completions"
        self.assertEqual(self.normalizer.normalize("raw thoughts", mk_post=True), "Formatted transcript.")
        self.assertEqual(self.post.call_args.kwargs["json"]["messages"][0]["content"], "make a post")
        self.assertEqual(self.post.call_args.kwargs["json"]["max_tokens"], 1024)
        self.post.reset_mock()
        self.assertEqual(
            self.normalizer.normalize("raw thoughts", mk_post=True, translate_en=True),
            "Formatted transcript.",
        )
        self.assertEqual(self.post.call_args.kwargs["json"]["messages"][0]["content"], "make an English post")
        self.assertEqual(self.post.call_count, 1)

    def test_idea_and_english_are_one_request(self):
        CONFIG.LLM_ENDPOINT = "https://provider.example/v1/chat/completions"
        result = self.normalizer.normalize_result(
            "raw thoughts", idea=True, translate_en=True, normalize=True)
        self.assertTrue(result.succeeded)
        self.assertEqual(result.text, "Formatted transcript.")
        self.assertEqual(self.post.call_count, 1)
        message = self.post.call_args.kwargs["json"]["messages"]
        self.assertEqual(message[0]["content"], "idea in English")
        self.assertIn("raw thoughts", message[1]["content"])
        self.assertEqual(self.post.call_args.kwargs["json"]["max_tokens"], 2048)

    def test_normalize_with_idea_sends_only_the_idea_request(self):
        CONFIG.LLM_ENDPOINT = "https://provider.example/v1/chat/completions"
        result = self.normalizer.normalize_result("raw thoughts", idea=True, normalize=True)
        self.assertTrue(result.succeeded)
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.post.call_args.kwargs["json"]["messages"][0]["content"], "idea prompt")

    def test_normalization_uses_its_own_server_until_another_mode_is_selected(self):
        CONFIG.LLM_ENDPOINT = "https://main.example/v1/chat/completions"
        CONFIG.LLM_NORMALIZE_ENDPOINT = "https://normalize.example/v1/chat/completions"
        CONFIG.LLM_NORMALIZE_API_KEY = "normalization-test-key"
        result = self.normalizer.normalize_result("raw thoughts", normalize=True)
        self.assertTrue(result.succeeded)
        self.assertEqual(self.post.call_args.args, ("https://normalize.example/v1/chat/completions",))
        self.assertEqual(self.post.call_args.kwargs["json"]["model"], "normalization-model")
        self.assertEqual(self.post.call_args.kwargs["headers"]["Authorization"], "Bearer normalization-test-key")
        self.assertEqual(self.post.call_args.kwargs["timeout"], 9)
        self.post.reset_mock()
        result = self.normalizer.normalize_result("raw thoughts", normalize=True, mk_post=True, translate_en=True)
        self.assertTrue(result.succeeded)
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.post.call_args.args, ("https://main.example/v1/chat/completions",))
        self.assertEqual(self.post.call_args.kwargs["json"]["model"], "fictional-model")
        CONFIG.LLM_NORMALIZE_ENDPOINT = ""
        CONFIG.LLM_NORMALIZE_API_KEY = ""

    def test_failed_translation_keeps_the_original_transcript(self):
        CONFIG.LLM_ENDPOINT = "https://provider.example/v1/chat/completions"

        def post(*args, **kwargs):
            prompt = kwargs["json"]["messages"][0]["content"]
            reason = "length" if prompt == "idea in English" else "stop"
            content = "structured" if reason == "stop" else "cut"
            reply = Mock(ok=True, status_code=200)
            reply.json.return_value = {"choices": [{"message": {"content": content}, "finish_reason": reason}]}
            return reply

        self.post.side_effect = post
        result = self.normalizer.normalize_result("raw thoughts", idea=True, translate_en=True)
        self.assertFalse(result.succeeded)
        self.assertEqual(result.text, "raw thoughts")

    def test_local_http_remains_available_without_api_key(self):
        CONFIG.LLM_API_KEY = ""
        for endpoint in (
            "http://localhost:11434/v1/chat/completions",
            "http://LOCALHOST:11434/v1/chat/completions",
            "http://127.0.0.1:11434/v1/chat/completions",
            "http://127.0.0.2:11434/v1/chat/completions",
            "http://[::1]:11434/v1/chat/completions",
        ):
            with self.subTest(endpoint=endpoint):
                CONFIG.LLM_ENDPOINT = endpoint
                self.post.reset_mock()
                self.assertEqual(self.normalizer.normalize("local transcript"), "Formatted transcript.")
                self.post.assert_called_once()
                self.assertNotIn("Authorization", self.post.call_args.kwargs["headers"])
                self.assertFalse(self.post.call_args.kwargs.get("allow_redirects", True))
                self.assertEqual(self.post.call_args.kwargs.get("proxies"), {"http": "", "https": "", "all": ""})

    def test_misleading_localhost_urls_are_rejected(self):
        for endpoint in (
            "http://localhost.provider.example/v1",
            "http://localhost@example.com/v1",
            "http://provider.example@localhost/v1",
            "http://provider.example\\@localhost/v1",
            "http://localhost\\provider.example/v1",
            "http://127.0.0.1.provider.example/v1",
            "http://%6cocalhost/v1",
            "http://local\nhost/v1",
        ):
            with self.subTest(endpoint=endpoint):
                CONFIG.LLM_ENDPOINT = endpoint
                self.assertEqual(self.normalizer.normalize("original"), "original")
                self.post.assert_not_called()

    def test_malformed_or_unsupported_endpoints_are_rejected(self):
        for endpoint in (
            "ftp://localhost/v1", "//localhost/v1", "https:///v1",
            "https://provider.example:bad/v1", "http://[::1/v1",
            "https://user:@example.com/v1",
            "https://:@example.com/v1",
        ):
            with self.subTest(endpoint=endpoint):
                CONFIG.LLM_ENDPOINT = endpoint
                self.assertEqual(self.normalizer.normalize("original"), "original")
                self.post.assert_not_called()

    def test_redirect_is_not_followed_or_accepted_as_a_result(self):
        for endpoint in ("https://provider.example/v1", "http://localhost:11434/v1"):
            with self.subTest(endpoint=endpoint):
                CONFIG.LLM_ENDPOINT = endpoint
                self.reply.status_code = 307
                self.reply.headers = {"Location": "http://provider.example/redirected"}
                self.post.reset_mock()
                self.assertEqual(self.normalizer.normalize("original"), "original")
                self.post.assert_called_once()
                self.assertFalse(self.post.call_args.kwargs.get("allow_redirects", True))

    def test_missing_endpoint_and_empty_text_do_not_make_requests(self):
        CONFIG.LLM_ENDPOINT = ""
        self.assertEqual(self.normalizer.normalize("original"), "original")
        CONFIG.LLM_ENDPOINT = "https://provider.example/v1"
        self.assertEqual(self.normalizer.normalize(""), "")
        self.post.assert_not_called()

    def test_requests_preparation_keeps_local_http_off_external_proxies(self):
        CONFIG.LLM_ENDPOINT = "http://localhost:11434/v1/chat/completions"
        captured = []

        def send(request, **options):
            captured.append((request, options))
            response = LLM.requests.Response()
            response.status_code = 200
            response._content = b'{"choices":[{"message":{"content":"Local result"},"finish_reason":"stop"}]}'
            return response

        # Exercise Requests' real preparation and environment merging, stopping
        # before its network adapter. No auth-profile or secret-file reads.
        with (
            patch.object(LLM.requests, "post", self.real_post),
            patch.object(LLM.requests.sessions.Session, "send", side_effect=send),
            patch.object(LLM.requests.sessions, "get_netrc_auth", return_value=None),
            patch.dict("os.environ", {
                "HTTP_PROXY": "http://proxy.example:8080",
                "HTTPS_PROXY": "http://proxy.example:8080",
                "ALL_PROXY": "http://proxy.example:8080",
                "NO_PROXY": "",
            }),
        ):
            self.assertEqual(self.normalizer.normalize("local text"), "Local result")
        self.assertEqual(len(captured), 1)
        request, options = captured[0]
        self.assertEqual(request.url, CONFIG.LLM_ENDPOINT)
        self.assertFalse(options["allow_redirects"])
        self.assertTrue(options["verify"])
        self.assertFalse(LLM.requests.utils.select_proxy(request.url, options["proxies"]))


if __name__ == "__main__":
    unittest.main()
