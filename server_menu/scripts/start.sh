#!/usr/bin/bash

SERVER_DIR="/root/minecraft/fabric_serv"  # Директория сервера
JAR_NAME="fabric-server-mc.1.21.4-loader.0.16.14-launcher.1.0.3.jar"  # Загрузщик сервера
SCREEN_NAME="minecraft_fabric_server"  # Имя screen сессии сервера

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

# Запуск сервера
echo "Запуск Minecraft сервера в screen сессии..."
screen -S "$SCREEN_NAME" -d -m java -Xmx2G -jar "$JAR_NAME" nogui

if [ $? -eq 0 ]; then
    echo "Сервер успешно запущен в screen сессии: $SCREEN_NAME"
    echo "Для подключения к консоли сервера выполните:"
    echo "  screen -r $SCREEN_NAME"
else
    echo "Ошибка: не удалось запустить сервер"
    exit 1
fi