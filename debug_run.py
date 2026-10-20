import traceback
import sys

try:
    print("Запуск основного скрипта в режиме отладки...")
    # Принудительно импортируем ваш скрипт как модуль, перехватывая любые ошибки
    import app
except Exception as e:
    # Если скрипт падает, этот блок намертво перехватит ошибку и запишет на диск
    error_msg = traceback.format_exc()
    print("ОБНАРУЖЕНА КРИТИЧЕСКАЯ ОШИБКА!")
    print(error_msg)
    
    with open("error_log.txt", "w", encoding="utf-8") as f:
        f.write("=== ЛОГ КРИТИЧЕСКОЙ ОШИБКИ ЗАПУСКА ===\n")
        f.write(error_msg)
    
    input("\nНажмите Enter для выхода...")
