import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


OUT = Path("jobs.json")
BASE_URL = "https://oportunidades.ypf.com"
SEARCH_URL = f"{BASE_URL}/search/"
HEADERS = {
    "User-Agent": (
        "VMContratos/2.0 "
        "(+https://github.com/cuartiermorinlescayes-cpu/Vm-contratos)"
    )
}
VACA_MUERTA_LOCATIONS = (
    "neuquen",
    "anelo",
    "rincon de los sauces",
    "plaza huincul",
    "cutral co",
    "catriel",
)


def clean(value):
    return re.sub(r"\s+", " ", value or "").strip()


def fold(value):
    normalized = unicodedata.normalize("NFD", value or "")
    return "".join(
        character
        for character in normalized
        if unicodedata.category(character) != "Mn"
    ).lower()


def field(tile, suffix):
    node = tile.select_one(f'[id$="-desktop-section-{suffix}-value"]')
    return clean(node.get_text(" ", strip=True)) if node else ""


def display_title(value):
    words = clean(value).title().split()
    replacements = {
        "Iiss": "IISS",
        "Up": "UP",
        "Sp": "SP",
        "Tecnico": "Técnico",
        "Logistica": "Logística",
        "Permisologia": "Permisología",
    }
    return " ".join(replacements.get(word, word) for word in words)


def display_location(value):
    location = clean(value).title()
    return "Neuquén" if fold(location) == "neuquen" else location


def fetch_page(startrow):
    response = requests.get(
        SEARCH_URL,
        params={
            "q": "",
            "sortColumn": "referencedate",
            "sortDirection": "desc",
            "startrow": startrow,
        },
        headers=HEADERS,
        timeout=40,
    )
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def parse_jobs():
    jobs = {}

    # SuccessFactors muestra 25 resultados por página. El límite evita que un
    # cambio inesperado del portal convierta la tarea programada en un bucle.
    for startrow in range(0, 100, 25):
        soup = fetch_page(startrow)
        tiles = soup.select("li.job-tile")
        if not tiles:
            break

        new_ids = 0
        for tile in tiles:
            link = tile.select_one(".sub-section-desktop a.jobTitle-link")
            if not link:
                continue

            vacancy_id = field(tile, "customfield1")
            title = clean(link.get_text(" ", strip=True))
            published = field(tile, "date")
            category = field(tile, "department")
            company = field(tile, "customfield2")
            location = field(tile, "customfield3")

            # El proyecto publica únicamente búsquedas de YPF vinculadas con
            # Neuquén/Vaca Muerta, no las demás sociedades del portal.
            if fold(company) != "ypf":
                continue
            if not any(place in fold(location) for place in VACA_MUERTA_LOCATIONS):
                continue

            href = link.get("href")
            if not vacancy_id or not title or not href:
                continue
            job_id = f"YPF-{vacancy_id}"
            if job_id in jobs:
                continue

            jobs[job_id] = {
                "id": job_id,
                "titulo": display_title(title),
                "empresa": "YPF",
                "ubicacion": display_location(location),
                "categoria": category or "Consultar publicación oficial",
                "publicado": published,
                "descripcion": (
                    f"Vacante oficial de YPF para {display_title(title)} en "
                    f"{display_location(location)}. Consultá los requisitos, tareas y "
                    "vigencia en la publicación oficial."
                ),
                "fuente": urljoin(BASE_URL, href),
            }
            new_ids += 1

        if len(tiles) < 25 or new_ids == 0:
            break

    return list(jobs.values())


def main():
    jobs = parse_jobs()
    if not jobs:
        print(
            "No se encontraron vacantes YPF para Neuquén/Vaca Muerta; "
            "se conserva jobs.json existente.",
            file=sys.stderr,
        )
        sys.exit(1)

    payload = {
        "updated": date.today().isoformat(),
        "automatic_update": True,
        "update_frequency_hours": 6,
        "source": "Portal oficial de empleos de YPF",
        "source_url": SEARCH_URL,
        "jobs": jobs,
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Actualizados {len(jobs)} empleos oficiales de YPF.")


if __name__ == "__main__":
    main()
