"""
Module ai_brain.py pour EcoRadar-Autopilot.
Utilise le SDK officiel google-genai (gemini-2.5-flash) avec Rate Limiting strict
et un moteur Fallback déterministe garantissant 100% de disponibilité.
"""

import os
import json
import time
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from src.database import (
    save_city_summary, get_city_summary, get_fuel_price_trends,
    get_national_fuel_stats, log_event
)

logger = logging.getLogger("EcoRadar.AIBrain")


def fmt_price(val: Optional[float], default: str = "N/C") -> str:
    """Formate un prix en chaîne à 3 décimales de façon 100% sécurisée contre les NoneType."""
    if val is not None and isinstance(val, (int, float)) and val > 0:
        return f"{val:.3f}"
    return default


class AIBrain:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.api_key = os.environ.get("GEMINI_API_KEY")
        self.model_name = config.get("gemini", {}).get("model", "gemini-2.5-flash")
        self.delay_seconds = config.get("gemini", {}).get("request_delay_seconds", 4.0)
        self.client = None

        if self.api_key and self.api_key.strip():
            try:
                from google import genai
                self.client = genai.Client(api_key=self.api_key.strip())
                logger.info(f"Client Google GenAI initialisé avec succès (Modèle: {self.model_name})")
            except Exception as e:
                logger.warning(f"Erreur initialisation Google GenAI : {e}. Mode Fallback actif.")
                self.client = None
        else:
            logger.info("Aucune variable GEMINI_API_KEY détectée. Mode Fallback déterministe actif.")


    def generate_deterministic_fallback(
        self,
        city: Dict[str, Any],
        metrics: Dict[str, Any],
        stations: List[Dict[str, Any]],
        tempo: Dict[str, Any],
        national_stats: Dict[str, Any],
        trends: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Génère une synthèse analytique mathématique complète, précise et 100% fonctionnelle
        sans appel API externe, résistante à toute absence de données.
        """
        nom = city.get("nom", "cette ville")
        departement = city.get("departement") or "France"
        station_count = len(stations)
        
        # Carburants principaux
        gazole_avg = metrics.get("avg_gazole")
        gazole_min = metrics.get("min_gazole")
        e10_avg = metrics.get("avg_e10")
        e10_min = metrics.get("min_e10")
        sp98_avg = metrics.get("avg_sp98")
        sp98_min = metrics.get("min_sp98")
        e85_avg = metrics.get("avg_e85")

        # Recherche de la station la moins chère pour le gazole
        cheapest_gazole_station = None
        if gazole_min:
            for s in stations:
                if s.get("gazole") == gazole_min:
                    cheapest_gazole_station = s
                    break

        # Tendance locale
        gazole_trend = trends.get("gazole", {}).get("text", "Stable")
        e10_trend = trends.get("e10", {}).get("text", "Stable")

        # Analyse vs national
        nat_gazole = national_stats.get("nat_avg_gazole")
        comparaison_nat = ""
        if gazole_avg and nat_gazole and isinstance(gazole_avg, (int, float)) and isinstance(nat_gazole, (int, float)):
            diff = round(gazole_avg - nat_gazole, 3)
            if diff > 0.01:
                comparaison_nat = f"Le gazole y est actuellement supérieur de +{abs(diff):.3f} €/L à la moyenne nationale observée ({fmt_price(nat_gazole)} €/L)."
            elif diff < -0.01:
                comparaison_nat = f"Le gazole y est particulièrement avantageux, affichant -{abs(diff):.3f} €/L sous la moyenne nationale ({fmt_price(nat_gazole)} €/L)."
            else:
                comparaison_nat = f"Les tarifs du gazole y sont quasiment alignés sur la moyenne nationale ({fmt_price(nat_gazole)} €/L)."

        # Tempo EDF
        lib_today = tempo.get("lib_today", "Bleu")
        lib_tomorrow = tempo.get("lib_tomorrow", "Non communiqué")
        couleur_today = tempo.get("couleur_today", "BLEU")
        
        conseil_tempo = ""
        if couleur_today == "BLEU":
            conseil_tempo = "Aujourd'hui est un jour **Tempo Bleu** : c'est le créneau optimal pour recharger les véhicules électriques ou hybrides rechargeables à domicile à tarif très avantageux."
        elif couleur_today == "BLANC":
            conseil_tempo = "Aujourd'hui est un jour **Tempo Blanc** : tarif intermédiaire. Privilégiez impérativement la recharge de nuit pendant les Heures Creuses (22h - 6h)."
        elif couleur_today == "ROUGE":
            conseil_tempo = "Alerte **Tempo Rouge** aujourd'hui : le kWh électrique en Heures Pleines est à son tarif le plus élevé. Évitez les charges lourdes en journée."
        else:
            conseil_tempo = "L'indicateur Tempo EDF est actif : planifiez vos recharges nocturnes pour maximiser vos économies."

        # Construction Markdown
        st_info = ""
        if cheapest_gazole_station and gazole_min is not None:
            adr = cheapest_gazole_station.get("adresse", "")
            ville_st = cheapest_gazole_station.get("ville", nom)
            st_info = f"La station la plus compétitive relevée pour le Gazole est située au **{adr} ({ville_st})** avec un tarif de **{fmt_price(gazole_min)} €/L**."

        summary_md = f"""### Analyse Locale des Prix à {nom} ({departement})

Ce baromètre dynamique synthétise les relevés officiels collectés auprès de **{station_count} stations-service** réparties sur le bassin de {nom}.

- **Gazole** : Prix moyen constaté à **{fmt_price(gazole_avg)} €/L** (minimum : **{fmt_price(gazole_min)} €/L**). Tendance récente : *{gazole_trend}*.
- **SP95-E10** : Prix moyen constaté à **{fmt_price(e10_avg)} €/L** (minimum : **{fmt_price(e10_min)} €/L**). Tendance récente : *{e10_trend}*.
- **SP98** : Prix moyen affiché à **{fmt_price(sp98_avg)} €/L** (minimum : **{fmt_price(sp98_min)} €/L**).
{f"- **Superéthanol E85** : Moyenne locale à **{fmt_price(e85_avg)} €/L** pour les motorisations compatibles." if e85_avg else ""}

{comparaison_nat} {st_info}

#### ⚡ Indice Énergétique & Recharge Mobilité
{conseil_tempo}
Pour demain, la couleur prévisionnelle annoncée est **{lib_tomorrow}**.
"""

        # FAQ structurée JSON-LD Schema.org
        parts = []
        if gazole_avg:
            parts.append(f"{fmt_price(gazole_avg)} €/L pour le Gazole")
        if e10_avg:
            parts.append(f"{fmt_price(e10_avg)} €/L pour le SP95-E10")
        if sp98_avg:
            parts.append(f"{fmt_price(sp98_avg)} €/L pour le SP98")
        rep_moyennes = f"Les moyennes relevées sur le secteur de {nom} sont de {', '.join(parts)}." if parts else "Les données de prix sont actualisées en continu à chaque passage de nos robots."

        faq = [
            {
                "question": f"Où trouver le carburant le moins cher à {nom} aujourd'hui ?",
                "answer": (
                    f"Selon les derniers flux du Ministère de l'Économie, la station la plus économique pour le Gazole à {nom} "
                    f"se situe au {cheapest_gazole_station.get('adresse', 'centre-ville')} ({cheapest_gazole_station.get('ville', nom)}) "
                    f"avec un litre à {fmt_price(gazole_min)} €." if (cheapest_gazole_station and gazole_min) else f"Consultez notre tableau comparatif en direct ci-dessus répertoriant les {station_count} stations de {nom}."
                )
            },
            {
                "question": f"Quels sont les tarifs moyens des carburants à {nom} ?",
                "answer": rep_moyennes
            },
            {
                "question": f"Est-ce avantageux de recharger une voiture électrique aujourd'hui à {nom} ?",
                "answer": (
                    f"Aujourd'hui le réseau électrique national est en couleur {lib_today}. "
                    f"{'Les tarifs heures creuses sont très compétitifs, idéal pour une recharge complète.' if couleur_today == 'BLEU' else 'Il est fortement recommandé de différer la recharge entre 22h et 6h du matin.'}"
                )
            }
        ]

        takeaways = [
            f"Gazole dès {fmt_price(gazole_min)} €/L" if gazole_min else "Prix carburants en direct",
            f"SP95-E10 dès {fmt_price(e10_min)} €/L" if e10_min else "Comparatif multi-stations",
            f"Énergie EDF : Jour {lib_today}"
        ]

        return {
            "summary_markdown": summary_md,
            "faq": faq,
            "takeaways": takeaways,
            "ai_generated": False
        }

    def generate_ai_analysis(
        self,
        city: Dict[str, Any],
        metrics: Dict[str, Any],
        stations: List[Dict[str, Any]],
        tempo: Dict[str, Any],
        national_stats: Dict[str, Any],
        trends: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Génère l'analyse via Gemini 2.5 Flash si API key présente et quota dispo,
        avec repli automatique immédiat sur le fallback déterministe.
        """
        # Si aucun client IA ou quota journalier déjà épuisé, fallback immédiat sans délai
        if not self.client or getattr(self, "quota_exhausted", False):
            return self.generate_deterministic_fallback(city, metrics, stations, tempo, national_stats, trends)

        prompt = f"""Tu es un analyste expert en énergie et pouvoir d'achat pour le site EcoRadar.
Rédige un bulletin d'analyse concis, percutant et unique (pour le SEO français) pour la commune suivante :
- Ville : {city.get('nom')} (Code postal: {city.get('codesPostaux', [''])[0]}, Dpt: {city.get('departement')}, Population: {city.get('population')})
- Nombre de stations-service analysées : {len(stations)}
- Prix moyens locaux : Gazole: {metrics.get('avg_gazole')} €/L, E10: {metrics.get('avg_e10')} €/L, SP98: {metrics.get('avg_sp98')} €/L, E85: {metrics.get('avg_e85')} €/L
- Prix minimums locaux : Gazole: {metrics.get('min_gazole')} €/L, E10: {metrics.get('min_e10')} €/L
- Moyennes nationales de référence : Gazole: {national_stats.get('nat_avg_gazole', 'N/C')} €/L, E10: {national_stats.get('nat_avg_e10', 'N/C')} €/L
- Couleur EDF Tempo aujourd'hui : {tempo.get('lib_today')} (Demain: {tempo.get('lib_tomorrow')})
- Tendances récentes : Gazole {trends.get('gazole', {}).get('text')}, E10 {trends.get('e10', {}).get('text')}

Fournis impérativement ta réponse au format JSON strict avec la structure suivante :
{{
  "summary_markdown": "Texte en Markdown riche (3 à 4 paragraphes courts avec titres h3 et listes à puces) analysant les tarifs locaux, le bon moment pour faire le plein, la comparaison avec la moyenne nationale et le conseil mobilité électrique/Tempo EDF.",
  "faq": [
    {{"question": "Question locale 1 avec le nom de la ville", "answer": "Réponse précise et chiffrée"}},
    {{"question": "Question locale 2 avec le nom de la ville", "answer": "Réponse précise et chiffrée"}},
    {{"question": "Question locale 3 sur l'électricité / Tempo à {city.get('nom')}", "answer": "Réponse concrète"}}
  ],
  "takeaways": [
    "Point clé 1 court",
    "Point clé 2 court",
    "Point clé 3 court"
  ]
}}
"""
        try:
            from google.genai import types
            
            # Application du Rate Limiter (Google AI Studio Free Tier)
            time.sleep(self.delay_seconds)

            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.3,
                )
            )

            raw_text = response.text.strip()
            if raw_text.startswith("```json"):
                raw_text = raw_text[7:]
            if raw_text.startswith("```"):
                raw_text = raw_text[3:]
            if raw_text.endswith("```"):
                raw_text = raw_text[:-3]

            parsed = json.loads(raw_text.strip())
            
            if "summary_markdown" in parsed and "faq" in parsed:
                return {
                    "summary_markdown": parsed["summary_markdown"],
                    "faq": parsed.get("faq", []),
                    "takeaways": parsed.get("takeaways", []),
                    "ai_generated": True
                }
        except Exception as exc:
            err_msg = str(exc)
            if any(k in err_msg for k in ["429", "RESOURCE_EXHAUSTED", "400", "401", "403", "API_KEY", "quota"]):
                self.quota_exhausted = True
                logger.warning(f"Quota ou connectivité Gemini indisponible ({exc}). Bascule instantanée sur Fallback déterministe pour toutes les communes.")
            else:
                logger.warning(f"Appel Gemini échoué pour {city.get('nom')} ({exc}).")

        return self.generate_deterministic_fallback(city, metrics, stations, tempo, national_stats, trends)



def enrich_all_cities(active_cities: List[Dict[str, Any]], config: Dict[str, Any]) -> int:
    """Enrichit toutes les villes avec l'analyse IA ou fallback et persiste dans SQLite."""
    from src.database import (
        get_all_latest_fuel_snapshots, get_all_fuel_price_trends,
        get_tempo_state, get_national_fuel_stats, save_all_city_summaries, log_event
    )

    brain = AIBrain(config)
    tempo = get_tempo_state()
    national_stats = get_national_fuel_stats()
    all_snapshots = get_all_latest_fuel_snapshots()
    all_trends = get_all_fuel_price_trends()

    summaries_to_save = []
    total = len(active_cities)
    logger.info(f"Début de l'enrichissement IA / Déterministe pour {total} villes...")

    for idx, city in enumerate(active_cities, start=1):
        code_insee = city.get("code_insee") or city.get("code")
        nom = city.get("nom", "Inconnue")
        snapshot = all_snapshots.get(code_insee, {})
        stations = snapshot.get("stations", [])
        trends = all_trends.get(code_insee, {})

        analysis = brain.generate_ai_analysis(
            city=city,
            metrics=snapshot,
            stations=stations,
            tempo=tempo,
            national_stats=national_stats,
            trends=trends
        )

        summaries_to_save.append({
            "code_insee": code_insee,
            "summary_md": analysis["summary_markdown"],
            "faq_list": analysis["faq"],
            "takeaways": analysis["takeaways"],
            "ai_generated": analysis["ai_generated"]
        })

        if idx % 50 == 0 or idx == total or analysis["ai_generated"]:
            source_label = "Gemini AI" if analysis["ai_generated"] else "Deterministic Fallback"
            logger.info(f"[{idx}/{total}] Synthèse générée pour {nom} ({source_label})")

    # Enregistrement groupé ultra-rapide en une seule transaction
    save_all_city_summaries(summaries_to_save)
    log_event("AI_ENRICH_ALL", "SUCCESS", f"{len(summaries_to_save)}/{total} synthèses générées et enregistrées.")
    return len(summaries_to_save)
