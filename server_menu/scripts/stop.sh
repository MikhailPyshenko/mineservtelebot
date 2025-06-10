#!/usr/bin/bash

SERVER_DIR="/root/minecraft/fabric_serv"  # Директория сервера
SCREEN_NAME="minecraft_fabric_server"  # Имя screen сессии сервера
RESTART_DELAY=30  # Задержка перед перезапуском (в секундах)

# Проверка наличия screen
if ! command -v screen &> /dev/null; then
    echo "Ошибка: screen не установлен. Установите его командой:"
    echo "  apt install screen   # для Debian/Ubuntu"
    echo "  yum install screen   # для CentOS/RHEL"
    exit 1
fi

# Переход в директорию с сервером
cd "$SERVER_DIR" || { echo "Ошибка: не удалось перейти в директорию сервера"; exit 1; }

# Остановка сервера
if screen -list | grep -q "$SCREEN_NAME"; then
    echo "Останавливаю текущий сервер..."
    screen -S "$SCREEN_NAME" -X stuff "say Сервер будет перезапущен через $RESTART_DELAY сек...\n"
    sleep "$RESTART_DELAY"
    screen -S "$SCREEN_NAME" -X stuff "stop\n"
fi

if [ $? -eq 0 ]; then
    echo "Screen сессия ($SCREEN_NAME) сервера отключена"
    echo "Сервер остановлен"
else
    echo "Ошибка: не удалось остановить сервер"
    exit 1
fi