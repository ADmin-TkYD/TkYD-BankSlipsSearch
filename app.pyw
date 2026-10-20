import os
import re
import sys
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox
import threading
from datetime import datetime, timedelta
import configparser
import platform

# Версия программного комплекса
VERSION = "4.3.2"
CONTACT_EMAIL = "ADmin@TkYD.ru"

# АВТООПРЕДЕЛЕНИЕ ОС: Если Windows 10/11 и выше — включаем эмодзи, если старая Win 7/8 — текст
try:
    if hasattr(sys, "getwindowsversion"):
        is_modern_os = sys.getwindowsversion().major >= 10
except Exception:
    is_modern_os = False

if is_modern_os:
    ICONS = {
        "CARD": "💳", "AMOUNT": "💲", "RRN": "🔗", "KA": "🔑", "UNKNOWN": "❓",
        "DESC_K": "— по номеру Карты", "DESC_P": "— по номеру ссылки RRN",
        "DESC_S": "— по Сумме чека",   "DESC_A": "— по коду Авторизации"
    }
else:
    ICONS = {
        "CARD": "[К]", "AMOUNT": "[С]", "RRN": "[Р]", "KA": "[А]", "UNKNOWN": "[?]",
        "DESC_K": "— по номеру Карты",  "DESC_P": "— по номеру ссылки RRN",
        "DESC_S": "— по Сумме чека",    "DESC_A": "— по коду Авторизации"
    }

# ИСПРАВЛЕНИЕ: Жёстко определяем реальную папку запуска (для EXE и для скрипта .pyw)
if getattr(sys, 'frozen', False):
    MAIN_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    MAIN_DIR = os.path.dirname(os.path.abspath(__file__))

db_loaded = False
DB_PATH = os.path.join(MAIN_DIR, "slips_index.db")
INI_PATH = os.path.join(MAIN_DIR, "config.ini")

# ПРЕДКОМПИЛЯЦИЯ REGEX: шаблонов логов
RE_RRN = re.compile(r'(?:RRN|РРН|Номер\s+ссылки):\s*(\d+)', re.IGNORECASE)
RE_KA = re.compile(r'(?:К/А|Код\s+авторизации):\s*(\S+)', re.IGNORECASE)
RE_AMT = re.compile(r'Сумма.*\(Руб\):?\s*([\d.]+)', re.IGNORECASE)
RE_CARD = re.compile(r'(?:\*+|Карта:.*?)(\d{4})\b')

def get_base_dir():
    """Читает путь к логам из config.ini. Запрос всеяден к регистру букв админа"""
    config = configparser.ConfigParser()
    # ИСПРАВЛЕНИЕ: Используем глобально вычисленный MAIN_DIR вместо локального __file__
    default_path = os.path.join(MAIN_DIR, "..", "..", "SLS-Acquiring", "ReportsDays")
    
    if not os.path.exists(INI_PATH):
        config["SETTINGS"] = {"reportsdayspath": os.path.normpath(default_path)}
        try:
            with open(INI_PATH, "w", encoding="utf-8") as configfile:
                config.write(configfile)
        except Exception:
            pass
        return os.path.abspath(default_path)
    
    try:
        config.read(INI_PATH, encoding="utf-8")
        path_from_ini = config.get("SETTINGS", "reportsdayspath")
        if not os.path.isabs(path_from_ini):
            return os.path.abspath(os.path.join(MAIN_DIR, path_from_ini))
        return os.path.abspath(path_from_ini)
    except Exception:
        return os.path.abspath(default_path)

def init_db():
    """Создает базу данных и таблицы с индексами, если их еще нет"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS slips (
            file_path TEXT PRIMARY KEY,
            date_time TEXT,
            amount TEXT,
            rrn TEXT,
            ka TEXT,
            card TEXT
        )
    ''')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_card ON slips(card)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_amount ON slips(amount)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_rrn ON slips(rrn)')
    cursor.execute('CREATE INDEX IF NOT EXISTS idx_ka ON slips(ka)')
    conn.commit()
    conn.close()

def parse_and_insert_file(cursor, file_path, file, year_dir):
    """Оптимизированная функция парсинга файла чека"""
    try:
        content = None
        for enc in ['cp866', 'utf-8', 'cp1251']:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                break
            except Exception:
                continue
        
        if not content:
            return False

        rrn_m = RE_RRN.search(content)
        ka_m = RE_KA.search(content)
        amt_m = RE_AMT.search(content)
        card_m = RE_CARD.search(content)

        rrn_val = rrn_m.group(1) if rrn_m else "Не найден"
        ka_val = ka_m.group(1) if ka_m else "Не найден"
        amt_val = amt_m.group(1) if amt_m else "---"
        card_val = card_m.group(1) if card_m else "Не указана"

        raw_time = file.replace("Slip", "").replace(".txt", "").replace("ntte", "").strip()
        try:
            if " " in raw_time:
                date_part, time_part = raw_time.split(" ")
                if date_part.startswith(year_dir[2:]):
                    date_part = year_dir + date_part[2:]
                time_str = f"{date_part} {time_part.replace('_', ':')}"
            else:
                time_str = raw_time.replace("_", ":")
                if time_str.startswith(year_dir[2:]):
                    time_str = year_dir + time_str[2:]
        except Exception:
            time_str = raw_time

        cursor.execute(
            'INSERT OR IGNORE INTO slips VALUES (?, ?, ?, ?, ?, ?)',
            (file_path, time_str, amt_val, rrn_val, ka_val, card_val)
        )
        return True
    except Exception:
        return False

def scan_today_only():
    """Моментально сканирует ТОЛЬКО сегодняшнюю папку перед выполнением поиска"""
    base_dir = get_base_dir()
    now = datetime.now()
    
    year_str = now.strftime("%Y")
    month_str = now.strftime("%m")
    day_str = now.strftime("%d")
    
    today_path = os.path.join(base_dir, year_str, month_str, day_str)
    if not os.path.exists(today_path):
        return

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        files = os.listdir(today_path)
        for file in files:
            if file.startswith("Slip") and file.endswith(".txt"):
                file_path = os.path.join(today_path, file)
                
                cursor.execute('SELECT 1 FROM slips WHERE file_path = ?', (file_path,))
                if not cursor.fetchone():
                    parse_and_insert_file(cursor, file_path, file, year_str)
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()

def update_database():
    """Фоновый первоначальный сканер папок за 6 месяцев при старте приложения"""
    global db_loaded
    init_db()
    
    base_dir = get_base_dir()
    if not os.path.exists(base_dir):
        db_loaded = True
        root.after(0, lambda: lbl_status.config(text="Путь не найден", foreground="red"))
        return

    now = datetime.now()
    limit_date = now - timedelta(days=180)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    try:
        years = sorted(os.listdir(base_dir), reverse=True)
    except Exception:
        years = []

    for year_dir in years:
        if not (year_dir.isdigit() and len(year_dir) == 4) or int(year_dir) < limit_date.year:
            continue
        year = int(year_dir)

        year_path = os.path.join(base_dir, year_dir)
        try:
            months = sorted(os.listdir(year_path), reverse=True)
        except Exception:
            continue

        for month_dir in months:
            if not month_dir.isdigit() or int(month_dir) > 12:
                continue
            month = int(month_dir)

            month_path = os.path.join(year_path, month_dir)
            try:
                days = sorted(os.listdir(month_path), reverse=True)
            except Exception:
                continue

            for day_dir in days:
                if not day_dir.isdigit():
                    continue
                day = int(day_dir)
                
                if datetime(year, month, day) < datetime(limit_date.year, limit_date.month, limit_date.day):
                    continue

                day_path = os.path.join(month_path, day_dir)
                try:
                    files = os.listdir(day_path)
                except Exception:
                    continue

                for file in files:
                    if file.startswith("Slip") and file.endswith(".txt"):
                        file_path = os.path.join(day_path, file)
                        
                        cursor.execute('SELECT 1 FROM slips WHERE file_path = ?', (file_path,))
                        if cursor.fetchone():
                            continue

                        parse_and_insert_file(cursor, file_path, file, year_dir)
                conn.commit()

    limit_str = (datetime.now() - timedelta(days=180)).strftime("%Y-%m-%d")
    cursor.execute("DELETE FROM slips WHERE date_time < ?", (limit_str,))
    conn.commit()
    conn.close()
    
    db_loaded = True
    root.after(0, lambda: lbl_status.config(text="База готова", foreground="green"))

def on_row_double_click(event, copy_ka=False):
    """Именная распаковка строк полностью защищает копирование от багов маркдауна"""
    item = tree.selection()
    if not item: return
    row_values = tree.item(item, "values")
    if not row_values or len(row_values) < 5: return
    
    match_type, date_time, amount, rrn, ka = row_values
    val_to_copy = ka if copy_ka else rrn
    label_text = "Код авторизации" if copy_ka else "RRN"
    
    if val_to_copy and val_to_copy != "Не найден":
        root.clipboard_clear()
        root.clipboard_append(val_to_copy)
        root.update()
        
        old_status = lbl_status.cget("text")
        old_color = lbl_status.cget("foreground")
        lbl_status.config(text=f"{label_text} скопирован!", foreground="darkgreen")
        root.after(2000, lambda: lbl_status.config(text=old_status, foreground=old_color))

def show_about():
    """Кастомное окно 'О программе' с автоматическим центрированием и динамическими иконками"""
    about_win = tk.Toplevel(root)
    about_win.title("О программе")
    
    win_width = 470
    win_height = 450
    
    about_win.withdraw()
    about_win.transient(root)
    about_win.grab_set()

    bg_color = ttk.Style().lookup("TFrame", "background")
    about_win.configure(bg=bg_color)

    content_frame = ttk.Frame(about_win, padding="20")
    content_frame.pack(fill=tk.BOTH, expand=True)
    content_frame.columnconfigure(0, weight=1)

    texts_top = [
        ("Поиск банковских слипов", ("Helvetica", 11, "bold"), 10),
        (f"Версия ПО: {VERSION}", ("Helvetica", 10), 15),
        ('Разработано TkYD для интеграции с ПО SoftLand Systems "SLS-Эквайринг".', ("Helvetica", 10), 8),
        ("Глубина поиска: последние 6 месяцев (Локальная БД SQLite3).", ("Helvetica", 10), 15),
        ("Тип совпадения (первый столбец):", ("Helvetica", 10, "bold"), 8)
    ]

    current_row = 0
    for txt, font_style, pad_y in texts_top:
        lbl = ttk.Label(content_frame, text=txt, font=font_style, wraplength=430, justify=tk.LEFT)
        lbl.grid(row=current_row, column=0, columnspan=2, sticky=tk.W, pady=(0, pad_y))
        current_row += 1

    grid_frame = ttk.Frame(content_frame)
    grid_frame.grid(row=current_row, column=0, columnspan=2, sticky=tk.W, pady=(0, 20))
    
    lbl_k_letter = ttk.Label(grid_frame, text=ICONS["CARD"], font=("Helvetica", 10, "bold") if not is_modern_os else ("Helvetica", 11), foreground="darkblue" if not is_modern_os else None)
    lbl_k_letter.grid(row=0, column=0, sticky=tk.W, padx=(0, 5))
    lbl_k_text = ttk.Label(grid_frame, text=ICONS["DESC_K"], font=("Helvetica", 10))
    lbl_k_text.grid(row=0, column=1, sticky=tk.W, padx=(0, 35))

    lbl_p_letter = ttk.Label(grid_frame, text=ICONS["RRN"], font=("Helvetica", 10, "bold") if not is_modern_os else ("Helvetica", 11), foreground="darkblue" if not is_modern_os else None)
    lbl_p_letter.grid(row=1, column=0, sticky=tk.W, padx=(0, 5))
    lbl_p_text = ttk.Label(grid_frame, text=ICONS["DESC_P"], font=("Helvetica", 10))
    lbl_p_text.grid(row=1, column=1, sticky=tk.W, padx=(0, 35))

    lbl_s_letter = ttk.Label(grid_frame, text=ICONS["AMOUNT"], font=("Helvetica", 10, "bold") if not is_modern_os else ("Helvetica", 11), foreground="darkblue" if not is_modern_os else None)
    lbl_s_letter.grid(row=0, column=2, sticky=tk.W, padx=(0, 5))
    lbl_s_text = ttk.Label(grid_frame, text=ICONS["DESC_S"], font=("Helvetica", 10))
    lbl_s_text.grid(row=0, column=3, sticky=tk.W)

    lbl_a_letter = ttk.Label(grid_frame, text=ICONS["KA"], font=("Helvetica", 10, "bold") if not is_modern_os else ("Helvetica", 11), foreground="darkblue" if not is_modern_os else None)
    lbl_a_letter.grid(row=1, column=2, sticky=tk.W, padx=(0, 5))
    lbl_a_text = ttk.Label(grid_frame, text=ICONS["DESC_A"], font=("Helvetica", 10))
    lbl_a_text.grid(row=1, column=3, sticky=tk.W)
    
    current_row += 1

    texts_bottom = [
        ("Горячие клавиши для кассира:", ("Helvetica", 10, "bold"), 6),
        ("• Двойной клик — скопировать RRN", ("Helvetica", 10), 3),
        ("• Shift + Двойной клик — скопировать К/А", ("Helvetica", 10), 15),
        ("Техническая поддержка:", ("Helvetica", 10, "bold"), 2)
    ]

    for txt, font_style, pad_y in texts_bottom:
        lbl = ttk.Label(content_frame, text=txt, font=font_style, wraplength=430, justify=tk.LEFT)
        lbl.grid(row=current_row, column=0, columnspan=2, sticky=tk.W, pady=(0, pad_y))
        current_row += 1

    def open_mail(event):
        import webbrowser
        from urllib.parse import quote
        comp_name = os.environ.get('COMPUTERNAME', 'UNKNOWN-PC')
        subject_text = f"Техподдержка TkYD-BankSlipsSearch v{VERSION} ({comp_name})"
        webbrowser.open(f"mailto:{CONTACT_EMAIL}?subject={quote(subject_text)}")

    lbl_email = tk.Label(
        content_frame, 
        text=CONTACT_EMAIL, 
        fg="blue", 
        bg=bg_color,
        cursor="hand2", 
        font=("Helvetica", 10, "underline"),
        justify=tk.LEFT
    )
    lbl_email.grid(row=current_row, column=0, columnspan=2, sticky=tk.W, pady=(0, 15))
    lbl_email.bind("<Button-1>", open_mail)
    current_row += 1

    btn_close = ttk.Button(content_frame, text="Закрыть", command=about_win.destroy)
    btn_close.grid(row=current_row, column=1, sticky=tk.E, pady=(5, 0))

    root.update_idletasks()
    root_x = root.winfo_x()
    root_y = root.winfo_y()
    root_width = root.winfo_width()
    root_height = root.winfo_height()
    
    pos_x = root_x + (root_width // 2) - (win_width // 2)
    pos_y = root_y + (root_height // 2) - (win_height // 2)
    
    about_win.geometry(f"{win_width}x{win_height}+{pos_x}+{pos_y}")
    about_win.resizable(False, False)
    about_win.deiconify()

def perform_search():
    global db_loaded
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        db_loaded = False
        lbl_status.config(text="Восстановление БД...", foreground="orange")
        threading.Thread(target=update_database, daemon=True).start()
        messagebox.showwarning("База данных", "Обнаружено повреждение или удаление базы данных! Запущено автоматическое фоновое восстановление логов.")
        return

    # ДОРАБОТКА: Окно-таймер, которое автоматически закрывается по факту готовности БД или через 5 секунд
    if not db_loaded:
        wait_win = tk.Toplevel(root)
        wait_win.title("Пожалуйста, подождите")
        wait_win.geometry("380x120")
        wait_win.resizable(False, False)
        wait_win.transient(root)
        wait_win.grab_set()
        
        # Центрируем окно ожидания относительно главного
        root.update_idletasks()
        pos_x = root.winfo_x() + (root.winfo_width() // 2) - 190
        pos_y = root.winfo_y() + (root.winfo_height() // 2) - 60
        wait_win.geometry(f"+{pos_x}+{pos_y}")
        
        lbl_msg = ttk.Label(wait_win, text="Идет первоначальное обновление базы слипов...\nПожалуйста, подождите.", font=("Helvetica", 10), justify=tk.CENTER)
        lbl_msg.pack(expand=True, pady=10)
        
        ticks = [5]  # Счетчик секунд
        
        def check_status():
            if db_loaded or ticks[0] <= 0:
                wait_win.destroy()
                if db_loaded:
                    perform_search()  # Автоматически запускаем поиск, если база догрузилась
            else:
                ticks[0] -= 1
                wait_win.after(1000, check_status)
                
        wait_win.after(1000, check_status)
        return

    search_term = entry_search.get().strip().replace('*', '')
    if not search_term:
        messagebox.showwarning("Внимание", "Введите сумму, карту, RRN или код авторизации.")
        return

    scan_today_only()

    for row in tree.get_children():
        tree.delete(row)

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    query = f"""
        SELECT 
            CASE 
                WHEN card = ? OR card LIKE ? THEN '{ICONS["CARD"]}'
                WHEN amount = ? OR amount LIKE ? THEN '{ICONS["AMOUNT"]}'
                WHEN rrn = ? OR rrn LIKE ? THEN '{ICONS["RRN"]}'
                WHEN ka = ? OR ka LIKE ? THEN '{ICONS["KA"]}'
                ELSE '{ICONS["UNKNOWN"]}'
            END as match_type,
            date_time, amount, rrn, ka 
        FROM slips 
        WHERE card = ? OR amount = ? OR rrn = ? OR ka = ?
        OR card LIKE ? OR amount LIKE ? OR rrn LIKE ? OR ka LIKE ?
        ORDER BY date_time DESC
    """
    like_term = f"%{search_term}%"
    
    params = (
        search_term, like_term, search_term, like_term, search_term, like_term, search_term, like_term,
        search_term, search_term, search_term, search_term, like_term, like_term, like_term, like_term
    )
    
    cursor.execute(query, params)
    found_records = cursor.fetchall()
    conn.close()

    for rec in found_records:
        tree.insert("", tk.END, values=(rec[0], rec[1], rec[2], rec[3], rec[4]))

    if not found_records:
        lbl_status.config(text="Не найдено", foreground="red")
        messagebox.showinfo("Результат", "Транзакция не найдена за последние 6 месяцев.")
    else:
        lbl_status.config(text=f"Найдено: {len(found_records)}", foreground="green")

def auto_scroll(first, last):
    if float(first) <= 0.0 and float(last) >= 1.0:
        scrollbar.pack_forget()
    else:
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    scrollbar.set(first, last)

# ДОРАБОТКА: Функция автовыделения имеющегося текста при клике по полю ввода
def select_all_text(event):
    entry_search.selection_range(0, tk.END)

# Инициализация интерфейса
root = tk.Tk()
root.title(f"Поиск банковских слипов v{VERSION}")
root.geometry("710x410")
root.resizable(False, False)

frame_input = ttk.Frame(root, padding="10")
frame_input.pack(fill=tk.X)

lbl_search = ttk.Label(frame_input, text="Поисковый запрос:")
lbl_search.pack(side=tk.LEFT, padx=5)

entry_search = ttk.Entry(frame_input, width=25)
entry_search.pack(side=tk.LEFT, padx=5)
entry_search.focus()

# Привязываем автовыделение текста ко всем видам кликов мыши и фокуса
entry_search.bind("<FocusIn>", select_all_text)
entry_search.bind("<Button-1>", select_all_text)

btn_search = ttk.Button(frame_input, text="Найти", command=perform_search)
btn_search.pack(side=tk.LEFT, padx=5)

btn_about = ttk.Button(frame_input, text="  ?  ", width=3, command=show_about)
btn_about.pack(side=tk.LEFT, padx=5)

lbl_status = ttk.Label(frame_input, text="Проверка БД...", foreground="orange")
lbl_status.pack(side=tk.RIGHT, padx=5)

ttk.Separator(root, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=15, pady=5)

frame_result = ttk.Frame(root, padding="10")
frame_result.pack(fill=tk.BOTH, expand=True)

columns = ("match_type", "date_time", "amount", "rrn", "ka")
tree = ttk.Treeview(frame_result, columns=columns, show="headings")

tree.heading("match_type", text="Тип")
tree.heading("date_time", text="Дата и время")
tree.heading("amount", text="Сумма (Руб)")
tree.heading("rrn", text="RRN")
tree.heading("ka", text="Код авт. (К/А)")

tree.column("match_type", width=45, anchor=tk.CENTER)
tree.column("date_time", width=140, anchor=tk.W)
tree.column("amount", width=100, anchor=tk.E)
tree.column("rrn", width=180, anchor=tk.CENTER)
tree.column("ka", width=100, anchor=tk.CENTER)

scrollbar = ttk.Scrollbar(frame_result, orient=tk.VERTICAL, command=tree.yview)
tree.configure(yscrollcommand=auto_scroll)

tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

tree.bind("<Double-1>", lambda event: on_row_double_click(event, copy_ka=False))
tree.bind("<Shift-Double-1>", lambda event: on_row_double_click(event, copy_ka=True))
root.bind('<Return>', lambda event: perform_search())

def universal_paste(event=None):
    should_paste = False
    if event is None:
        should_paste = True
    else:
        if event.keysym in ('v', 'V', 'м', 'М') or event.keycode == 86:
            should_paste = True
            
    if should_paste:
        try:
            text = root.clipboard_get()
            if text:
                try:
                    entry_search.delete(tk.SEL_FIRST, tk.SEL_LAST)
                except tk.TclError:
                    pass
                entry_search.insert(tk.INSERT, text)
        except tk.TclError:
            pass
        return "break"

def show_context_menu(event):
    menu = tk.Menu(root, tearoff=0)
    menu.add_command(label="Вставить", command=universal_paste)
    menu.post(event.x_root, event.y_root)

entry_search.bind("<Control-KeyPress>", universal_paste)
entry_search.bind("<Button-3>", show_context_menu)

threading.Thread(target=update_database, daemon=True).start()

root.mainloop()
