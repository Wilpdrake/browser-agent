"""Human-only sign-in in a normal installed browser, without automation flags."""

import shutil
import subprocess

from browser_agent.cli.console import Console
from browser_agent.config import Settings


def login_command(settings: Settings) -> list[str]:
    executable = settings.browser_executable_path
    if not executable:
        candidates = (
            ("google-chrome", "chrome")
            if settings.browser_channel == "chrome"
            else (
                "brave",
                "brave-browser",
                "google-chrome",
                "chromium",
                "chromium-browser",
                "chrome",
            )
        )
        executable = next((found for name in candidates if (found := shutil.which(name))), "")
    if not executable:
        raise ValueError(
            "Для ручного входа укажите BROWSER_EXECUTABLE_PATH "
            "на установленный Brave/Chrome/Chromium."
        )
    return [
        executable,
        f"--user-data-dir={settings.project_root / 'browser-data'}",
        "--new-window",
        "https://accounts.google.com/",
    ]


def manual_login(settings: Settings, console: Console) -> int:
    command = login_command(settings)
    (settings.project_root / "browser-data").mkdir(parents=True, exist_ok=True)
    console.status(
        "Ручной вход: обычный браузер без Playwright и LLM. "
        "Введите пароль и 2FA самостоятельно. Затем закройте все окна этого профиля."
    )
    console.status(
        "Для последующего запуска агента используйте тот же браузер: "
        f"BROWSER_EXECUTABLE_PATH={command[0]}; BROWSER_PERSISTENT=true"
    )
    result = subprocess.run(
        command, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    if result.returncode:
        console.error("Браузер не запустился. Проверьте путь, GUI-сеанс и занятость browser-data.")
    else:
        console.status(
            "Браузер завершился или передал запрос открытому окну. "
            "Это не подтверждение входа. Перед запуском агента закройте профиль."
        )
    return 0 if result.returncode == 0 else 1
