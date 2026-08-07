# Автозапуск бота через планировщик Windows.
#
#   powershell -ExecutionPolicy Bypass -File tools\install-autostart.ps1
#   powershell -ExecutionPolicy Bypass -File tools\install-autostart.ps1 -Remove
#
# Задача запускается при входе в систему от текущего пользователя, без окна
# консоли, и поднимается сама, если процесс упал. Пароль нигде не сохраняется:
# «работать только при выполненном входе» этого не требует.
#
# Работает, пока компьютер включён и в сети. Выключенная машина — выключенный бот.

param(
    [switch]$Remove,
    [string]$TaskName = "MisGe pharmacy bot"
)

$ErrorActionPreference = "Stop"

$project = Split-Path -Parent $PSScriptRoot
# pythonw.exe вместо python.exe — иначе при каждом входе всплывает чёрное окно.
$python = Join-Path $project ".venv\Scripts\pythonw.exe"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Автозапуск удалён: $TaskName"
    } else {
        Write-Host "Задачи '$TaskName' и не было."
    }
    return
}

if (-not (Test-Path $python)) {
    throw "Не найден $python. Сначала создайте окружение: python -m venv .venv"
}
if (-not (Test-Path (Join-Path $project ".env"))) {
    throw "Не найден .env с токеном бота рядом с проектом: $project"
}

$action = New-ScheduledTaskAction -Execute $python -Argument "-m misbot.bot" -WorkingDirectory $project

# Триггера два, и второй здесь главный.
#
# «Перезапуск при сбое» (RestartCount) в Windows реагирует на невозможность
# запустить задачу, а не на то, что запущенный процесс умер: проверено — бот
# убивали, задача честно записывала LastTaskResult = -1 и не поднимала его.
# Поэтому раз в две минуты задача просто запускается заново, а MultipleInstances
# IgnoreNew гасит попытку, если бот и так жив. Заодно это вытаскивает бота после
# сна и после обрыва сети.
$atLogon = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$watchdog = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 2) `
    -RepetitionDuration (New-TimeSpan -Days 3650)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
# ExecutionTimeLimit = 0 значит «не убивать по времени»: бот должен жить всегда.
# IgnoreNew — чтобы два бота с одним токеном не подрались за getUpdates:
# Telegram отвечает на такое ошибкой 409.

$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger @($atLogon, $watchdog) `
    -Settings $settings -Principal $principal -Force | Out-Null

Write-Host "Автозапуск настроен: $TaskName"
Write-Host "  запускается    : при входе в систему"
Write-Host "  проверка       : раз в 2 минуты, поднимает бота, если тот умер"
Write-Host "  лог            : $(Join-Path $project 'misge.log')"
Write-Host ""
Write-Host "Запустить прямо сейчас : Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Остановить             : Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "Убрать автозапуск      : tools\install-autostart.ps1 -Remove"
