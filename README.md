# 🔬 Utilitaires de Spectrométrie de Masse & Spectroscopie

Collection de trois outils indépendants dédiés à l'analyse de données en spectrométrie de masse (MALDI, MS/MS) et en spectroscopie UV-Vis / fluorescence.

---

## 📦 Outils disponibles

### 1. `maldi_gui.py` — MALDI Extraction & Visualisation

Interface graphique Python (Tkinter) pour l'extraction et la visualisation de données MALDI à partir de fichiers Excel (masslists Bruker).

**Fonctionnalités :**
- Chargement de fichiers Excel multi-feuilles avec détection automatique des matrices et concentrations
- Mapping interactif des matrices (nom d'affichage, concentrations éditables, réordonnables)
- Définition de tags m/z avec support des adducts +Na (+22 Da) et +K (+38 Da)
- Extraction des signaux S/N, intensité et résolution avec tolérance m/z configurable
- Filtrage par seuil S/N minimum
- Génération de graphiques en barres groupées par matrice et concentration
- Personnalisation complète : palette de couleurs, échelle Y (log/lin), barres d'erreur, DPI export
- Export des données en CSV et Excel (données individuelles + statistiques agrégées)
- Sauvegarde de la figure en PNG, SVG, PDF ou JPEG

**Dépendances :**
```bash
pip install pandas numpy matplotlib seaborn openpyxl
```

**Lancement :**
```bash
python maldi_gui.py
```

---

### 2. `msms_calculator.html` — MS/MS Fragment Calculator

Outil web (HTML/CSS/JS autonome, sans serveur) pour le calcul théorique de fragments MS/MS et la digestion enzymatique de protéines multi-chaînes.

**Fonctionnalités :**

*Onglet MS/MS Fragmentation :*
- Jusqu'à 4 chaînes peptidiques (A, B, C, D) simultanées
- Calcul des ions b, a et y avec variants -H₂O, +H₂O, -NH₃
- Support des ponts disulfure intra- et inter-chaînes
- Modifications N-term, C-term et latérales (phosphorylation, biotine, acétylation, etc.)
- Matching avec une mass list expérimentale (tolérance Da configurable)
- Filtres interactifs (ions, chaînes, modifications, fragments liés)
- Export CSV

*Onglet Digest Only :*
- Digestion enzymatique (Trypsine, Chymotrypsine, Lys-C, Arg-C, Asp-N, Glu-C, Pepsin, Thermolysin, CNBr)
- Clivages manqués configurables
- Filtrage par masse (min/max)
- Génération de peptides liés par ponts S-S
- Matching avec mass list expérimentale
- Export CSV

**Utilisation :** ouvrir `msms_calculator.html` directement dans un navigateur web moderne.

---

### 3. `uv_vis_viewer.html` — UV-Vis / Plate Reader Viewer

Outil web (HTML/CSS/JS, utilise Plotly.js via CDN) pour la visualisation interactive de spectres UV-Vis et de données de plate reader.

**Fonctionnalités :**

*Onglet UV-Vis :*
- Import de fichiers CSV par glisser-déposer (format CCA Bruker ou CSV générique)
- Soustraction de blanc (spectre de référence)
- Lissage des spectres : Savitzky-Golay, Gaussien, Moyenne mobile
- Détection automatique des λmax
- Normalisation (0–1), décalage vertical (auto ou manuel)
- Personnalisation des couleurs et styles de ligne
- Export PNG, SVG, CSV

*Onglet Plate Reader :*
- Import de fichiers plate reader (.xls/.txt tab-séparé ou CSV avec métadonnées)
- Gestion multi-plaques avec navigation
- Soustraction de blanc par colonne
- Vues : tous les spectres, un par un, sélection
- Détection des λmax par spectre
- Export PNG, SVG, CSV, Split CSV (un fichier par composé), tableau λmax, export global

**Utilisation :** ouvrir `uv_vis_viewer.html` dans un navigateur web (connexion internet requise pour Plotly.js).

---

## 🖥️ Compatibilité

| Outil | Plateforme | Prérequis |
|---|---|---|
| `maldi_gui.py` | Windows / macOS / Linux | Python 3.8+, pip |
| `msms_calculator.html` | Tout navigateur moderne | Aucun (standalone) |
| `uv_vis_viewer.html` | Tout navigateur moderne | Connexion internet (Plotly CDN) |

---

## 📄 Licence

Ce projet est distribué sous licence MIT. Voir le fichier [LICENSE](LICENSE) pour plus de détails.
