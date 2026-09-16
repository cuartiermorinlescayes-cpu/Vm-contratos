import json
import re
import sys
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

LIST_URL = "https://www.epen.gov.ar/index.php/licitaciones/"
BASE = "https://www.epen.gov.ar"
OUT = Path("data.json")
HEADERS = {"User-Agent": "VMContratos/1.0 (+https://github.com/cuartiermorinlescayes-cpu/Vm-contratos)"}
MONTHS = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "setiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}


def clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def fold(s):
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn").lower()


def get(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


def publication_date(url):
    m = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", url)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def parse_opening(raw):
    if not raw:
        return None
    s = clean(raw).lower().replace("hs.", "").replace("horas", "")
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](20\d{2}).*?(\d{1,2})[:.](\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4)), int(m.group(5)))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+del\s+año|\s+de)?\s+(20\d{2}).*?(\d{1,2})[:.](\d{2})", s)
    if m:
        month = MONTHS.get(fold(m.group(2)))
        if month:
            try:
                return datetime(int(m.group(3)), month, int(m.group(1)), int(m.group(4)), int(m.group(5)))
            except ValueError:
                pass
    return None


def classify(text):
    t = fold(text)
    if any(k in t for k in ["oracle", "informat", "software", "comput", "tecnolog", "base de datos", "licencia"]):
        return "Tecnología"
    if any(k in t for k in ["limpieza", "mantenimiento", "servicio general"]):
        return "Servicios generales"
    if any(k in t for k in ["obra", "construccion", "refaccion", "reparacion", "edificio"]):
        return "Obras"
    if any(k in t for k in ["energia", "electr", "transformador", "proteccion", "rele", "subestacion", "set "]):
        return "Energía"
    return "Otros"


def make_id(title, url):
    m = re.search(r"(?:n[.º°o\s]*|lp\s*)?(\d{1,3})\s*/\s*(20\d{2})", fold(title))
    if m:
        return f"EPEN-{m.group(1)}-{m.group(2)}"
    slug = urlparse(url).path.strip("/").split("/")[-1]
    return "EPEN-" + re.sub(r"[^a-z0-9]+", "-", fold(slug)).strip("-")[:60]


def extract_detail(url, fallback_title):
    html = get(url)
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = clean(h1.get_text(" ", strip=True) if h1 else fallback_title)
    text = clean(soup.get_text(" ", strip=True))

    desc = ""
    m = re.search(r"Descripci[oó]n:\s*(.*?)\s*(?:Monto total estimado:|Fecha de apertura:)", text, re.I)
    if not m:
        m = re.search(r"Objeto:\s*(.*?)\s*(?:Presupuesto Oficial:|Monto total estimado:|Fecha de apertura:)", text, re.I)
    if m:
        desc = clean(m.group(1))

    opening_raw = ""
    m = re.search(r"Fecha de apertura:\s*(.*?)\s*(?:Lugar de apertura:|Recepci[oó]n de ofertas:|Observaciones:|Pliego:)", text, re.I)
    if m:
        opening_raw = clean(m.group(1))
    opening = parse_opening(opening_raw)

    pub = publication_date(url)
    today = date.today()
    status = "Abierta"
    note = None
    if opening and opening.date() < today:
        if pub and (today - pub).days <= 45:
            status = "Verificar fecha"
            note = "La fecha de apertura publicada por la fuente oficial ya pasó o puede haber sido modificada. Verificar la publicación antes de ofertar."
        else:
            return None
    elif not opening:
        status = "Consultar fuente"

    full = f"{title} {desc}"
    item = {
        "id": make_id(title, url),
        "organismo": "EPEN",
        "titulo": title,
        "rubro": classify(full),
        "zona": "Neuquén",
        "estado": status,
        "apertura": opening.isoformat() + "-03:00" if opening else None,
        "publicado": pub.isoformat() if pub else None,
        "descripcion": desc or "Consultar descripción y condiciones en la fuente oficial.",
        "fuente": url,
    }
    if opening_raw:
        item["apertura_texto_fuente"] = opening_raw
    if note:
        item["nota"] = note
    return item


def main():
    html = get(LIST_URL)
    soup = BeautifulSoup(html, "html.parser")
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        title = clean(a.get_text(" ", strip=True))
        href = urljoin(BASE, a["href"])
        ft = fold(title)
        if "/2026/" not in href:
            continue
        if not ("licitacion" in ft or re.search(r"\bl\.?\s*p\.?", ft)):
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append((href, title))

    opportunities = []
    errors = []
    for url, title in links[:40]:
        try:
            item = extract_detail(url, title)
            if item:
                opportunities.append(item)
        except Exception as exc:
            errors.append(f"{url}: {exc}")

    if not opportunities:
        print("No se extrajeron oportunidades; se conserva data.json existente.", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)

    opportunities.sort(key=lambda o: (o.get("apertura") is None, o.get("apertura") or "9999", o.get("titulo") or ""))
    payload = {
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "automatic_update": True,
        "sources": {"EPEN": LIST_URL},
        "opportunities": opportunities,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Actualizadas {len(opportunities)} oportunidades de EPEN.")
    if errors:
        print(f"Advertencias: {len(errors)} páginas no pudieron procesarse.")


if __name__ == "__main__":
    main()
