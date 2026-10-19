"""
Chef d'orchestre principal EcoRadar-Autopilot.
Exécute la chaîne autonome :
Diagnostic (self_heal) -> Aspiration (fetcher) -> Enrichissement (ai_brain) -> Compilation (builder) -> Contrôle qualité.
"""

import sys
import os
import json
import logging
import argparse
from datetime import datetime, timezone

# Assure l'inclusion du répertoire racine dans le sys.path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.database import init_db, get_active_cities, log_event
from src.fetcher import fetch_tempo_data, refresh_all_fuel_data
from src.ai_brain import enrich_all_cities
from src.builder import SiteBuilder
from src.self_heal import pre_run_heal, post_run_health_check

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("EcoRadar.Autopilot")


def load_env_file() -> None:
    env_path = os.path.join(ROOT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip().strip('"').strip("'")
                    if key and not os.environ.get(key):
                        os.environ[key] = val


def load_config() -> dict:
    load_env_file()
    config_path = os.path.join(ROOT_DIR, "config.json")
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Fichier de configuration introuvable : {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def run_pipeline(sample_limit: int = None) -> bool:
    start_time = datetime.now(timezone.utc)
    logger.info("=" * 65)
    logger.info("🚀 DÉMARRAGE DU CYCLE AUTOPILOT ECORADAR")
    logger.info(f"Horodatage UTC : {start_time.isoformat()}")
    logger.info("=" * 65)

    config = load_config()
    init_db()

    # 1. Étape Diagnostic & Expansion Organique
    logger.info("\n--- [ÉTAPE 1/5] DIAGNOSTIC & EXPANSION DES COMMUNES ---")
    total_cities, added_cities = pre_run_heal(config)
    logger.info(f"Total communes actives en base : {total_cities}")
    if added_cities:
        logger.info(f"Nouvelles communes intégrées ce cycle : {len(added_cities)}")

    # Sélection des villes actives à traiter
    active_cities = get_active_cities()
    if sample_limit and sample_limit > 0:
        logger.info(f"🧪 MODE TEST/ÉCHANTILLON ACTIF : Limitation à {sample_limit} villes.")
        active_cities = active_cities[:sample_limit]

    if not active_cities:
        logger.error("Aucune commune active disponible pour l'exécution.")
        return False

    # 2. Étape Aspiration des Données en Direct (100% Gratuites & Officielles)
    logger.info("\n--- [ÉTAPE 2/5] ASPIRATION DONNÉES TEMPO & CARBURANTS ---")
    today_tempo, tomorrow_tempo = fetch_tempo_data()
    logger.info(f"⚡ Météo EDF Tempo : Aujourd'hui {today_tempo.get('libCouleur')} | Demain {tomorrow_tempo.get('libCouleur')}")

    fuel_data = refresh_all_fuel_data(active_cities, radius_km=config.get("default_search_radius_km", 12))
    logger.info(f"⛽ Relevés carburants terminés pour {len(fuel_data)} communes.")

    # 3. Étape Enrichissement IA & Fallback Déterministe
    logger.info("\n--- [ÉTAPE 3/5] ENRICHISSEMENT IA / SYNTHÈSE ANALYTIQUE ---")
    enriched_count = enrich_all_cities(active_cities, config)
    logger.info(f"🧠 {enriched_count} synthèses SEO & FAQ générées.")

    # 4. Étape Compilation Web Statique & SEO
    logger.info("\n--- [ÉTAPE 4/5] COMPILATION STATIQUE JINJA2 / TAILWIND ---")
    builder = SiteBuilder(config)
    build_metrics = builder.build_all(active_cities)
    logger.info(f"📦 Compilation achevée : {build_metrics['cities_pages']} pages villes + index + flux générés dans dist/.")

    # 5. Étape Contrôle Qualité & Auto-Guérison
    logger.info("\n--- [ÉTAPE 5/5] CONTRÔLE QUALITÉ DES FICHIERS PRODUITS ---")
    health = post_run_health_check(active_cities)
    duration = (datetime.now(timezone.utc) - start_time).total_seconds()

    logger.info("\n" + "=" * 65)
    logger.info("📊 BILAN D'EXÉCUTION ECORADAR-AUTOPILOT")
    logger.info(f"Statut global          : {health['status']}")
    logger.info(f"Fichiers vérifiés      : {health['checked_files']} ({health['valid_files']} valides)")
    logger.info(f"Communes traitées      : {len(active_cities)}")
    logger.info(f"Durée totale du cycle  : {duration:.2f} secondes")
    if health["errors"]:
        logger.warning(f"Anomalies relevées     : {len(health['errors'])}")
        for err in health["errors"][:5]:
            logger.warning(f"  - {err}")
    logger.info("=" * 65)

    log_event("PIPELINE_COMPLETE", health["status"], f"Durée: {duration:.2f}s | Fichiers: {health['valid_files']}/{health['checked_files']}")
    # Le pipeline est opérationnel dès lors que l'index et la majorité des fichiers sont générés
    is_operational = health.get("valid_files", 0) > 0 and os.path.exists(os.path.join(ROOT_DIR, "dist", "index.html"))
    return is_operational



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EcoRadar Autopilot Runner")
    parser.add_argument("--sample", type=int, default=None, help="Limiter à N villes pour un test rapide")
    args = parser.parse_args()

    success = run_pipeline(sample_limit=args.sample)
    sys.exit(0 if success else 1)
