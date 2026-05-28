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
<!-- For non-trivial architectural choices, link the spec under
docs/superpowers/specs/ or attach an inline ADR section below. -->
Spec / ADR (optional):

## Як перевірено (local)

<!-- Що саме ти зробив, щоб переконатись що працює. Команди / endpoints / скриншоти. -->

```bash
# приклад:
docker compose up -d postgres redis
docker compose -f docker-compose.yml -f docker-compose.test.yml build api-test
docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps api-test pytest -q
docker compose run --rm api alembic upgrade head
curl -fsS http://localhost:8000/health
```

## Checklist

- [ ] `ruff check` + `ruff format` пройшли для змінених сервісів
- [ ] Тести зелені (для API: `docker compose -f docker-compose.yml -f docker-compose.test.yml run --rm --no-deps api-test pytest -q`)
- [ ] Якщо змінена схема БД — додано міграцію Alembic (`alembic revision --autogenerate -m "..."`)
- [ ] Якщо архітектурне рішення — додано spec у `docs/superpowers/specs/` (або inline ADR у тілі PR)
- [ ] Якщо змінений публічний API — оновлено відповідний `apps/<service>/README.md`
- [ ] Жодних секретів у diff (`.env`, токени, ключі)
- [ ] CI пройшов (workflow `CI` зелений)
