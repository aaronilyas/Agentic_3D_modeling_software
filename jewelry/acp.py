"""Real Codex/Grok ACP stdio adapters with a local mock model."""

from __future__ import annotations

import json
import os
import select
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from jewelry.jsonrpc import INVALID_PARAMS, dumps, error as rpc_error
from jewelry.mock_model import MockModel, lift_envelope

_CODEX_PREWARMED: str | None = None
_DEFAULT_CODEX_ACP = "@agentclientprotocol/codex-acp@1.12.0"
_BIN_ENV = {
    "grok": "JEWELRY_GROK",
    "codex": "JEWELRY_CODEX",
    "npx": "JEWELRY_NPX",
}


class MissingCapability(Exception):
    """Production CLI or mock backend is unavailable."""


def open_acp(application, agent: str, cwd: str, deterministic: bool = True):
    if not deterministic:
        raise MissingCapability("MISSING_CAPABILITY: paid model inference is not used")
    agent = str(agent)
    if agent not in {"grok", "codex"}:
        raise MissingCapability(f"MISSING_CAPABILITY: unknown ACP agent {agent!r}")
    cwd_path = Path(cwd)
    if not cwd_path.is_absolute():
        raise MissingCapability("MISSING_CAPABILITY: ACP cwd must be an absolute path")
    endpoint = application.endpoint()
    mock = MockModel()
    mock.observed_len = lambda: len(endpoint.observed_calls)
    mock.mcp_ready = endpoint.tools_ready
    try:
        mock.start()
    except OSError as exc:
        raise MissingCapability(f"MISSING_CAPABILITY: could not bind mock model: {exc}") from exc
    try:
        if agent == "grok":
            return _launch_grok(endpoint, mock, cwd_path)
        return _launch_codex(endpoint, mock, cwd_path)
    except Exception:
        mock.close()
        raise


class AcpTransport:
    def __init__(
        self,
        proc: subprocess.Popen,
        mock: MockModel,
        endpoint,
        home: Path,
        stderr_lines: list[str],
    ) -> None:
        self.mcp_servers = endpoint.mcp_servers()
        self.observed_calls = endpoint.observed_calls
        mock.observed_len = lambda: len(endpoint.observed_calls)
        self._proc = proc
        self._mock = mock
        self._home = home
        self._stderr_lines = stderr_lines
        self._buffer = bytearray()
        self._closed = False
        self._send_lock = threading.Lock()
        self._injected: list[str] = []

    def queue_tool_calls(self, calls: list[dict]) -> None:
        self._mock.queue_tool_calls(calls)

    def send_line(self, line: str) -> None:
        if self._closed or self._proc.stdin is None:
            raise ConnectionError("ACP transport is closed")
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        injected = _reject_relative_cwd(text)
        if injected is not None:
            self._injected.append(injected)
            return
        data = text.encode("utf-8")
        if not data.endswith(b"\n"):
            data += b"\n"
        with self._send_lock:
            self._proc.stdin.write(data)
            self._proc.stdin.flush()

    def recv_line(self, timeout: float = 30.0) -> str:
        if self._closed:
            raise ConnectionError("ACP transport is closed")
        if self._injected:
            return self._injected.pop(0)
        deadline = time.monotonic() + max(0.0, float(timeout))
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(self._timeout_message())
            newline = self._buffer.find(b"\n")
            if newline >= 0:
                raw = bytes(self._buffer[:newline])
                del self._buffer[: newline + 1]
                text = raw.decode("utf-8", errors="replace").strip()
                if not text:
                    continue
                if text[:1] in "{[":
                    return _normalize_acp_line(text)
                self._stderr_lines.append(text)
                continue
            chunk = self._read_stdout(remaining)
            if chunk is None:
                raise TimeoutError(self._timeout_message())
            if chunk == b"":
                raise ConnectionError(self._timeout_message("ACP CLI closed stdout"))
            self._buffer.extend(chunk)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if self._proc.stdin is not None:
                self._proc.stdin.close()
        except OSError:
            pass
        _stop_process_group(self._proc)
        self._mock.close()
        shutil.rmtree(self._home, ignore_errors=True)

    def _read_stdout(self, timeout: float) -> bytes | None:
        stdout = self._proc.stdout
        if stdout is None:
            return b""
        ready, _, _ = select.select([stdout], [], [], timeout)
        if not ready:
            return None
        return os.read(stdout.fileno(), 65536)

    def _timeout_message(self, prefix: str = "ACP recv_line timed out") -> str:
        tail = "".join(self._stderr_lines[-40:])
        requests = self._mock.requests[-8:]
        return (
            f"{prefix}; stderr={tail!r}; mock_requests={requests!r}; "
            f"exit={self._proc.poll()}"
        )


def _launch_grok(endpoint, mock: MockModel, cwd: Path) -> AcpTransport:
    grok = _which("grok")
    home = Path(tempfile.mkdtemp(prefix="jewelry-grok-home-"))
    try:
        grok_home = home / "grok"
        grok_home.mkdir()
        (grok_home / "config.toml").write_text(_grok_config(mock.base_url), encoding="utf-8")
        env = _isolated_env(home)
        env.update(
            {
                "GROK_HOME": str(grok_home),
                "XAI_API_KEY": "test",
                "GROK_CLI_CHAT_PROXY_BASE_URL": mock.base_url,
                "GROK_MODELS_BASE_URL": mock.base_url,
                "GROK_AGENT_DASHBOARD": "0",
                "GROK_SANDBOX": "off",
            }
        )
        command = [
            grok,
            "--sandbox",
            "off",
            "--disable-web-search",
            "--no-subagents",
            "agent",
            "--always-approve",
            "--no-leader",
            "--model",
            "jewelry-mock",
            "--cli-chat-proxy-base-url",
            mock.base_url,
            "--xai-api-base-url",
            mock.base_url,
            "stdio",
        ]
        return _spawn(command, env, cwd, mock, endpoint, home)
    except Exception:
        shutil.rmtree(home, ignore_errors=True)
        raise


def _launch_codex(endpoint, mock: MockModel, cwd: Path) -> AcpTransport:
    npx = _which("npx")
    codex = _which("codex")
    package = _codex_acp_spec()
    _prewarm_codex_acp(npx, package)
    home = Path(tempfile.mkdtemp(prefix="jewelry-codex-home-"))
    try:
        codex_home = home / "codex"
        codex_home.mkdir()
        (codex_home / "config.toml").write_text(
            _codex_config(mock.base_url, cwd),
            encoding="utf-8",
        )
        (codex_home / "auth.json").write_text(
            '{"auth_mode":"apikey","OPENAI_API_KEY":"test"}\n',
            encoding="utf-8",
        )
        (home / "logs").mkdir(parents=True, exist_ok=True)
        env = _isolated_env(home)
        env.update(
            {
                "CODEX_HOME": str(codex_home),
                "CODEX_PATH": codex,
                "OPENAI_API_KEY": "test",
                "CODEX_API_KEY": "test",
                "NO_BROWSER": "1",
                "INITIAL_AGENT_MODE": "agent-full-access",
                "MODEL_PROVIDER": "jewelry",
                "DEFAULT_AUTH_REQUEST": dumps({"methodId": "api-key"}),
                "APP_SERVER_LOGS": str(home / "logs"),
            }
        )
        command = [npx, "-y", package]
        return _spawn(command, env, cwd, mock, endpoint, home)
    except Exception:
        shutil.rmtree(home, ignore_errors=True)
        raise


def _spawn(
    command: list[str],
    env: dict[str, str],
    cwd: Path,
    mock: MockModel,
    endpoint,
    home: Path,
) -> AcpTransport:
    stderr_lines: list[str] = []
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(cwd),
            env=env,
            start_new_session=True,
        )
    except OSError as exc:
        shutil.rmtree(home, ignore_errors=True)
        raise MissingCapability(
            f"MISSING_CAPABILITY: failed to spawn {' '.join(command)}: {exc}"
        ) from exc
    thread = threading.Thread(
        target=_drain_stderr,
        args=(proc, stderr_lines),
        name="jewelry-acp-stderr",
        daemon=True,
    )
    thread.start()
    return AcpTransport(proc, mock, endpoint, home, stderr_lines)


def _drain_stderr(proc: subprocess.Popen, bucket: list[str]) -> None:
    stream = proc.stderr
    if stream is None:
        return
    try:
        while True:
            line = stream.readline()
            if not line:
                return
            if isinstance(line, bytes):
                bucket.append(line.decode("utf-8", errors="replace"))
            else:
                bucket.append(line)
    except OSError:
        return


def _stop_process_group(proc: subprocess.Popen) -> None:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        if proc.poll() is not None:
            return
        proc.terminate()
    try:
        proc.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        proc.kill()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass


def _which(name: str) -> str:
    env_name = _BIN_ENV[name]
    override = os.environ.get(env_name, "").strip()
    if override:
        path = Path(override)
        if not path.is_file() or not os.access(path, os.X_OK):
            raise MissingCapability(
                f"MISSING_CAPABILITY: {name} executable {override} from {env_name} "
                "is missing or not executable"
            )
        return str(path.resolve())
    found = shutil.which(name)
    if not found:
        raise MissingCapability(
            f"MISSING_CAPABILITY: {name} CLI not found on PATH; set {env_name} to an executable"
        )
    return str(Path(found).resolve())


def _codex_acp_spec() -> str:
    spec = os.environ.get("JEWELRY_CODEX_ACP", _DEFAULT_CODEX_ACP).strip()
    if not spec:
        raise MissingCapability("MISSING_CAPABILITY: JEWELRY_CODEX_ACP is empty")
    return spec


def _isolated_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    real_home = env.get("HOME") or str(Path.home())
    env["HOME"] = str(home)
    env["XDG_CONFIG_HOME"] = str(home / "config")
    env["XDG_CACHE_HOME"] = str(home / "cache")
    env["XDG_DATA_HOME"] = str(home / "data")
    env["NO_BROWSER"] = "1"
    env["CI"] = "1"
    npm_cache = Path(real_home) / ".npm"
    env["npm_config_cache"] = str(npm_cache)
    env["NPM_CONFIG_CACHE"] = str(npm_cache)
    # Never inherit the parent Grok/Codex session, leader socket, or paid keys.
    for key in list(env):
        if key.startswith(("GROK_", "CODEX_", "XAI_", "OPENAI_")):
            env.pop(key, None)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _grok_config(base_url: str) -> str:
    return f"""\
[cli]
auto_update = false

[features]
telemetry = false
remote_fetch = false
codebase_indexing = false
lsp_tools = false

[models]
default = "jewelry-mock"

[model.jewelry-mock]
model = "jewelry-mock"
base_url = "{base_url}"
name = "Jewelry Mock"
api_key = "test"
api_backend = "chat_completions"
context_window = 128000
"""


def _codex_config(base_url: str, cwd: Path) -> str:
    cwd_key = dumps(str(cwd))
    return f"""\
model = "jewelry-mock"
model_provider = "jewelry"
approval_policy = "never"
sandbox_mode = "danger-full-access"
model_reasoning_effort = "none"
model_context_window = 128000

[model_providers.jewelry]
name = "Jewelry mock"
base_url = "{base_url}"
env_key = "OPENAI_API_KEY"
wire_api = "responses"
requires_openai_auth = false

[projects.{cwd_key}]
trust_level = "trusted"
"""


def _reject_relative_cwd(text: str) -> str | None:
    try:
        message = json.loads(text)
    except ValueError:
        return None
    if not isinstance(message, dict) or message.get("method") != "session/new":
        return None
    if "id" not in message:
        return None
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    cwd = params.get("cwd")
    if isinstance(cwd, str) and Path(cwd).is_absolute():
        return None
    return dumps(rpc_error(message["id"], INVALID_PARAMS, "cwd must be an absolute path"))


def _normalize_acp_line(text: str) -> str:
    try:
        message = json.loads(text)
    except ValueError:
        return text
    if not isinstance(message, dict) or message.get("method") != "session/update":
        return text
    params = message.get("params")
    if not isinstance(params, dict):
        return text
    update = params.get("update")
    if not isinstance(update, dict):
        return text
    if update.get("sessionUpdate") not in {"tool_call", "tool_call_update"}:
        return text
    envelope = lift_envelope(update.get("rawOutput"))
    if envelope is None:
        return text
    update["rawOutput"] = envelope
    return dumps(message)


def _prewarm_codex_acp(npx: str, package: str) -> None:
    global _CODEX_PREWARMED
    if _CODEX_PREWARMED == package:
        return
    command = [npx, "-y", "--package", package, "node", "-e", "process.exit(0)"]
    try:
        proc = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise MissingCapability(
            f"MISSING_CAPABILITY: could not pre-warm {package}: {exc}"
        ) from exc
    try:
        _stdout, stderr = proc.communicate(timeout=120)
    except subprocess.TimeoutExpired as exc:
        _stop_process_group(proc)
        raise MissingCapability(
            f"MISSING_CAPABILITY: could not pre-warm {package}: {exc}"
        ) from exc
    if proc.returncode != 0:
        detail = stderr.decode("utf-8", errors="replace")[-500:] if stderr else ""
        raise MissingCapability(
            f"MISSING_CAPABILITY: could not pre-warm {package}: exit {proc.returncode} {detail}"
        )
    _CODEX_PREWARMED = package
