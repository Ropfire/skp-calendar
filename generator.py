"""
SKP Schedule to iCalendar (.ics) Generator
Совместимо с Google Календарь, Samsung Календарь, Apple Календарь, Яндекс Календарь и Outlook.
Генерирует .ics поток для группы с автообновлением.
"""

import sys
import os
import json
import re
import argparse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# UTF-8 stdout/stderr на Windows
if sys.stdout:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if sys.stderr:
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

API_SCHEDULE_URL = "https://skp-rasp.ru/api/schedule"
API_VERSION_URL = "https://skp-rasp.ru/api/version"
TIMEZONE = "Asia/Yekaterinburg"
TIMEZONE_OFFSET = "+0500"

DEFAULT_PAIR_SLOTS = {
    1: ("08:30", "10:00"),
    2: ("10:15", "11:45"),
    3: ("12:00", "13:30"),
    4: ("14:00", "15:30"),
    5: ("15:45", "17:15"),
    6: ("17:25", "18:55"),
}


def fetch_schedule_data(cache_file="schedule_cache.json"):
    """Загружает расписание с API skp-rasp.ru с кэшированием."""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) SKP-Calendar-Sync/1.0"}
    req = urllib.request.Request(API_SCHEDULE_URL, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            with open(cache_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return data
    except Exception as e:
        print(f"[!] Ошибка загрузки с API: {e}", file=sys.stderr)
        if os.path.exists(cache_file):
            print(f"[*] Используем локальный кэш: {cache_file}", file=sys.stderr)
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        raise


def get_available_groups(data):
    """Возвращает отсортированный список всех групп."""
    groups = data.get("groups", [])
    if not groups:
        groups = sorted(list({it.get("group") for it in data.get("items", []) if it.get("group")}))
    return sorted(groups)


def parse_time_range(time_str, pair):
    """Парсит строку времени пары (например '08:30-10:00' или '9:00-10:00')."""
    if time_str:
        cleaned = re.sub(r"[–—]", "-", str(time_str).strip())
        parts = cleaned.split("-")
        if len(parts) == 2:
            start_str = parts[0].strip().replace(".", ":")
            end_str = parts[1].strip().replace(".", ":")
            if len(start_str.split(":")[0]) == 1:
                start_str = "0" + start_str
            if len(end_str.split(":")[0]) == 1:
                end_str = "0" + end_str
            return start_str, end_str

    if pair in DEFAULT_PAIR_SLOTS:
        return DEFAULT_PAIR_SLOTS[pair]
    return ("08:30", "10:00")


def escape_ics(text):
    """Экранирует специальные символы в формате RFC 5545 iCalendar."""
    if not text:
        return ""
    text = str(text).replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,")
    text = text.replace("\r\n", "\\n").replace("\n", "\\n")
    return text


def fold_line(line):
    """Переносит длинные строки согласно RFC 5545 (макс 75 байт в строке)."""
    encoded = line.encode("utf-8")
    if len(encoded) <= 75:
        return line

    parts = []
    while len(encoded) > 75:
        cut = 75
        while cut > 0 and (encoded[cut] & 0xC0) == 0x80:
            cut -= 1
        parts.append(encoded[:cut].decode("utf-8"))
        encoded = b" " + encoded[cut:]
    parts.append(encoded.decode("utf-8"))
    return "\r\n".join(parts)


def format_event_title(item):
    """
    Форматирует заголовок события по требованию пользователя:
    "Название предмета (Л/П)[Номер кабинета]
    Имя преподавателя"
    Пример:
    Философия (Л)[15]
    Коваленко Т.Д
    """
    raw_subject = (item.get("subject") or "Занятие").strip()
    raw_type = (item.get("event_type") or "").strip().lower()
    teacher = (item.get("teacher") or "").strip()
    room = str(item.get("room") or "").strip()

    # Определение формата: Лекция (Л) / Практика (П) / Курсовой проект (КП)
    fmt = ""
    # Поиск (Лек), (Л), (Пр), (П), (Лаб) внутри названия
    match = re.search(r"\((Лек|Л|Пр|П|Лаб|Курс проект|Курс работа)\)", raw_subject, re.IGNORECASE)
    if match:
        m_val = match.group(1).lower()
        if m_val in ("лек", "л"):
            fmt = "Л"
        elif m_val in ("пр", "п", "лаб"):
            fmt = "П"
        elif "проект" in m_val or "работа" in m_val:
            fmt = "КП"
        clean_subj = raw_subject[:match.start()] + raw_subject[match.end():]
    else:
        clean_subj = raw_subject
        if "лек" in raw_type:
            fmt = "Л"
        elif "практ" in raw_type or "лаб" in raw_type:
            fmt = "П"

    # Очищаем лишние пробелы и точки
    clean_subj = re.sub(r"\s+", " ", clean_subj).strip(" \t\r\n")
    clean_subj = re.sub(r"\s+\.", ".", clean_subj).strip(" .,-")

    fmt_part = f" ({fmt})" if fmt else ""
    room_part = f"[{room}]" if room else ""

    first_line = f"{clean_subj}{fmt_part}{room_part}".strip()
    if teacher:
        return f"{first_line}\n{teacher}"
    return first_line


def generate_ics_for_group(data, target_group, alarm_minutes=15):
    """Генерирует валидный iCalendar (.ics) для указанной группы."""
    items = data.get("items", [])
    group_items = [it for it in items if it.get("group") == target_group]

    if not group_items:
        target_lower = target_group.lower().strip()
        group_items = [it for it in items if str(it.get("group", "")).lower().strip() == target_lower]

    if not group_items:
        raise ValueError(f"Группа '{target_group}' не найдена в расписании.")

    # Разрешение коллизий листов:
    # Если для даты есть лист с точным названием даты (напр. '01.09.2026'),
    # исключаем записи этой даты из базовых листов (напр. 'Лист1')
    dates_with_specific_sheets = set()
    for it in group_items:
        sheet = str(it.get("source_sheet", "")).strip()
        date = str(it.get("date", "")).strip()
        if sheet == date:
            dates_with_specific_sheets.add(date)

    filtered_items = []
    for it in group_items:
        date = str(it.get("date", "")).strip()
        sheet = str(it.get("source_sheet", "")).strip()
        if date in dates_with_specific_sheets and sheet != date:
            continue
        filtered_items.append(it)

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//SKP Schedule Sync//RU",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:Расписание {target_group}",
        f"X-WR-TIMEZONE:{TIMEZONE}",
        # VTIMEZONE блок
        "BEGIN:VTIMEZONE",
        f"TZID:{TIMEZONE}",
        "BEGIN:STANDARD",
        "DTSTART:19700101T000000",
        f"TZOFFSETFROM:{TIMEZONE_OFFSET}",
        f"TZOFFSETTO:{TIMEZONE_OFFSET}",
        "TZNAME:+05",
        "END:STANDARD",
        "END:VTIMEZONE",
    ]

    now_utc = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    for item in filtered_items:
        date_str = item.get("date")  # DD.MM.YYYY
        pair = int(item.get("pair") or 0)
        time_str = item.get("time") or item.get("grid_time")
        teacher = (item.get("teacher") or "").strip()
        room = str(item.get("room") or "").strip()
        room_label = (item.get("room_label") or "Ауд.").strip()
        event_type = (item.get("event_type") or "").strip()
        format_type = (item.get("format") or "").strip()

        try:
            day, month, year = date_str.split(".")
        except Exception:
            continue

        start_time, end_time = parse_time_range(time_str, pair)
        sh, sm = start_time.split(":")
        eh, em = end_time.split(":")

        dtstart = f"{year}{month}{day}T{sh}{sm}00"
        dtend = f"{year}{month}{day}T{eh}{em}00"

        # Детерминированный стабильный UID для предотвращения дубликатов при обновлениях
        uid = f"skp-{year}{month}{day}-p{pair}-{target_group}-{item.get('source_sheet', '')}@skp-rasp.ru"

        # Заголовок по требованию пользователя
        summary_raw = format_event_title(item)
        summary = escape_ics(summary_raw)

        location = ""
        if room:
            location = escape_ics(f"{room_label} {room}".strip())

        # Подробное описание в теле события
        desc_lines = [
            f"Пара: {pair} пара ({start_time}-{end_time})",
            f"Группа: {target_group}",
        ]
        if teacher:
            desc_lines.append(f"Преподаватель: {teacher}")
        if room:
            desc_lines.append(f"Аудитория: {room_label} {room}".strip())
        if event_type:
            desc_lines.append(f"Тип: {event_type}")
        if format_type:
            desc_lines.append(f"Формат: {format_type}")

        description = escape_ics("\n".join(desc_lines))

        event_lines = [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{now_utc}",
            f"DTSTART;TZID={TIMEZONE}:{dtstart}",
            f"DTEND;TZID={TIMEZONE}:{dtend}",
            f"SUMMARY:{summary}",
            f"DESCRIPTION:{description}",
        ]
        if location:
            event_lines.append(f"LOCATION:{location}")
        event_lines.append("STATUS:CONFIRMED")

        if alarm_minutes and alarm_minutes > 0:
            alarm_summary = escape_ics(summary_raw.split("\n")[0])
            event_lines.extend([
                "BEGIN:VALARM",
                "ACTION:DISPLAY",
                f"DESCRIPTION:{alarm_summary}",
                f"TRIGGER:-PT{alarm_minutes}M",
                "END:VALARM",
            ])

        event_lines.append("END:VEVENT")
        lines.extend(event_lines)

    lines.append("END:VCALENDAR")
    return "\r\n".join(fold_line(line) for line in lines)


def main():
    parser = argparse.ArgumentParser(description="SKP Schedule to iCalendar Converter")
    parser.add_argument("--group", "-g", default="ИСиП-23/1", help="Название группы (по умолч. 'ИСиП-23/1')")
    parser.add_argument("--list-groups", "-l", action="store_true", help="Показать все доступные группы")
    parser.add_argument("--all-groups", "-a", action="store_true", help="Сгенерировать .ics файлы для всех групп")
    parser.add_argument("--out-dir", "-o", default="calendars", help="Папка для сохранения .ics файлов (по умолч. 'calendars')")
    parser.add_argument("--alarm", type=int, default=15, help="Уведомление до пары в минутах (по умолч. 15)")
    args = parser.parse_args()

    print("[*] Получаем данные расписания...")
    data = fetch_schedule_data()
    available_groups = get_available_groups(data)

    if args.list_groups:
        print("\n=== Доступные группы в расписании ===")
        for i, g in enumerate(available_groups, 1):
            print(f" {i:2d}. {g}")
        return

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.all_groups:
        print(f"[*] Генерация календарей для всех {len(available_groups)} групп...")
        for g in available_groups:
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", g)
            filename = out_dir / f"{safe_name}.ics"
            ics_str = generate_ics_for_group(data, g, alarm_minutes=args.alarm)
            with open(filename, "w", encoding="utf-8") as f:
                f.write(ics_str)
            print(f" [+] Сохранено: {filename}")
        print("[*] Все календари успешно сгенерированы!")
        return

    target = args.group
    safe_name = re.sub(r'[\\/*?:"<>|]', "_", target)
    filename = out_dir / f"{safe_name}.ics"
    ics_str = generate_ics_for_group(data, target, alarm_minutes=args.alarm)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(ics_str)

    print(f"\n[*] Календарь для группы '{target}' сохранен в: {filename.resolve()}")


if __name__ == "__main__":
    main()
