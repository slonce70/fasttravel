<!--
Дякую за PR! Заповни секції нижче — це економить час реверсу і прискорює рев'ю.
Видали підказки в коментарях перед submit.
-->

## Що змінено

<!-- Стисло: 1–3 буліти про конкретні зміни (файли/модулі/поведінка). -->

-
-

## Чому

<!-- Який use-case / баг / decision стоїть за зміною. Лінкуй issue / ADR. -->

Closes #
Related ADR: docs/DECISIONS.md#

## Як перевірено (local)

<!-- Що саме ти зробив, щоб переконатись що працює. Команди / endpoints / скриншоти. -->

```bash
# приклад:
docker compose up -d postgres redis
cd apps/api && poetry run pytest
poetry run alembic upgrade head
curl -fsS http://localhost:8000/health
```

## Checklist

- [ ] `ruff check` + `ruff format` пройшли (`cd apps/api && poetry run ruff check src/ tests/`)
- [ ] Тести зелені (`poetry run pytest`)
- [ ] Якщо змінена схема БД — додано міграцію Alembic (`alembic revision --autogenerate -m "..."`)
- [ ] Якщо архітектурне рішення — додано/оновлено запис у `docs/DECISIONS.md`
- [ ] Якщо змінений публічний API — оновлено `docs/ARCHITECTURE.md` / README
- [ ] Жодних секретів у diff (`.env`, токени, ключі)
- [ ] CI пройшов (workflow `CI` зелений)
