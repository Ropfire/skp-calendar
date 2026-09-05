"""
Build script to generate all calendars and web page locally
"""
import os
from pathlib import Path
import generator
import web_page

def build():
    docs_dir = Path("docs")
    calendars_dir = docs_dir / "calendars"
    calendars_dir.mkdir(parents=True, exist_ok=True)
    
    print("[*] Скачиваем расписание...")
    data = generator.fetch_schedule_data()
    groups = generator.get_available_groups(data)
    
    print(f"[*] Генерируем календари для {len(groups)} групп...")
    for g in groups:
        safe_name = g.replace("/", "_").replace("\\", "_")
        filename = calendars_dir / f"{safe_name}.ics"
        ics_content = generator.generate_ics_for_group(data, g)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(ics_content)
        print(f" [+] {g} -> {filename}")
        
    print("[*] Генерируем страницу docs/index.html...")
    html = web_page.generate_html_page(groups, default_group="ИСиП-23/1")
    with open(docs_dir / "index.html", "w", encoding="utf-8") as f:
        f.write(html)
        
    print("[*] Сборка завершена успешно!")

if __name__ == "__main__":
    build()
