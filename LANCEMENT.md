# 🚀 Lancement d'EcoRadar-Autopilot en 3 Clics

Votre site web statique auto-génératif et auto-géré est prêt à 100%.

Suivez ces 3 étapes simples sur GitHub pour activer le pilote automatique gratuit :

---

### Clic 1 : Activer GitHub Pages
1. Rendez-vous sur votre dépôt GitHub : **Settings** > **Pages** (dans le menu latéral gauche).
2. Sous **Build and deployment** > **Source**, sélectionnez :  
   👉 **GitHub Actions**.

---

### Clic 2 : (Optionnel) Ajouter la clé Gemini
Si vous souhaitez activer l'enrichissement par IA (Gemini 2.5 Flash) en complément du mode fallback déterministe automatique :
1. Sur votre dépôt : **Settings** > **Secrets and variables** > **Actions**.
2. Cliquez sur **New repository secret** :
   - **Name** : `GEMINI_API_KEY`
   - **Secret** : votre clé Google AI Studio gratuite.

*(Si vous ne renseignez pas de clé, le moteur bascule automatiquement sur le template mathématique sans aucune erreur).*

---

### Clic 3 : Déclencher le premier déploiement
1. Allez dans l'onglet **Actions** de votre dépôt GitHub.
2. Dans la colonne de gauche, cliquez sur **EcoRadar Autopilot Daily Run**.
3. Cliquez sur le bouton à droite **Run workflow** > **Run workflow**.

---

### ✅ C'est terminé !
- Votre site est automatiquement accessible à l'adresse : `https://<votre-compte>.github.io/<nom-du-repo>/`
- Le robot s'exécute automatiquement **tous les matins à 05h30 UTC** sans intervention humaine.
- À chaque cycle, il actualise les prix des carburants, relève la couleur Tempo EDF, enrichit l'analyse locale, ajoute 15 nouvelles communes françaises et déploie le site à jour.
