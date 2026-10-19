"""
Module builder.py pour EcoRadar-Autopilot.
Compile les pages HTML, sitemap.xml, robots.txt, llms.txt et l'API JSON latest.json
dans le dossier dist/ avec Jinja2 et TailwindCSS.
"""

import os
import json
import logging
import re
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from jinja2 import Environment, FileSystemLoader

from src.database import (
    get_active_cities, get_latest_fuel_snapshot, get_all_latest_fuel_snapshots,
    get_city_summary, get_all_city_summaries,
    get_tempo_state, get_national_fuel_stats,
    get_fuel_price_trends, get_all_fuel_price_trends, log_event
)

logger = logging.getLogger("EcoRadar.Builder")

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT_DIR, "dist")
TEMPLATES_DIR = os.path.join(ROOT_DIR, "src", "templates")


def simple_markdown_to_html(md_text: str) -> str:
    """Convertit un Markdown basique en HTML propre sans dépendance lourde."""
    lines = md_text.splitlines()
    html_lines = []
    in_list = False

    for line in lines:
        line_str = line.strip()
        if not line_str:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            continue

        # Titres ### ou ####
        if line_str.startswith("#### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            title = line_str[5:].strip()
            html_lines.append(f'<h4 class="text-base font-bold text-slate-900 mt-4 mb-2">{title}</h4>')
            continue
        elif line_str.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            title = line_str[4:].strip()
            html_lines.append(f'<h3 class="text-lg font-bold text-slate-900 mt-5 mb-2">{title}</h3>')
            continue

        # Listes à puces
        if line_str.startswith("- ") or line_str.startswith("* "):
            if not in_list:
                html_lines.append('<ul class="list-disc pl-5 space-y-1 my-3 text-slate-700">')
                in_list = True
            content = line_str[2:].strip()
            # Gras
            content = re.sub(r"\*\*(.+?)\*\*", r'<strong class="text-slate-900 font-bold">\1</strong>', content)
            # Italique
            content = re.sub(r"\*(.+?)\*", r'<em>\1</em>', content)
            html_lines.append(f"<li>{content}</li>")
            continue
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False

        # Paragraphe normal avec mise en forme
        content = re.sub(r"\*\*(.+?)\*\*", r'<strong class="text-slate-900 font-bold">\1</strong>', line_str)
        content = re.sub(r"\*(.+?)\*", r'<em>\1</em>', content)
        html_lines.append(f'<p class="mb-3 text-slate-600 leading-relaxed">{content}</p>')

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


class SiteBuilder:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.base_url = config.get("base_url", "https://ecoradar-france.github.io/EcoRadar-Autopilot").rstrip("/")
        self.env = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=True)
        self.now_utc = datetime.now(timezone.utc)
        self.build_date = self.now_utc.strftime("%d/%m/%Y à %H:%M UTC")
        self.iso_date = self.now_utc.strftime("%Y-%m-%d")
        self.current_year = self.now_utc.year
        self.radius_km = config.get("default_search_radius_km", 12)

    def prepare_directories(self) -> None:
        os.makedirs(DIST_DIR, exist_ok=True)
        os.makedirs(os.path.join(DIST_DIR, "ville"), exist_ok=True)
        os.makedirs(os.path.join(DIST_DIR, "api"), exist_ok=True)

    def build_all(self, cities: Optional[List[Dict[str, Any]]] = None) -> Dict[str, int]:
        """Exécute la compilation intégrale du site statique avec données préchargées en mémoire."""
        self.prepare_directories()
        active_cities = cities if cities is not None else get_active_cities()
        tempo = get_tempo_state()
        national_stats = get_national_fuel_stats()

        logger.info(f"Chargement en cache des données et compilation de {len(active_cities)} pages villes...")
        all_snapshots = get_all_latest_fuel_snapshots()
        all_summaries = get_all_city_summaries()
        all_trends = get_all_fuel_price_trends()

        template_city = self.env.get_template("city.html")
        cities_cards = []
        city_slugs = []

        for city in active_cities:
            code_insee = city["code_insee"]
            snapshot = all_snapshots.get(code_insee, {})
            stations = snapshot.get("stations", [])
            summary = all_summaries.get(code_insee)
            trends = all_trends.get(code_insee, {})
            if not trends:
                trends = {f: {"direction": "stable", "diff": 0.0, "text": "Stable"} for f in ["gazole", "sp95", "sp98", "e10", "e85", "gplc"]}

            # Villes apparentées pour le maillage interne
            related = [c for c in active_cities if c["code_insee"] != code_insee][:8]

            summary_html = ""
            if summary and summary.get("summary_markdown"):
                summary_html = simple_markdown_to_html(summary["summary_markdown"])

            city_context = {
                "base_url": self.base_url,
                "canonical_url": f"{self.base_url}/ville/{city['slug']}.html",
                "city": city,
                "metrics": snapshot,
                "stations": stations,
                "summary": summary,
                "summary_html": summary_html,
                "trends": trends,
                "tempo": tempo,
                "national": national_stats,
                "related_cities": related,
                "radius_km": self.radius_km,
                "build_date": self.build_date,
                "current_year": self.current_year,
                "monetization": self.config.get("monetization", {})
            }

            html_content = template_city.render(city_context)

            city_file_path = os.path.join(DIST_DIR, "ville", f"{city['slug']}.html")
            with open(city_file_path, "w", encoding="utf-8") as f:
                f.write(html_content)

            cities_cards.append({
                "city": city,
                "metrics": snapshot,
                "station_count": len(stations)
            })
            city_slugs.append(city["slug"])

        # 2. Compilation de la page d'accueil (index.html)
        logger.info("Compilation de la page d'accueil index.html...")
        index_context = {
            "base_url": self.base_url,
            "canonical_url": f"{self.base_url}/index.html",
            "cities_cards": cities_cards,
            "tempo": tempo,
            "national": national_stats,
            "build_date": self.build_date,
            "current_year": self.current_year,
            "monetization": self.config.get("monetization", {})
        }
        template_index = self.env.get_template("index.html")
        index_html = template_index.render(index_context)
        with open(os.path.join(DIST_DIR, "index.html"), "w", encoding="utf-8") as f:
            f.write(index_html)

        # 3. Génération de sitemap.xml
        self.generate_sitemap(city_slugs)

        # 4. Génération de robots.txt
        self.generate_robots_txt()

        # 5. Génération de llms.txt
        self.generate_llms_txt(active_cities, tempo, national_stats, all_snapshots)

        # 6. Génération de l'API JSON latest.json
        self.generate_api_latest(active_cities, tempo, national_stats, all_snapshots, all_summaries)

        # 7. Génération de ads.txt pour AdSense
        self.generate_ads_txt()

        metrics = {
            "cities_pages": len(city_slugs),
            "total_files": len(city_slugs) + 6
        }
        log_event("BUILD_ALL", "SUCCESS", f"{metrics['cities_pages']} pages villes + index + sitemap + llms + api + ads.txt générés.")
        return metrics

    def generate_ads_txt(self) -> None:
        """Génère dist/ads.txt pour la certification Google AdSense."""
        adsense_id = self.config.get("monetization", {}).get("adsense_client_id", "")
        if adsense_id and adsense_id.startswith("ca-"):
            clean_pub = adsense_id.replace("ca-", "")
            content = f"google.com, {clean_pub}, DIRECT, f08c47fec0942fa0\n"
            with open(os.path.join(DIST_DIR, "ads.txt"), "w", encoding="utf-8") as f:
                f.write(content)


    def generate_sitemap(self, city_slugs: List[str]) -> None:
        """Génère un sitemap.xml valide aux normes Google."""
        urls = [
            f"""  <url>
    <loc>{self.base_url}/index.html</loc>
    <lastmod>{self.iso_date}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>"""
        ]

        for slug in city_slugs:
            urls.append(f"""  <url>
    <loc>{self.base_url}/ville/{slug}.html</loc>
    <lastmod>{self.iso_date}</lastmod>
    <changefreq>daily</changefreq>
    <priority>0.8</priority>
  </url>""")

        xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""

        with open(os.path.join(DIST_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
            f.write(xml_content.strip())

    def generate_robots_txt(self) -> None:
        """Génère robots.txt autorisant l'indexation et pointant vers le sitemap."""
        content = f"""User-agent: *
Allow: /

Sitemap: {self.base_url}/sitemap.xml
"""
        with open(os.path.join(DIST_DIR, "robots.txt"), "w", encoding="utf-8") as f:
            f.write(content)

    def generate_llms_txt(self, active_cities: List[Dict[str, Any]], tempo: Dict[str, Any], national: Dict[str, Any], all_snapshots: Dict[str, Dict[str, Any]]) -> None:
        """Génère dist/llms.txt pour les LLMs et passerelles de crawl IA."""
        lines = [
            f"# EcoRadar - Baromètre Carburants & Énergie France",
            f"> Source de données citoyenne ouverte, mise à jour quotidiennement sans clé API.",
            f"",
            f"- Date de mise à jour : {self.iso_date}",
            f"- URL Officielle : {self.base_url}",
            f"- Endpoint Machine-Readable : {self.base_url}/api/latest.json",
            f"",
            f"## Synthèse Énergétique Nationale",
            f"- Tempo EDF Aujourd'hui : {tempo.get('lib_today', 'Bleu')} (Couleur: {tempo.get('couleur_today', 'BLEU')})",
            f"- Tempo EDF Demain : {tempo.get('lib_tomorrow', 'Non communiqué')}",
            f"- Gazole Moyen National : {national.get('nat_avg_gazole', 'N/C')} €/L",
            f"- SP95-E10 Moyen National : {national.get('nat_avg_e10', 'N/C')} €/L",
            f"- SP98 Moyen National : {national.get('nat_avg_sp98', 'N/C')} €/L",
            f"",
            f"## Villes Couvertes ({len(active_cities)})",
        ]

        for c in active_cities:
            snap = all_snapshots.get(c["code_insee"], {})
            lines.append(
                f"- [{c['nom']} ({c['codes_postaux'][0] if c.get('codes_postaux') else c['code_insee']})]({self.base_url}/ville/{c['slug']}.html) : "
                f"Gazole {snap.get('avg_gazole', 'N/C')} €/L | E10 {snap.get('avg_e10', 'N/C')} €/L | {snap.get('station_count', 0)} stations"
            )

        with open(os.path.join(DIST_DIR, "llms.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

    def generate_api_latest(self, active_cities: List[Dict[str, Any]], tempo: Dict[str, Any], national: Dict[str, Any], all_snapshots: Dict[str, Dict[str, Any]], all_summaries: Dict[str, Dict[str, Any]]) -> None:
        """Génère dist/api/latest.json pour les intégrations JSON statiques."""
        data = {
            "meta": {
                "generated_at": self.now_utc.isoformat(),
                "service": "EcoRadar-Autopilot",
                "version": "1.0",
                "license": "Licence Ouverte v2.0 (Etalab)"
            },
            "tempo": tempo,
            "national_stats": national,
            "cities": []
        }

        for c in active_cities:
            snap = all_snapshots.get(c["code_insee"], {})
            summary = all_summaries.get(c["code_insee"])
            data["cities"].append({
                "nom": c["nom"],
                "code_insee": c["code_insee"],
                "slug": c["slug"],
                "codes_postaux": c.get("codes_postaux", []),
                "departement": c.get("departement"),
                "population": c.get("population"),
                "latitude": c.get("latitude"),
                "longitude": c.get("longitude"),
                "metrics": {
                    "avg_gazole": snap.get("avg_gazole"),
                    "min_gazole": snap.get("min_gazole"),
                    "avg_e10": snap.get("avg_e10"),
                    "min_e10": snap.get("min_e10"),
                    "avg_sp98": snap.get("avg_sp98"),
                    "min_sp98": snap.get("min_sp98"),
                    "avg_e85": snap.get("avg_e85"),
                    "min_e85": snap.get("min_e85"),
                    "station_count": snap.get("station_count", 0)
                },
                "takeaways": summary.get("takeaways", []) if summary else [],
                "page_url": f"{self.base_url}/ville/{c['slug']}.html"
            })

        with open(os.path.join(DIST_DIR, "api", "latest.json"), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
