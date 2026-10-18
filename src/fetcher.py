"""
Module fetcher.py pour EcoRadar-Autopilot.
Interroge les API publiques officielles (Carburants, EDF Tempo, Communes de France)
avec timeouts, backoff exponentiel et fallback SQLite.
"""

import time
import json
import logging
import re
import unicodedata
from typing import Dict, Any, List, Optional, Tuple
import requests

from src.database import (
    save_tempo_state, save_fuel_snapshot, get_latest_fuel_snapshot, log_event
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
logger = logging.getLogger("EcoRadar.Fetcher")

USER_AGENT = "EcoRadar-Autopilot/1.0 (+https://github.com/EcoRadar-France/EcoRadar-Autopilot)"
HEADERS = {"User-Agent": USER_AGENT, "Accept": "application/json"}
REQUEST_TIMEOUT = 12


def slugify(text: str) -> str:
    """Transforme une chaîne de texte en slug URL propre pour le SEO."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("utf-8")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")


def robust_get(url: str, params: Optional[Dict[str, Any]] = None, max_retries: int = 3) -> Optional[requests.Response]:
    """Exécute une requête GET avec backoff exponentiel et gestion d'erreurs."""
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 200:
                return resp
            logger.warning(f"Tentative {attempt}/{max_retries} - HTTP {resp.status_code} sur {url}")
        except (requests.RequestException, Exception) as exc:
            logger.warning(f"Tentative {attempt}/{max_retries} échouée pour {url} : {exc}")
        
        if attempt < max_retries:
            time.sleep(backoff)
            backoff *= 2.0

    return None


def fetch_tempo_data() -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Récupère la couleur Tempo EDF pour aujourd'hui et demain.
    Fallback sur valeurs par défaut si indisponible.
    """
    url_today = "https://www.api-couleur-tempo.fr/api/jourTempo/today"
    url_tomorrow = "https://www.api-couleur-tempo.fr/api/jourTempo/tomorrow"

    today_data = {"dateJour": "", "codeJour": 1, "couleur": "BLEU", "libCouleur": "Bleu"}
    tomorrow_data = {"dateJour": "", "codeJour": 0, "couleur": "INDETERMINE", "libCouleur": "Non communiqué"}

    resp_today = robust_get(url_today)
    if resp_today:
        try:
            d = resp_today.json()
            couleur_brute = d.get("libCouleur", "BLEU").upper()
            today_data = {
                "dateJour": d.get("dateJour", ""),
                "codeJour": d.get("codeJour", 1),
                "couleur": couleur_brute,
                "libCouleur": d.get("libCouleur", "Bleu").capitalize()
            }
        except Exception as e:
            logger.error(f"Erreur décodage Tempo Today : {e}")

    resp_tomorrow = robust_get(url_tomorrow)
    if resp_tomorrow:
        try:
            d = resp_tomorrow.json()
            couleur_brute = d.get("libCouleur", "INDETERMINE").upper()
            tomorrow_data = {
                "dateJour": d.get("dateJour", ""),
                "codeJour": d.get("codeJour", 0),
                "couleur": couleur_brute,
                "libCouleur": d.get("libCouleur", "Non communiqué").capitalize()
            }
        except Exception as e:
            logger.error(f"Erreur décodage Tempo Tomorrow : {e}")

    save_tempo_state(today_data, tomorrow_data)
    log_event("TEMPO_FETCH", "SUCCESS", f"Aujourd'hui: {today_data['couleur']} | Demain: {tomorrow_data['couleur']}")
    return today_data, tomorrow_data


def fetch_top_french_cities(limit: int = 150) -> List[Dict[str, Any]]:
    """
    Récupère les communes les plus peuplées de France via geo.api.gouv.fr.
    """
    url = "https://geo.api.gouv.fr/communes"
    params = {
        "fields": "nom,code,codesPostaux,population,departement,region,centre",
        "format": "json",
        "geometry": "centre"
    }
    resp = robust_get(url, params=params)
    if not resp:
        logger.error("Impossible de joindre geo.api.gouv.fr")
        return []

    try:
        data = resp.json()
        valid_cities = []
        for item in data:
            pop = item.get("population") or 0
            code = item.get("code") or ""
            # Exclure les collectivités d'outre-mer non couvertes par le flux métropolitain de carburants
            if code.startswith("97") or code.startswith("98"):
                continue

            centre = item.get("centre") or {}
            coords = centre.get("coordinates") or []
            if pop > 0 and len(coords) == 2:
                lon, lat = coords[0], coords[1]
                slug = f"{slugify(item['nom'])}-{item['code']}"
                valid_cities.append({
                    "code": item["code"],
                    "nom": item["nom"],
                    "slug": slug,
                    "codesPostaux": item.get("codesPostaux", []),
                    "departement": item.get("departement", {}).get("nom") if isinstance(item.get("departement"), dict) else item.get("codeDepartement"),
                    "region": item.get("region", {}).get("nom") if isinstance(item.get("region"), dict) else None,
                    "population": pop,
                    "latitude": lat,
                    "longitude": lon,
                    "status": "active"
                })

        valid_cities.sort(key=lambda x: x["population"], reverse=True)
        return valid_cities[:limit]
    except Exception as e:
        logger.error(f"Erreur lors du traitement des communes : {e}")
        return []


def parse_station_record(record: Dict[str, Any]) -> Dict[str, Any]:
    """Nettoie et extrait les attributs utiles d'un enregistrement de station."""
    geom = record.get("geom") or {}
    services_list = record.get("services_service") or []
    if isinstance(services_list, str):
        services_list = [s.strip() for s in services_list.split(",") if s.strip()]

    return {
        "id": record.get("id"),
        "adresse": record.get("adresse", "Adresse non communiquée"),
        "ville": record.get("ville", ""),
        "cp": record.get("cp", ""),
        "latitude": geom.get("lat"),
        "longitude": geom.get("lon"),
        "services": services_list,
        "automate_24_24": record.get("horaires_automate_24_24") == "Oui",
        "gazole": record.get("gazole_prix"),
        "gazole_maj": record.get("gazole_maj"),
        "sp95": record.get("sp95_prix"),
        "sp95_maj": record.get("sp95_maj"),
        "sp98": record.get("sp98_prix"),
        "sp98_maj": record.get("sp98_maj"),
        "e10": record.get("e10_prix"),
        "e10_maj": record.get("e10_maj"),
        "e85": record.get("e85_prix"),
        "e85_maj": record.get("e85_maj"),
        "gplc": record.get("gplc_prix"),
        "gplc_maj": record.get("gplc_maj")
    }


def compute_fuel_metrics(stations: List[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    """Calcule les moyennes et minima pour les 6 carburants officiels."""
    fuels = ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]
    metrics: Dict[str, Optional[float]] = {}

    for f in fuels:
        prices = [s[f] for s in stations if s.get(f) is not None and s[f] > 0]
        if prices:
            metrics[f"avg_{f}"] = round(sum(prices) / len(prices), 3)
            metrics[f"min_{f}"] = round(min(prices), 3)
        else:
            metrics[f"avg_{f}"] = None
            metrics[f"min_{f}"] = None

    return metrics


def fetch_fuel_for_city(city: Dict[str, Any], radius_km: int = 12) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Interroge l'API OpenDataSoft du Ministère de l'Économie pour récupérer
    les stations-service autour de la commune.
    Fallback sur SQLite si échec réseau.
    """
    code_insee = city["code_insee"] if "code_insee" in city else city["code"]
    lat = city.get("latitude")
    lon = city.get("longitude")

    if lat is None or lon is None:
        logger.warning(f"Coordonnées manquantes pour {city.get('nom')}")
        cached = get_latest_fuel_snapshot(code_insee)
        if cached:
            return cached, cached.get("stations", [])
        return {}, []

    url = "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/records"
    where_clause = f"within_distance(geom, geom'POINT({lon} {lat})', {radius_km}km)"
    params = {
        "where": where_clause,
        "limit": 50,
        "order_by": "gazole_prix asc"
    }

    resp = robust_get(url, params=params)

    # Si aucune station à rayon standard et rayon < 25, tentative d'extension
    if resp:
        try:
            data = resp.json()
            results = data.get("results", [])
            if len(results) == 0 and radius_km < 25:
                extended_where = f"within_distance(geom, geom'POINT({lon} {lat})', 25km)"
                resp_ext = robust_get(url, params={"where": extended_where, "limit": 40})
                if resp_ext:
                    data = resp_ext.json()
                    results = data.get("results", [])

            stations = [parse_station_record(r) for r in results]
            metrics = compute_fuel_metrics(stations)
            
            # Sauvegarde en base SQLite
            save_fuel_snapshot(code_insee, metrics, stations)
            return metrics, stations
        except Exception as e:
            logger.error(f"Erreur analyse réponse carburant pour {city.get('nom')} : {e}")

    # Fallback sur le cache SQLite
    logger.info(f"Activation du Fallback Cache SQLite pour {city.get('nom')}")
    cached = get_latest_fuel_snapshot(code_insee)
    if cached:
        return cached, cached.get("stations", [])
    
    # Aucun historique existant
    empty_metrics = compute_fuel_metrics([])
    save_fuel_snapshot(code_insee, empty_metrics, [])
    return empty_metrics, []


def refresh_all_fuel_data(active_cities: List[Dict[str, Any]], radius_km: int = 12) -> Dict[str, Any]:
    """Actualise l'ensemble des données carburant pour toutes les villes actives."""
    results = {}
    success_count = 0
    total = len(active_cities)

    logger.info(f"Début de l'actualisation des données carburant pour {total} villes...")
    for idx, city in enumerate(active_cities, start=1):
        nom = city.get("nom", "Inconnue")
        code = city.get("code_insee") or city.get("code")
        try:
            metrics, stations = fetch_fuel_for_city(city, radius_km=radius_km)
            results[code] = {
                "city": city,
                "metrics": metrics,
                "stations": stations
            }
            success_count += 1
            logger.info(f"[{idx}/{total}] {nom} : {len(stations)} stations détectées")
        except Exception as e:
            logger.error(f"[{idx}/{total}] Erreur sur {nom} : {e}")
            log_event("CITY_FETCH_FAIL", "ERROR", f"Ville: {nom} ({code}) - {e}")
        
        # Courte pause de politesse pour respecter les API gouvernementales
        time.sleep(0.15)

    log_event("FUEL_REFRESH_ALL", "SUCCESS", f"{success_count}/{total} villes mises à jour.")
    return results
