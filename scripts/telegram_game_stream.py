#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Mapping

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import game_mailbox

TERMINAL_STATUSES = game_mailbox.TERMINAL_STATUSES


class TelegramError(RuntimeError):
    pass


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def _skill_env() -> Path:
    return SCRIPT_DIR.parent / ".env"


def load_bot_token(hermes_home: str | Path, environ: Mapping[str, str] | None = None) -> str:
    env = os.environ if environ is None else environ
    token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        token = _parse_env_file(Path(hermes_home) / ".env").get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        token = _parse_env_file(_skill_env()).get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise TelegramError("未找到 TELEGRAM_BOT_TOKEN（进程环境、hermes .env 或 skill .env）")
    return token


def load_stream_target(
    environ: Mapping[str, str] | None = None,
) -> tuple[str | None, str | None]:
    """从 skill .env 读取直播目标 chat/thread，供命令行缺省时使用。"""
    env = os.environ if environ is None else environ
    values = _parse_env_file(_skill_env())
    chat_id = (env.get("TELEGRAM_STREAM_CHAT_ID") or values.get("TELEGRAM_STREAM_CHAT_ID") or "").strip() or None
    thread_id = (env.get("TELEGRAM_STREAM_THREAD_ID") or values.get("TELEGRAM_STREAM_THREAD_ID") or "").strip() or None
    return chat_id, thread_id


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        import yaml
        value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def load_transport_config(
    hermes_home: str | Path,
    environ: Mapping[str, str] | None = None,
) -> tuple[str, str | None]:
    env = os.environ if environ is None else environ
    api_base = (
        env.get("TELEGRAM_BOT_API_BASE_URL")
        or env.get("TELEGRAM_API_BASE_URL")
        or ""
    ).strip()
    proxy = (env.get("TELEGRAM_PROXY") or "").strip() or None
    cfg = _load_yaml(Path(hermes_home) / "config.yaml")
    candidates = [
        cfg.get("telegram"),
        (cfg.get("platforms") or {}).get("telegram") if isinstance(cfg.get("platforms"), dict) else None,
        (((cfg.get("gateway") or {}).get("platforms") or {}).get("telegram")
         if isinstance(cfg.get("gateway"), dict) else None),
    ]
    for item in candidates:
        if not isinstance(item, dict):
            continue
        extra = item.get("extra") if isinstance(item.get("extra"), dict) else {}
        if not api_base:
            api_base = str(
                extra.get("api_base_url") or extra.get("base_url")
                or item.get("api_base_url") or item.get("base_url") or ""
            ).strip()
        if not proxy:
            proxy = str(extra.get("proxy_url") or item.get("proxy_url") or "").strip() or None
    return api_base.rstrip("/") or "https://api.telegram.org", proxy


class TelegramBot:
    def __init__(self, token: str, api_base: str, proxy: str | None = None):
        self._token = token
        self._api_base = api_base.rstrip("/")
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
        self._opener = urllib.request.build_opener(*handlers)

    def method_url(self, method: str) -> str:
        base = self._api_base
        if "{token}" in base:
            prefix = base.replace("{token}", self._token)
        elif base.endswith("/bot"):
            prefix = base + self._token
        elif base.endswith("/bot" + self._token):
            prefix = base
        else:
            prefix = base + "/bot" + self._token
        return f"{prefix}/{method}"

    def call(self, method: str, data: dict[str, Any], attempts: int = 4) -> dict[str, Any]:
        encoded = urllib.parse.urlencode({k: v for k, v in data.items() if v is not None}).encode()
        url = self.method_url(method)
        for attempt in range(attempts):
            request = urllib.request.Request(url, data=encoded, method="POST")
            try:
                with self._opener.open(request, timeout=30) as response:
                    payload = json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    payload = {"ok": False, "description": f"HTTP {exc.code}"}
                if exc.code == 429 and attempt + 1 < attempts:
                    retry_after = float((payload.get("parameters") or {}).get("retry_after", 1))
                    time.sleep(max(0.2, retry_after))
                    continue
                raise TelegramError(f"Telegram {method} 失败：{payload.get('description', exc.code)}") from exc
            except OSError as exc:
                if attempt + 1 < attempts:
                    time.sleep(min(2 ** attempt, 4))
                    continue
                raise TelegramError(f"Telegram {method} 网络失败：{type(exc).__name__}") from exc
            if payload.get("ok"):
                result = payload.get("result")
                return result if isinstance(result, dict) else {"result": result}
            description = str(payload.get("description", "未知错误"))
            if "message is not modified" in description.lower():
                return {"not_modified": True}
            raise TelegramError(f"Telegram {method} 失败：{description}")
        raise TelegramError(f"Telegram {method} 重试耗尽")

    def send(self, chat_id: str, text: str, thread_id: str | None) -> int:
        result = self.call("sendMessage", {
            "chat_id": chat_id,
            "message_thread_id": thread_id,
            "text": text,
            "disable_notification": "true",
        })
        if "message_id" not in result:
            raise TelegramError("sendMessage 没有返回 message_id")
        return int(result["message_id"])

    def edit(self, chat_id: str, message_id: int, text: str) -> None:
        self.call("editMessageText", {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        })


def _event_line(event: dict[str, Any]) -> str:
    event_type = event.get("type")
    actor = event.get("actor")
    text = str(event.get("text", ""))
    if event_type == "surface":
        return f"汤面：{text}"
    if event_type == "question":
        return f"玩家：{text}"
    if event_type == "response":
        return f"主持人：{text}"
    if event_type == "hint":
        return f"提示：{text}"
    if event_type == "answer":
        return f"揭晓：{text}"
    if event_type == "control":
        return f"控制：{text}"
    if event_type == "exit":
        return f"{actor}：{text}"
    return f"{actor}：{text}"


def _status_line(state: dict[str, Any]) -> str:
    names = {
        "awaiting_host": "等待主持人开场",
        "player_turn": "等待玩家提问",
        "host_turn": "等待主持人回应",
        "stopped": "已停止",
        "solved": "已猜中",
        "max_rounds": "已达到轮次上限",
        "error": "代理异常退出",
    }
    return f"状态：{names.get(state.get('status'), state.get('status'))}｜第 {state.get('round', 0)} / {state.get('max_rounds', 50)} 轮"


def render_transcript(state: dict[str, Any], title: str = "海龟汤双代理演练", max_chars: int = 3900) -> str:
    header = [title, _status_line(state)]
    event_lines = [_event_line(event) for event in state.get("events", [])]
    surface = next((line for line in event_lines if line.startswith("汤面：")), None)
    rest = [line for line in event_lines if line is not surface]
    lines = header + ([surface] if surface else []) + rest

    def compose(current: list[str], omitted: bool) -> str:
        pieces = current[:2]
        pos = 2
        if surface and len(current) > 2 and current[2] == surface:
            pieces.append(current[2])
            pos = 3
        if omitted:
            pieces.append("……较早过程已折叠……")
        pieces.extend(current[pos:])
        return "\n\n".join(pieces)

    text = compose(lines, False)
    omitted = False
    while len(text) > max_chars and len(rest) > 1:
        rest.pop(0)
        omitted = True
        lines = header + ([surface] if surface else []) + rest
        text = compose(lines, omitted)
    if len(text) > max_chars:
        suffix = "\n\n……内容已截断……"
        text = text[: max(0, max_chars - len(suffix))] + suffix
    return text


def stream_game(
    state_file: str | Path,
    chat_id: str,
    thread_id: str | None,
    token: str,
    api_base: str,
    proxy: str | None = None,
    interval: float = 1.0,
    title: str = "海龟汤双代理演练",
    linger_after_terminal: bool = False,
    stop_event: threading.Event | None = None,
) -> dict[str, Any]:
    if interval <= 0:
        raise TelegramError("interval 必须大于 0")
    stop_event = stop_event or threading.Event()
    bot = TelegramBot(token, api_base, proxy)
    state = game_mailbox.snapshot(state_file)
    last_revision = state["revision"]
    last_text = render_transcript(state, title)
    message_id = bot.send(str(chat_id), last_text, str(thread_id) if thread_id else None)
    print(json.dumps({"message_id": message_id, "revision": last_revision}), flush=True)

    try:
        while not stop_event.is_set():
            time.sleep(interval)
            state = game_mailbox.snapshot(state_file)
            text = render_transcript(state, title)
            if state["revision"] != last_revision or text != last_text:
                if text != last_text:
                    bot.edit(str(chat_id), message_id, text)
                    last_text = text
                last_revision = state["revision"]
            if state["status"] in TERMINAL_STATUSES and not linger_after_terminal:
                break
    finally:
        try:
            state = game_mailbox.snapshot(state_file)
            text = render_transcript(state, title)
            if text != last_text:
                bot.edit(str(chat_id), message_id, text)
        except Exception:
            pass
    return {"message_id": message_id, "revision": last_revision, "status": state["status"]}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="把海龟汤邮箱过程编辑到同一条 Telegram 消息")
    parser.add_argument("--file", required=True)
    parser.add_argument("--chat-id", help="直播目标 chat_id；缺省从 skill 目录 .env 的 TELEGRAM_STREAM_CHAT_ID 读取")
    parser.add_argument("--thread-id", help="直播目标 thread_id；缺省从 skill 目录 .env 的 TELEGRAM_STREAM_THREAD_ID 读取")
    parser.add_argument("--hermes-home", default=os.environ.get("HERMES_HOME", str(Path.home() / ".hermes")))
    parser.add_argument("--api-base")
    parser.add_argument("--proxy")
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--title", default="海龟汤双代理演练")
    parser.add_argument("--linger-after-terminal", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    stop_event = threading.Event()

    def stop_handler(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        chat_id = args.chat_id or None
        thread_id = args.thread_id or None
        if not chat_id:
            chat_id, thread_id = load_stream_target()
        if not chat_id:
            raise TelegramError("未指定 --chat-id，且 skill .env 中没有 TELEGRAM_STREAM_CHAT_ID")
        token = load_bot_token(args.hermes_home)
        configured_base, configured_proxy = load_transport_config(args.hermes_home)
        result = stream_game(
            args.file,
            chat_id,
            thread_id,
            token,
            args.api_base or configured_base,
            args.proxy or configured_proxy,
            args.interval,
            args.title,
            args.linger_after_terminal,
            stop_event,
        )
        print(json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except (TelegramError, game_mailbox.ProtocolError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
