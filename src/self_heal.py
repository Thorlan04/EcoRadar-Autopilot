"""
Module self_heal.py pour EcoRadar-Autopilot.
Auto-guérison, vérification d'intégrité des fichiers générés,
purge des communes obsolètes et sélection progressive des nouvelles villes.
"""

import os
import json
import logging
from typing import Dict, Any, List, Tuple, Optional
from bs4 import BeautifulSoup

from src.database import (
    init_db, get_city_count, get_all_known_insee_codes,
    upsert_city, purge_stale_cities, cleanup_old_snapshots, log_event, get_active_cities
)
from src.fetcher import fetch_top_french_cities

logger = logging.getLogger("EcoRadar.SelfHeal")
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT_DIR, "dist")


def pre_run_heal(config: Dict[str, Any]) -> Tuple[int, List[str]]:
    """
    Exécute les vérifications initiales :
    1. Assure l'intégrité des tables SQLite.
    2. Purge les communes inactives ou sans stations répétées.
    3. Ajoute automatiquement N nouvelles villes françaises par ordre de population
       pour assurer une croissance organique (Programmatic SEO).
    """
    init_db()
    cleanup_old_snapshots(keep_history_count=5)
    
    # Purge des villes récurrentes sans stations
    purged = purge_stale_cities(threshold_runs=5)
    if purged:
        logger.warning(f"Villes sans stations désactivées : {', '.join(purged)}")
        log_event("SELF_HEAL_PURGE", "WARNING", f"Villes désactivées: {purged}")

    current_count = get_city_count()
    max_cities = config.get("max_cities", 1000)
    new_to_add = config.get("new_cities_per_run", 15)

    added_names = []

    if current_count < max_cities:
        known_codes = get_all_known_insee_codes()
        # Récupère un pool large des plus grandes communes de France
        all_candidates = fetch_top_french_cities(limit=max(300, current_count + new_to_add + 50))
        
        count_added = 0
        for candidate in all_candidates:
            if candidate["code"] not in known_codes:
                upsert_city(candidate)
                added_names.append(f"{candidate['nom']} ({candidate['code']})")
                count_added += 1
                if count_added >= new_to_add:
                    break

        if added_names:
            logger.info(f"Ajout de {len(added_names)} nouvelles communes au réseau : {', '.join(added_names[:5])}...")
            log_event("SELF_HEAL_EXPAND", "SUCCESS", f"{len(added_names)} nouvelles villes ajoutées.")
    else:
        logger.info(f"Plafond maximal de villes atteint ({current_count}/{max_cities}). Pas d'expansion ce cycle.")

    return get_city_count(), added_names


def verify_html_file(file_path: str) -> Tuple[bool, str]:
    """Vérifie l'intégrité technique d'un fichier HTML généré."""
    if not os.path.exists(file_path):
        return False, "Fichier manquant"
    
    size = os.path.getsize(file_path)
    if size < 1000:
        return False, f"Fichier anormalement petit ({size} octets)"

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        if "</html>" not in content.lower():
            return False, "Balise </html> manquante"

        # Vérification du title
        if "<title>" not in content.lower() or "</title>" not in content.lower():
            return False, "Titre HTML manquant ou vide"

        # Vérification du JSON-LD Schema.org
        if 'application/ld+json' not in content:
            return False, "Balisage Schema.org JSON-LD absent"

        return True, "OK"
    except Exception as e:
        return False, f"Erreur de lecture : {e}"


def post_run_health_check(checked_cities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """
    Vérifie la qualité de tous les artéfacts produits dans dist/ :
    index.html, ville/*.html, sitemap.xml, robots.txt, llms.txt, api/latest.json.
    """
    results = {
        "status": "PASSED",
        "errors": [],
        "checked_files": 0,
        "valid_files": 0
    }

    # 1. Vérification index.html
    index_path = os.path.join(DIST_DIR, "index.html")
    results["checked_files"] += 1
    valid, msg = verify_html_file(index_path)
    if valid:
        results["valid_files"] += 1
    else:
        results["errors"].append(f"index.html : {msg}")

    # 2. Vérification des pages villes traitées
    cities_to_check = checked_cities if checked_cities is not None else get_active_cities()
    for city in cities_to_check:
        city_path = os.path.join(DIST_DIR, "ville", f"{city['slug']}.html")
        results["checked_files"] += 1
        valid, msg = verify_html_file(city_path)
        if valid:
            results["valid_files"] += 1
        else:
            results["errors"].append(f"ville/{city['slug']}.html : {msg}")

    # 3. Vérification sitemap.xml
    sitemap_path = os.path.join(DIST_DIR, "sitemap.xml")
    results["checked_files"] += 1
    if os.path.exists(sitemap_path) and os.path.getsize(sitemap_path) > 100:
        with open(sitemap_path, "r", encoding="utf-8") as f:
            c = f.read()
            if "<urlset" in c and "</urlset>" in c:
                results["valid_files"] += 1
            else:
                results["errors"].append("sitemap.xml malformé")
    else:
        results["errors"].append("sitemap.xml manquant ou vide")

    # 4. Vérification robots.txt
    robots_path = os.path.join(DIST_DIR, "robots.txt")
    results["checked_files"] += 1
    if os.path.exists(robots_path) and os.path.getsize(robots_path) > 20:
        results["valid_files"] += 1
    else:
        results["errors"].append("robots.txt manquant")

    # 5. Vérification llms.txt
    llms_path = os.path.join(DIST_DIR, "llms.txt")
    results["checked_files"] += 1
    if os.path.exists(llms_path) and os.path.getsize(llms_path) > 50:
        results["valid_files"] += 1
    else:
        results["errors"].append("llms.txt manquant")

    # 6. Vérification latest.json
    api_path = os.path.join(DIST_DIR, "api", "latest.json")
    results["checked_files"] += 1
    if os.path.exists(api_path):
        try:
            with open(api_path, "r", encoding="utf-8") as f:
                d = json.load(f)
                if "cities" in d and "tempo" in d:
                    results["valid_files"] += 1
                else:
                    results["errors"].append("latest.json structure incomplète")
        except Exception as e:
            results["errors"].append(f"latest.json JSON invalide : {e}")
    else:
        results["errors"].append("api/latest.json manquant")

    if results["errors"]:
        results["status"] = "WARNINGS"
        log_event("HEALTH_CHECK", "WARNING", f"{len(results['errors'])} anomalies détectées : {results['errors'][:5]}")
    else:
        log_event("HEALTH_CHECK", "SUCCESS", f"{results['checked_files']} fichiers vérifiés avec succès (100% valides).")

    return results
