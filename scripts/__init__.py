"""Пакет scripts: утилиты разработчика.

№71: раньше scripts/ не имел __init__.py. Тесты делали
`from scripts import check_caps` — работало на CI случайно
(namespace package + CWD). На чистой машине из другого места — упадёт.
Пустой __init__.py делает scripts/ полноценным пакетом.
"""