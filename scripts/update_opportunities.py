import json
import re
import sys
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("data.json")
HEADERS = {"User-Agent": "VMContratos/2.0 (+https://github.com/cuartiermorinlescayes-cpu/Vm-contratos)"}
EPEN_LIST = "https://www.epen.gov.ar/index.php/licitaciones/"
EPEN_BASE = "https://www.epen.gov.ar"
PROVINCIA_LIST = "https://licitaciones.neuquen.gov.ar/"
CODINEU_LIST = "https://codi.neuquen.gob.ar/PortalLicitaciones/servlet/com.portallicitaciones.wwlicitacion"
SALUD_LIST = "https://salud.neuquen.gob.ar/category/licitaciones/"
CADENA_VALOR = "https://cadenavalorneuquina.adeneu.com.ar/"
ADENEU_LICIT = "https://adeneu.com.ar/category/licitaciones-y-remates/"
ADENEU_RONDAS = "https://adeneu.com.ar/?s=ronda+de+negocios"
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
    r = requests.get(url, headers=HEADERS, timeout=35)
    r.raise_for_status()
    return r.text


def publication_date_from_url(url):
    m = re.search(r"/(20\d{2})/(\d{2})/(\d{2})/", url)
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def publication_date_from_soup(soup, url):
    for time in soup.find_all("time"):
        raw = time.get("datetime") or time.get_text(" ", strip=True)
        m = re.search(r"(20\d{2})-(\d{2})-(\d{2})", raw or "")
        if m:
            try:
                return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            except ValueError:
                pass
    return publication_date_from_url(url)


def parse_opening(raw):
    if not raw:
        return None
    s = clean(raw).lower().replace("hs.", "").replace("hs", "").replace("horas", "")
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](20\d{2}).{0,120}?(\d{1,2})[:.](\d{2})", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4)), int(m.group(5)))
        except ValueError:
            pass
    m = re.search(r"(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+del\s+año|\s+del|\s+de)?\s+(20\d{2}).{0,160}?(\d{1,2})[:.](\d{2})", s)
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
    if any(k in t for k in ["oracle", "informat", "software", "comput", "tecnolog", "base de datos", "licencia", "network", "backup", "nvme", "datacenter"]):
        return "Tecnología"
    if any(k in t for k in ["limpieza", "parquiz", "camill", "vigilancia", "seguridad", "servicio general"]):
        return "Servicios generales"
    if any(k in t for k in ["residuo", "patogeno", "ambiental"]):
        return "Ambiente"
    if any(k in t for k in ["agua", "saneamiento", "planta de saneamiento"]):
        return "Agua y saneamiento"
    if any(k in t for k in ["obra", "construccion", "refaccion", "reparacion", "edificio", "vivienda", "natatorio", "lotes"]):
        return "Obras"
    if any(k in t for k in ["energia", "electr", "transformador", "proteccion", "rele", "subestacion", "set "]):
        return "Energía"
    if any(k in t for k in ["alimento", "racionamiento", "carne", "comida"]):
        return "Alimentos"
    if any(k in t for k in ["salud", "hospital", "protesis", "medicamento", "laboratorio"]):
        return "Salud"
    return "Otros"


def iso(dt):
    return dt.isoformat() + "-03:00" if dt else None


def item_id(prefix, title, url):
    t = fold(title)
    m = re.search(r"licitacion\s+publica(?:\s+nacional)?\s*(?:n[.º°o\s]*)?(\d{1,4})(?:\s*/\s*(20\d{2}|\d{2}))?", t)
    if m:
        year = m.group(2) or str(date.today().year)
        if len(year) == 2:
            year = "20" + year
        return f"{prefix}-{m.group(1)}-{year}"
    slug = urlparse(url).path.strip("/").split("/")[-1] or fold(title)
    return prefix + "-" + re.sub(r"[^a-z0-9]+", "-", fold(slug)).strip("-")[:70]


def active_or_recent(opening, pub):
    today = date.today()
    if opening:
        return opening.date() >= today
    return bool(pub and pub >= today - timedelta(days=35))


def extract_epen_detail(url, fallback_title):
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
    pub = publication_date_from_soup(soup, url)
    today = date.today()
    status = "Abierta"
    note = None
    if opening and opening.date() < today:
        if pub and (today - pub).days <= 45:
            status = "Verificar fecha"
            note = "La fecha de apertura publicada ya pasó o puede haber sido modificada. Verificar la fuente oficial antes de ofertar."
            opening = None
        else:
            return None
    elif not opening:
        status = "Consultar fuente"
    item = {
        "id": item_id("EPEN", title, url), "organismo": "EPEN", "titulo": title,
        "rubro": classify(f"{title} {desc}"), "zona": "Neuquén", "estado": status,
        "apertura": iso(opening), "publicado": pub.isoformat() if pub else None,
        "descripcion": desc or "Consultar descripción y condiciones en la fuente oficial.", "fuente": url,
    }
    if note:
        item["nota"] = note
    return item


def scrape_epen(errors):
    out = []
    html = get(EPEN_LIST)
    soup = BeautifulSoup(html, "html.parser")
    seen = set()
    for a in soup.find_all("a", href=True):
        title = clean(a.get_text(" ", strip=True))
        href = urljoin(EPEN_BASE, a["href"])
        ft = fold(title)
        if f"/{date.today().year}/" not in href or not ("licitacion" in ft or re.search(r"\bl\.?\s*p\.?", ft)) or href in seen:
            continue
        seen.add(href)
        try:
            item = extract_epen_detail(href, title)
            if item:
                out.append(item)
        except Exception as exc:
            errors.append(f"EPEN {href}: {exc}")
    return out


def detail_to_item(url, organismo, prefix, canal=None):
    html = get(url)
    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find("h1") or soup.find("h2")
    title = clean(title_node.get_text(" ", strip=True) if title_node else "Licitación")
    text = clean(soup.get_text(" ", strip=True))
    pub = publication_date_from_soup(soup, url)
    opening = parse_opening(text)
    if not active_or_recent(opening, pub):
        return None
    number = re.search(r"Licitaci[oó]n\s+P[uú]blica(?:\s+Nacional)?\s*(?:N[º°o.]*)?\s*([0-9]+(?:/[0-9]{2,4})?)", text, re.I)
    label = f"Licitación Pública {number.group(1)} — {title}" if number and "licitación" not in fold(title) else title
    desc_match = re.search(r"Objeto:\s*(.*?)(?:Destino:|Importe|Presupuesto|Fecha\s*[-–:]|Fecha de Apertura:)", text, re.I)
    desc = clean(desc_match.group(1)) if desc_match else "Consultar objeto, pliego y condiciones en la fuente oficial."
    item = {
        "id": item_id(prefix, label, url), "organismo": organismo, "titulo": label,
        "rubro": classify(f"{label} {desc}"), "zona": "Neuquén", "estado": "Abierta" if opening else "Consultar fuente",
        "apertura": iso(opening), "publicado": pub.isoformat() if pub else None,
        "descripcion": desc, "fuente": url,
    }
    if canal:
        item["canal"] = canal
    return item


def scrape_salud(errors):
    out, seen = [], set()
    try:
        soup = BeautifulSoup(get(SALUD_LIST), "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(SALUD_LIST, a["href"])
            label = fold(a.get_text(" ", strip=True))
            if "salud.neuquen.gob.ar" not in href or href in seen or "/category/" in href:
                continue
            if not ("objeto" in label or "licit" in label):
                continue
            seen.add(href)
            try:
                item = detail_to_item(href, "Ministerio de Salud / CO.DI.NEU.", "SALUD", "CO.DI.NEU.")
                if item:
                    out.append(item)
            except Exception as exc:
                errors.append(f"Salud {href}: {exc}")
    except Exception as exc:
        errors.append(f"Salud listado: {exc}")
    return out


def scrape_generic_procurement(url, organismo, prefix, errors, canal=None):
    out, fingerprints = [], set()
    try:
        soup = BeautifulSoup(get(url), "html.parser")
    except Exception as exc:
        errors.append(f"{organismo} listado: {exc}")
        return out
    nodes = soup.find_all(["tr", "article", "li", "section", "div"])
    for node in nodes:
        text = clean(node.get_text(" ", strip=True))
        ft = fold(text)
        if len(text) < 35 or len(text) > 1800 or "licit" not in ft:
            continue
        opening = parse_opening(text)
        if not opening or opening.date() < date.today():
            continue
        fp = fold(text)[:180]
        if fp in fingerprints:
            continue
        fingerprints.add(fp)
        a = node.find("a", href=True)
        href = urljoin(url, a["href"]) if a else url
        m = re.search(r"(Licitaci[oó]n\s+P[uú]blica(?:\s+Nacional)?\s*(?:N[º°o.]*)?\s*[0-9]+(?:/[0-9]{2,4})?[^.]{0,180})", text, re.I)
        title = clean(m.group(1)) if m else clean(text[:180])
        desc = clean(text[:500])
        item = {
            "id": item_id(prefix, title, href), "organismo": organismo, "titulo": title,
            "rubro": classify(text), "zona": "Neuquén", "estado": "Abierta", "apertura": iso(opening),
            "publicado": None, "descripcion": desc, "fuente": href,
        }
        if canal:
            item["canal"] = canal
        out.append(item)
    return out


def scrape_adeneu(errors):
    out, links = [], set()
    for listing in (ADENEU_LICIT, ADENEU_RONDAS):
        try:
            soup = BeautifulSoup(get(listing), "html.parser")
            for a in soup.find_all("a", href=True):
                label = clean(a.get_text(" ", strip=True))
                fl = fold(label)
                href = urljoin(listing, a["href"])
                if "adeneu.com.ar" not in href or href in links:
                    continue
                if not any(k in fl for k in ["licitacion", "concurso de precios", "ronda de negocios"]):
                    continue
                links.add(href)
                try:
                    html = get(href)
                    detail = BeautifulSoup(html, "html.parser")
                    text = clean(detail.get_text(" ", strip=True))
                    pub = publication_date_from_soup(detail, href)
                    opening = parse_opening(text)
                    if opening and opening.date() < date.today():
                        continue
                    if not opening and not (pub and pub >= date.today() - timedelta(days=30)):
                        continue
                    h1 = detail.find("h1")
                    title = clean(h1.get_text(" ", strip=True) if h1 else label)
                    status = "Convocatoria" if "ronda de negocios" in fold(text) else "Consultar fuente"
                    out.append({
                        "id": item_id("ADENEU", title, href), "organismo": "Cadena de Valor Neuquina / ADENEU",
                        "titulo": title, "rubro": "Vinculación comercial" if status == "Convocatoria" else classify(text),
                        "zona": "Neuquén / Vaca Muerta", "estado": status, "apertura": iso(opening),
                        "publicado": pub.isoformat() if pub else None,
                        "descripcion": "Oportunidad de vinculación, compra o convocatoria empresarial. Revisar requisitos y vigencia en la publicación oficial.",
                        "fuente": href,
                    })
                except Exception as exc:
                    errors.append(f"ADENEU {href}: {exc}")
        except Exception as exc:
            errors.append(f"ADENEU listado {listing}: {exc}")
    return out


def official_current_seeds():
    seeds = [
        {
            "id": "EPAS-SAFIPRO-4202-2026", "organismo": "EPAS / CO.DI.NEU.",
            "titulo": "Solicitud de Provisión SAFIPRO 4202 — Equipamiento para la Planta de Saneamiento de San Martín de los Andes",
            "rubro": "Agua y saneamiento", "zona": "San Martín de los Andes", "estado": "Abierta",
            "apertura": "2026-09-25T10:00:00-03:00", "publicado": "2026-09-15",
            "descripcion": "Adquisición de equipamiento para la Planta de Saneamiento de San Martín de los Andes.",
            "canal": "CO.DI.NEU.", "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1959"
        },
        {
            "id": "SALUD-19-2026", "organismo": "Ministerio de Salud / CO.DI.NEU.",
            "titulo": "Licitación Pública 19/2026 — Servicio de limpieza integral, parquización y camilleros",
            "rubro": "Servicios generales", "zona": "Neuquén", "estado": "Abierta",
            "apertura": "2026-09-30T11:00:00-03:00", "publicado": "2026-09-15",
            "descripcion": "Servicio para hospitales y centros de salud de la Provincia del Neuquén.",
            "canal": "CO.DI.NEU.", "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1959"
        },
        {
            "id": "OPTIC-22-2026", "organismo": "Provincia del Neuquén / OPTIC",
            "titulo": "Licitación Pública 22/2026 — Solución integral de backup y almacenamiento NVMe",
            "rubro": "Tecnología", "zona": "Neuquén", "estado": "Abierta",
            "apertura": "2026-09-25T10:00:00-03:00", "publicado": "2026-09-11",
            "descripcion": "Adquisición de solución integral de backup y almacenamiento de alta performance, con hardware, software, instalación, capacitación y soporte.",
            "canal": "CO.DI.NEU.", "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1956"
        },
        {
            "id": "OPTIC-26-2026", "organismo": "Provincia del Neuquén / OPTIC",
            "titulo": "Licitación Pública 26/2026 — Soporte y reequipamiento de networking de datacenters provinciales",
            "rubro": "Tecnología", "zona": "Neuquén", "estado": "Abierta",
            "apertura": "2026-09-24T10:00:00-03:00", "publicado": "2026-09-11",
            "descripcion": "Soporte preventivo y correctivo, adecuación técnica, licenciamiento y reequipamiento de networking para datacenters provinciales.",
            "canal": "CO.DI.NEU.", "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1956"
        },
        {
            "id": "SALUD-18-2026", "organismo": "Ministerio de Salud / CO.DI.NEU.",
            "titulo": "Licitación Pública 18/2026 — Servicio de seguridad y control de accesos",
            "rubro": "Servicios generales", "zona": "Neuquén", "estado": "Abierta",
            "apertura": "2026-09-28T11:00:00-03:00", "publicado": "2026-09-11",
            "descripcion": "Servicio de seguridad para control de accesos, circulación y orientación al público en hospitales y centros de salud.",
            "canal": "CO.DI.NEU.", "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1956"
        },
        {
            "id": "SMA-04-2026", "organismo": "Municipalidad de San Martín de los Andes",
            "titulo": "Licitación Pública 04/2026 — Recolección, transporte, tratamiento y disposición de residuos patógenos",
            "rubro": "Ambiente", "zona": "San Martín de los Andes", "estado": "Abierta",
            "apertura": "2026-09-23T10:00:00-03:00", "publicado": "2026-09-11",
            "descripcion": "Concesión del servicio de recolección, transporte, tratamiento y disposición final de residuos patógenos.",
            "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1956"
        },
        {
            "id": "OBRAS-10-2026", "organismo": "Secretaría de Obras Públicas",
            "titulo": "Licitación Pública 10/2026 — Escuela 86: refacción, ampliación y SUM, San Martín de los Andes",
            "rubro": "Obras", "zona": "San Martín de los Andes", "estado": "Abierta",
            "apertura": "2026-09-28T12:00:00-03:00", "publicado": "2026-09-11",
            "descripcion": "Circular modificatoria: obra de refacción, ampliación y SUM de la Escuela N° 86.",
            "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1956"
        },
        {
            "id": "UPEFE-07-2026", "organismo": "UPEFE / Provincia del Neuquén",
            "titulo": "Licitación Pública 07/2026 — Nuevo natatorio olímpico, Neuquén Capital",
            "rubro": "Obras", "zona": "Neuquén Capital", "estado": "Abierta",
            "apertura": "2026-10-14T13:00:00-03:00", "publicado": "2026-09-11",
            "descripcion": "Obra del Plan Neuquén Vive para un nuevo natatorio olímpico en Neuquén Capital.",
            "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1956"
        },
        {
            "id": "POLICIA-79-2026", "organismo": "Policía de la Provincia del Neuquén",
            "titulo": "Licitación Pública 79/2026 — Racionamiento elaborado para unidades de detención de Zapala",
            "rubro": "Alimentos", "zona": "Zapala", "estado": "Abierta",
            "apertura": "2026-09-30T10:00:00-03:00", "publicado": "2026-09-04",
            "descripcion": "Adquisición de racionamiento elaborado para internos alojados en unidades de detención y comisaría de Zapala.",
            "canal": "CO.DI.NEU.", "fuente": "https://infoleg.neuquen.gov.ar/BoletinDetalle?Id=1954"
        },
        {
            "id": "UPEFE-LPN-01-2026", "organismo": "UPEFE / Provincia del Neuquén",
            "titulo": "Licitación Pública Nacional 01/2026 — Construcción de 10 viviendas e infraestructura en Neuquén Capital",
            "rubro": "Obras", "zona": "Neuquén Capital", "estado": "Abierta",
            "apertura": "2026-09-30T13:00:00-03:00", "publicado": "2026-09-07",
            "descripcion": "Construcción de diez viviendas, infraestructura y plan de reasentamiento para barrios Pacífica, Morro y Juvenil.",
            "fuente": "https://www.boletinoficial.gov.ar/detalleAviso/tercera/2417086/20260907"
        },
    ]
    today = date.today()
    return [s for s in seeds if datetime.fromisoformat(s["apertura"]).date() >= today]


def merge(items):
    chosen = {}
    for item in items:
        if not item:
            continue
        key = item.get("id") or fold(item.get("titulo", ""))
        old = chosen.get(key)
        if not old or (item.get("publicado") or "") > (old.get("publicado") or ""):
            chosen[key] = item
    result = list(chosen.values())
    result.sort(key=lambda o: (o.get("apertura") is None, o.get("apertura") or "9999", o.get("titulo") or ""))
    return result


def main():
    errors = []
    opportunities = []
    for label, fn in [
        ("EPEN", lambda: scrape_epen(errors)),
        ("Salud", lambda: scrape_salud(errors)),
        ("Provincia", lambda: scrape_generic_procurement(PROVINCIA_LIST, "Provincia del Neuquén", "NQN", errors)),
        ("CO.DI.NEU.", lambda: scrape_generic_procurement(CODINEU_LIST, "CO.DI.NEU.", "CODI", errors, "CO.DI.NEU.")),
        ("Cadena de Valor", lambda: scrape_adeneu(errors)),
    ]:
        try:
            opportunities.extend(fn())
        except Exception as exc:
            errors.append(f"{label}: {exc}")

    opportunities.extend(official_current_seeds())
    opportunities = merge(opportunities)
    if not opportunities:
        print("No se extrajeron oportunidades; se conserva data.json existente.", file=sys.stderr)
        for e in errors:
            print(e, file=sys.stderr)
        sys.exit(1)

    payload = {
        "updated": datetime.now().astimezone().isoformat(timespec="seconds"),
        "automatic_update": True,
        "update_frequency_hours": 6,
        "sources": {
            "EPEN": EPEN_LIST,
            "Provincia del Neuquén": PROVINCIA_LIST,
            "CO.DI.NEU.": CODINEU_LIST,
            "Ministerio de Salud": SALUD_LIST,
            "Cadena de Valor Neuquina": CADENA_VALOR,
            "Centro PyME-ADENEU": ADENEU_LICIT,
        },
        "source_count": 6,
        "opportunities": opportunities,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Actualizadas {len(opportunities)} oportunidades desde {payload['source_count']} fuentes.")
    if errors:
        print(f"Advertencias: {len(errors)} fuentes o páginas no pudieron procesarse completamente.", file=sys.stderr)
        for e in errors[:20]:
            print(e, file=sys.stderr)


if __name__ == "__main__":
    main()
