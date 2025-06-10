#!/usr/bin/bash

SERVER_DIR="/root/minecraft/fabric_serv"  # Директория сервера
JAR_NAME="fabric-server-mc.1.21.4-loader.0.16.14-launcher.1.0.3.jar"  # Файл сервера
SCREEN_NAME="minecraft_fabric_server"  # Имя screen сессии
RESTART_DELAY=30  # Задержка перед перезапуском (в секундах)

# Проверка наличия screen
if ! command -v screen &> /dev/null; then
    echo "Ошибка: screen не установлен. Установите его командой:"
    echo "  apt install screen   # для Debian/Ubuntu"
    echo "  yum install screen   # для CentOS/RHEL"
    exit 1
fi

# Проверка существования JAR-файла
if [ ! -f "$SERVER_DIR/$JAR_NAME" ]; then
    echo "Ошибка: JAR-файл сервера не найден по пути:"
    echo "  $SERVER_DIR/$JAR_NAME"
    exit 1
fi

# Переход в директорию с сервером
cd "$SERVER_DIR" || { echo "Ошибка: не удалось перейти в директорию сервера"; exit 1; }

# Остановка текущего сервера (если работает)
if screen -list | grep -q "$SCREEN_NAME"; then
    echo "Останавливаю текущий сервер..."
    screen -S "$SCREEN_NAME" -X stuff "say Сервер будет перезапущен через $RESTART_DELAY сек...\n"
    sleep "$RESTART_DELAY"
    screen -S "$SCREEN_NAME" -X stuff "stop\n"
    sleep 10  # Даем время на корректное завершение
    
    # Проверяем, что сессия закрылась
    if screen -list | grep -q "$SCREEN_NAME"; then
        echo "Принудительное завершение сессии screen..."
        screen -S "$SCREEN_NAME" -X quit
    fi
else
    echo "Сервер не запущен, просто запускаю новый..."
fi

# Запуск нового сервера
echo "Запуск Minecraft сервера в screen сессии..."
screen -S "$SCREEN_NAME" -d -m java -Xmx2G -jar "$JAR_NAME" nogui

if [ $? -eq 0 ]; then
    echo "Сервер успешно перезапущен в screen сессии: $SCREEN_NAME"
    echo "Для подключения к консоли сервера выполните:"
    echo "  screen -r $SCREEN_NAME"
else
    echo "Ошибка: не удалось перезапустить сервер"
    exit 1
fi