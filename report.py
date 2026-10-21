import argparse
from collections import Counter
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


def normalize_vacancy(item):
    return {
        "id": str(item["id"]),
        "name": item["title"],
        "company": item.get("company_name") or "Не указана",
        "category": item.get("category") or "Не указана",
        "job_type": item.get("job_type") or "Не указан",
        "location": item.get("candidate_required_location") or "Не указано",
        "salary": item.get("salary") or "",
        "url": item.get("url") or "",
    }


def unique_vacancies(items):
    seen = set()
    result = []
    for item in items:
        if item["id"] not in seen:
            seen.add(item["id"])
            result.append(item)
    return result


def select_vacancies(items, keyword):
    return [item for item in items if keyword.casefold() in item["name"].casefold()]


def summarize(items):
    return {
        "count": len(items),
        "companies": Counter(item["company"] for item in items).most_common(),
        "categories": Counter(item["category"] for item in items).most_common(),
        "job_types": Counter(item["job_type"] for item in items).most_common(),
        "salary_count": sum(bool(item["salary"].strip()) for item in items),
        "vacancies": items,
    }


def markdown_cell(value):
    text = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    for character in ("\\", "`", "*", "_", "[", "]", "|"):
        text = text.replace(character, "\\" + character)
    return text.replace("\n", " ").replace("\r", " ")


def vacancy_link(url):
    try:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in ("remotive.com", "www.remotive.com"):
            return "—"
    except ValueError:
        return "—"
    safe_url = url.replace("<", "%3C").replace(">", "%3E").replace("\n", "").replace("\r", "")
    return f"[Remotive](<{safe_url}>)"


def render_markdown(summary):
    lines = ["# Обзор вакансий", "",
             f"Вакансий: {summary['count']}", "",
             f"С указанной зарплатой: {summary['salary_count']}", "",
             "Отчёт описывает только полученную выборку. Зарплаты приведены как в источнике: "
             "валюты и периоды выплат могут отличаться, среднее не рассчитывается."]
    for heading, key in (("Компании", "companies"), ("Категории", "categories"),
                         ("Типы занятости", "job_types")):
        lines.extend(["", f"## {heading}", "", "| Значение | Вакансий |", "| --- | ---: |"])
        lines.extend(f"| {markdown_cell(name)} | {count} |" for name, count in summary[key])
    lines.extend(["", "## Вакансии", "",
                  "| Название | Компания | География | Зарплата | Источник |",
                  "| --- | --- | --- | --- | --- |"])
    for item in summary["vacancies"]:
        cells = [markdown_cell(item[key] or "Не указана")
                 for key in ("name", "company", "location", "salary")]
        cells.append(vacancy_link(item["url"]))
        lines.append("| " + " | ".join(cells) + " |")
    if not summary["count"]:
        lines.extend(["", "По заданному фильтру вакансий нет."])
    return "\n".join(lines) + "\n"


def fetch_vacancies(query):
    url = "https://remotive.com/api/remote-jobs?" + urlencode({"search": query, "limit": 100})
    request = Request(url, headers={"User-Agent": "VacancyReport/1.0"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code in (403, 429):
            raise ValueError(
                f"Remotive ограничил доступ (HTTP {error.code}). "
                "Не повторяйте запросы часто; попробуйте позже или используйте --input example.json."
            ) from error
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input", type=Path, help="JSON Remotive с массивом jobs")
    source.add_argument("--fetch", metavar="QUERY", help="Поиск в Remotive, например python")
    parser.add_argument("--keyword", default="", help="Подстрока в названии вакансии")
    parser.add_argument("--output", type=Path, default=Path("report.md"))
    args = parser.parse_args()
    try:
        data = json.loads(args.input.read_text(encoding="utf-8")) if args.input else fetch_vacancies(args.fetch)
        if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
            raise ValueError("Ожидается JSON-объект Remotive с массивом jobs")
        vacancies = unique_vacancies([normalize_vacancy(item) for item in data["jobs"]])
        selected = select_vacancies(vacancies, args.keyword)
        args.output.write_text(render_markdown(summarize(selected)), encoding="utf-8")
    except (OSError, URLError, ValueError, KeyError, TypeError, AttributeError) as error:
        parser.exit(1, f"Не удалось построить отчёт: {error}\n")
    print(f"Отчёт сохранён: {args.output} (вакансий: {len(selected)})")


if __name__ == "__main__":
    main()
