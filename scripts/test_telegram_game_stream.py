#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import os
import select
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class TelegramStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.t = load_module("telegram_game_stream", "telegram_game_stream.py")
        cls.m = load_module("game_mailbox_for_stream", "game_mailbox.py")

    def test_token_loads_from_hermes_env_without_echo(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td)
            (home / ".env").write_text("TELEGRAM_BOT_TOKEN='123456:secret_value'\n", encoding="utf-8")
            token = self.t.load_bot_token(home, environ={})
            self.assertEqual(token, "123456:secret_value")

    def test_token_falls_back_to_skill_env(self):
        skill_env = self.t.SCRIPT_DIR.parent / ".env"
        self.assertTrue(skill_env.is_file(), "skill 目录应有 .env 作为隔离配置")
        # hermes .env 用空目录模拟不存在，token 应回退到 skill .env
        with tempfile.TemporaryDirectory() as td:
            token = self.t.load_bot_token(Path(td), environ={})
        self.assertTrue(token, "应从 skill .env 读到 TELEGRAM_BOT_TOKEN")

    def test_load_stream_target_falls_back_to_skill_env(self):
        skill_env = self.t.SCRIPT_DIR.parent / ".env"
        self.assertTrue(skill_env.is_file())
        chat_id, thread_id = self.t.load_stream_target(environ={})
        self.assertTrue(chat_id, "从 skill .env 读 TELEGRAM_STREAM_CHAT_ID")
        self.assertTrue(thread_id, "从 skill .env 读 TELEGRAM_STREAM_THREAD_ID")

    def test_render_is_public_bounded_and_has_status(self):
        state = {
            "game_id": "g",
            "status": "player_turn",
            "round": 3,
            "max_rounds": 50,
            "events": [
                {"seq": 1, "actor": "host", "type": "surface", "text": "公开题面"},
                {"seq": 2, "actor": "player", "type": "question", "text": "问题" * 3000},
                {"seq": 3, "actor": "host", "type": "response", "text": "是"},
            ],
        }
        text = self.t.render_transcript(state, title="海龟汤演练", max_chars=3900)
        self.assertLessEqual(len(text), 3900)
        self.assertIn("海龟汤演练", text)
        self.assertIn("第 3 / 50 轮", text)
        self.assertIn("公开题面", text)
        self.assertNotIn("solution", text)
        self.assertNotIn("key_facts", text)

    def test_ptb_style_base_url_is_joined_without_duplicate_bot_segment(self):
        bot = self.t.TelegramBot("999:testtoken", "http://127.0.0.1:8081/bot")
        self.assertEqual(
            bot.method_url("sendMessage"),
            "http://127.0.0.1:8081/bot999:testtoken/sendMessage",
        )

    def test_stream_sends_once_then_edits_same_message_and_lingers(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(length).decode()
                requests.append((self.path, body))
                payload = {"ok": True, "result": {"message_id": 777}}
                data = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        try:
            with tempfile.TemporaryDirectory() as td:
                state_path = Path(td) / "game.json"
                self.m.initialize(state_path, max_rounds=1, game_id="g")
                stop = threading.Event()
                result = {}

                def run():
                    result.update(self.t.stream_game(
                        state_file=state_path,
                        chat_id="123",
                        thread_id="456",
                        token="999:testtoken",
                        api_base=f"http://127.0.0.1:{server.server_port}",
                        interval=0.02,
                        linger_after_terminal=True,
                        stop_event=stop,
                    ))

                worker = threading.Thread(target=run)
                worker.start()
                time.sleep(0.08)
                self.m.append_event(state_path, "host", "surface", "题面", expected_revision=0)
                self.m.append_event(state_path, "player", "question", "问题", expected_revision=1)
                self.m.append_event(state_path, "host", "response", "是", expected_revision=2)
                time.sleep(0.12)
                self.assertTrue(worker.is_alive(), "终局后应等待主代理关闭直播进程")
                stop.set()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(result["message_id"], 777)

            send_paths = [p for p, _ in requests if p.endswith("/sendMessage")]
            edit_paths = [p for p, _ in requests if p.endswith("/editMessageText")]
            self.assertEqual(len(send_paths), 1)
            self.assertGreaterEqual(len(edit_paths), 1)
            self.assertTrue(all("message_id=777" in body for p, body in requests if p.endswith("/editMessageText")))
            self.assertTrue(all("message_thread_id=456" in body for p, body in requests if p.endswith("/sendMessage")))
        finally:
            server.shutdown()
            server.server_close()

    def test_cli_lingers_at_terminal_until_sigterm_then_exits_cleanly(self):
        requests = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                requests.append((self.path, self.rfile.read(length).decode()))
                data = json.dumps({"ok": True, "result": {"message_id": 888}}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                home = Path(td) / "hermes"
                home.mkdir()
                (home / ".env").write_text("TELEGRAM_BOT_TOKEN=999:testtoken\n", encoding="utf-8")
                state = Path(td) / "game.json"
                self.m.initialize(state, max_rounds=1, game_id="sigterm")
                proc = subprocess.Popen(
                    [sys.executable, str(SCRIPTS / "telegram_game_stream.py"),
                     "--file", str(state), "--chat-id", "123",
                     "--hermes-home", str(home),
                     "--api-base", f"http://127.0.0.1:{server.server_port}",
                     "--interval", "0.02", "--linger-after-terminal"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                ready, _, _ = select.select([proc.stdout], [], [], 3)
                self.assertTrue(ready, "直播进程未报告 message_id")
                self.assertIn('"message_id": 888', proc.stdout.readline())
                self.m.add_control(state, "stop", expected_revision=0)
                time.sleep(0.08)
                self.assertIsNone(proc.poll(), "终局后直播进程不应自行退出")
                proc.terminate()
                stdout, stderr = proc.communicate(timeout=3)
                self.assertEqual(proc.returncode, 0, stderr)
                self.assertIn('"status": "stopped"', stdout)
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    unittest.main()
