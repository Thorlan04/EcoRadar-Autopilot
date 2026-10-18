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
        sans appel API externe.
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
        if gazole_avg and nat_gazole:
            diff = round(gazole_avg - nat_gazole, 3)
            if diff > 0.01:
                comparaison_nat = f"Le gazole y est actuellement supérieur de +{abs(diff):.3f} €/L à la moyenne nationale observée ({nat_gazole:.3f} €/L)."
            elif diff < -0.01:
                comparaison_nat = f"Le gazole y est particulièrement avantageux, affichant -{abs(diff):.3f} €/L sous la moyenne nationale ({nat_gazole:.3f} €/L)."
            else:
                comparaison_nat = f"Les tarifs du gazole y sont quasiment alignés sur la moyenne nationale ({nat_gazole:.3f} €/L)."

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
        if cheapest_gazole_station:
            adr = cheapest_gazole_station.get("adresse", "")
            ville_st = cheapest_gazole_station.get("ville", nom)
            st_info = f"La station la plus compétitive relevée pour le Gazole est située au **{adr} ({ville_st})** avec un tarif de **{gazole_min:.3f} €/L**."

        summary_md = f"""### Analyse Locale des Prix à {nom} ({departement})

Ce baromètre dynamique synthétise les relevés officiels collectés auprès de **{station_count} stations-service** réparties sur le bassin de {nom}.

- **Gazole** : Prix moyen constaté à **{gazole_avg if gazole_avg else 'N/C'} €/L** (minimum : **{gazole_min if gazole_min else 'N/C'} €/L**). Tendance récente : *{gazole_trend}*.
- **SP95-E10** : Prix moyen constaté à **{e10_avg if e10_avg else 'N/C'} €/L** (minimum : **{e10_min if e10_min else 'N/C'} €/L**). Tendance récente : *{e10_trend}*.
- **SP98** : Prix moyen affiché à **{sp98_avg if sp98_avg else 'N/C'} €/L** (minimum : **{sp98_min if sp98_min else 'N/C'} €/L**).
{f"- **Superéthanol E85** : Moyenne locale à **{e85_avg:.3f} €/L** pour les motorisations compatibles." if e85_avg else ""}

{comparaison_nat} {st_info}

#### ⚡ Indice Énergétique & Recharge Mobilité
{conseil_tempo}
Pour demain, la couleur prévisionnelle annoncée est **{lib_tomorrow}**.
"""

        # FAQ structurée JSON-LD Schema.org
        faq = [
            {
                "question": f"Où trouver le carburant le moins cher à {nom} aujourd'hui ?",
                "answer": (
                    f"Selon les derniers flux du Ministère de l'Économie, la station la plus économique pour le Gazole à {nom} "
                    f"se situe au {cheapest_gazole_station.get('adresse', 'centre-ville')} ({cheapest_gazole_station.get('ville', nom)}) "
                    f"avec un litre à {gazole_min:.3f} €." if cheapest_gazole_station else f"Consultez notre tableau comparatif en direct ci-dessus répertoriant les {station_count} stations de {nom}."
                )
            },
            {
                "question": f"Quels sont les tarifs moyens des carburants à {nom} ?",
                "answer": (
                    f"Les moyennes relevées sur le secteur de {nom} sont de {gazole_avg:.3f} €/L pour le Gazole, "
                    f"{e10_avg:.3f} €/L pour le SP95-E10 et {sp98_avg:.3f} €/L pour le SP98." if (gazole_avg and e10_avg) else f"Les données de prix sont actualisées en continu à chaque passage de nos robots."
                )
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
            f"Gazole dès {gazole_min:.3f} €/L" if gazole_min else "Prix carburants en direct",
            f"SP95-E10 dès {e10_min:.3f} €/L" if e10_min else "Comparatif multi-stations",
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
            if "429" in err_msg or "RESOURCE_EXHAUSTED" in err_msg:
                self.quota_exhausted = True
                logger.warning("Quota journalier Gemini Free Tier atteint. Bascule instantanée sur Fallback déterministe pour toutes les villes.")
            else:
                logger.warning(f"Appel Gemini échoué pour {city.get('nom')} ({exc}).")

        return self.generate_deterministic_fallback(city, metrics, stations, tempo, national_stats, trends)



def enrich_all_cities(active_cities: List[Dict[str, Any]], config: Dict[str, Any]) -> int:
    """Enrichit toutes les villes avec l'analyse IA ou fallback et persiste dans SQLite."""
    from src.database import (
        get_latest_fuel_snapshot, get_tempo_state, get_fuel_price_trends,
        get_national_fuel_stats
    )

    brain = AIBrain(config)
    tempo = get_tempo_state()
    national_stats = get_national_fuel_stats()

    count = 0
    total = len(active_cities)
    logger.info(f"Début de l'enrichissement IA / Déterministe pour {total} villes...")

    for idx, city in enumerate(active_cities, start=1):
        code_insee = city.get("code_insee") or city.get("code")
        nom = city.get("nom", "Inconnue")
        snapshot = get_latest_fuel_snapshot(code_insee) or {}
        stations = snapshot.get("stations", [])
        trends = get_fuel_price_trends(code_insee)

        analysis = brain.generate_ai_analysis(
            city=city,
            metrics=snapshot,
            stations=stations,
            tempo=tempo,
            national_stats=national_stats,
            trends=trends
        )

        save_city_summary(
            code_insee=code_insee,
            summary_md=analysis["summary_markdown"],
            faq_list=analysis["faq"],
            takeaways=analysis["takeaways"],
            ai_generated=analysis["ai_generated"]
        )
        count += 1
        source_label = "Gemini AI" if analysis["ai_generated"] else "Deterministic Fallback"
        logger.info(f"[{idx}/{total}] Synthèse générée pour {nom} ({source_label})")

    log_event("AI_ENRICH_ALL", "SUCCESS", f"{count}/{total} synthèses générées et enregistrées.")
    return count
