"""
Локальный веб-сервер для предварительного просмотра и отдачи расписания.
Запуск: python server.py
Работает на встроенном http.server без установки сторонних библиотек.
"""

import sys
import os
import urllib.parse
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

import generator
import web_page

PORT = 8000
DOCS_DIR = Path(__file__).parent / "docs"


class ScheduleHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(DOCS_DIR), **kwargs)

    def end_headers(self):
        # Добавляем CORS и запрет кэширования для динамических запросов
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)

        # Динамический календарь: /calendar.ics?group=ИСиП-23/1
        if path == "/calendar.ics":
            group = query.get("group", ["ИСиП-23/1"])[0]
            try:
                data = generator.fetch_schedule_data()
                ics_str = generator.generate_ics_for_group(data, group)
                encoded = ics_str.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)
                return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Ошибка: {e}".encode("utf-8"))
                return

        # Если запрашивают .ics из папки calendars/, отдаем правильный Content-Type
        if path.endswith(".ics"):
            file_path = DOCS_DIR / path.lstrip("/")
            if file_path.exists():
                with open(file_path, "rb") as f:
                    content = f.read()
                self.send_response(200)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.end_headers()
                self.wfile.write(content)
                return

        return super().do_GET()


def main():
    # Убеждаемся, что файлы сгенерированы
    if not (DOCS_DIR / "index.html").exists():
        import build_all
        build_all.build()

    server = HTTPServer(("0.0.0.0", PORT), ScheduleHandler)
    print(f"\n=======================================================")
    print(f" Сервер запущен!")
    print(f" Откройте в браузере: http://localhost:{PORT}")
    print(f" Прямая ссылка для календаря (ИСиП-23/1):")
    print(f" http://localhost:{PORT}/calendars/ИСиП-23_1.ics")
    print(f" Нажмите Ctrl+C для остановки")
    print(f"=======================================================\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nСервер остановлен.")


if __name__ == "__main__":
    main()
