"""CLI lifecycle. Configuration is validated before starting any browser/API."""

import argparse
import asyncio
import logging
import sys

from pydantic import ValidationError

from browser_agent.cli.console import Console
from browser_agent.config import Settings


def read_terminal_line(prompt: str, stdin=None, stdout=None, encoding: str | None = None) -> str:
    """Read exactly one byte line so a decode error cannot consume the next command."""
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout
    stdout.write(prompt)
    stdout.flush()
    raw = stdin.readline()
    if raw == b"":
        raise EOFError
    return (
        raw.decode(encoding or sys.stdin.encoding or "utf-8").removesuffix("\n").removesuffix("\r")
    )


async def read_command(console, read=None) -> str:
    """Read a terminal command without terminating the agent on a malformed byte sequence."""
    read = read or read_terminal_line
    while True:
        try:
            return await asyncio.to_thread(read, "\n> ")
        except UnicodeDecodeError:
            console.error(
                "Терминал передал поврежденную строку. Введите команду еще раз; "
                "агент продолжает работу."
            )


async def manual_login_handoff(session, settings, console, login=None) -> bool:
    """Temporarily release the profile to a normal browser, then resume automation."""
    if login is None:
        from browser_agent.browser.manual import manual_login

        login = manual_login
    await session.close()
    try:
        code = await asyncio.to_thread(login, settings, console)
    finally:
        await session.start()
    return code == 0


async def run(settings: Settings, task: str | None, console: Console) -> int:
    from browser_agent.agent.agent import Agent, AgentError
    from browser_agent.browser.session import BrowserSession
    from browser_agent.llm.base import LLMError
    from browser_agent.llm.openai_compatible import OpenAICompatibleProvider
    from browser_agent.tools.registry import ToolRegistry

    session = BrowserSession(settings)
    provider = OpenAICompatibleProvider(settings)
    agent = Agent(settings, provider, ToolRegistry(session), console)
    try:
        await session.start()
        while True:
            try:
                current = task if task is not None else await read_command(console)
            except EOFError:
                break
            current = current.strip()
            if current in {"/exit", "/quit"}:
                break
            if current == "/reset":
                agent.reset()
                session.refs.clear()
                console.status("Диалог и refs очищены. Cookies и текущая страница сохранены.")
            elif current == "/login":
                console.status(
                    "Автоматизация остановлена. Войдите вручную в открывшемся обычном "
                    "браузере и полностью закройте его — агент запустится снова."
                )
                if await manual_login_handoff(session, settings, console):
                    agent.reset()
                    console.status("Браузер агента перезапущен с обновленной авторизацией.")
                else:
                    console.error("Ручной браузер завершился с ошибкой; агент перезапущен.")
            elif current:
                console.status("Задача: " + current)
                try:
                    result = await agent.run(current)
                    console.final(result)
                except (LLMError, AgentError) as exc:
                    console.error(str(exc))
                    if task is not None:
                        return 1
            if task is not None:
                break
        return 0
    finally:
        try:
            await session.close()
        finally:
            await provider.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI agent in a visible Chromium/Brave browser")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--task", help="Run one task and exit")
    mode.add_argument(
        "--login",
        action="store_true",
        help="Manual Google sign-in in a normal browser, without LLM/Playwright",
    )
    args = parser.parse_args()
    console = Console()
    try:
        settings = Settings()
        if args.login:
            from browser_agent.browser.manual import manual_login

            try:
                code = manual_login(settings, console)
            except OSError:
                console.error(
                    "Не удалось открыть установленный браузер. Проверьте путь и GUI-сеанс."
                )
                code = 1
            except KeyboardInterrupt:
                code = 130
            raise SystemExit(code)
        settings.validate_llm()
    except (ValueError, ValidationError) as exc:
        if isinstance(exc, ValidationError):
            details = "; ".join(
                ".".join(map(str, e["loc"])) + ": " + e["msg"]
                for e in exc.errors(include_input=False, include_url=False)
            )
            console.error("Ошибка конфигурации: " + details)
        else:
            console.error(str(exc))
        raise SystemExit(2) from None
    try:
        logging.basicConfig(
            filename=settings.project_root / "errors.log",
            level=logging.ERROR,
            format="%(asctime)s %(name)s %(levelname)s %(message)s",
        )
    except OSError:
        console.error("Невозможно открыть errors.log. Проверьте права записи в папку проекта.")
        raise SystemExit(1) from None
    console.status(
        "Browser Agent\nModel: "
        + settings.llm_model
        + "\nBrowser: "
        + (settings.browser_executable_path or settings.browser_channel or "Playwright Chromium")
        + "\nHeadless: false\nВведите задачу. Команды: /exit /quit /reset /login"
    )
    try:
        code = asyncio.run(run(settings, args.task, console))
    except KeyboardInterrupt:
        console.status("Остановлено пользователем.")
        code = 130
    except Exception as exc:
        logging.exception("Application failed")
        console.error(
            f"{type(exc).__name__}: {str(exc)[:1000]}\n"
            "Проверьте установку браузера и GUI-сессию. Подробности: errors.log"
        )
        code = 1
    raise SystemExit(code)
