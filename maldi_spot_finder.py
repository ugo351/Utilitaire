"""
Recherche d'échantillons sur plaques MALDI (format 384 puits : A1 à P24).

Interface graphique (Tkinter) permettant à n'importe quel utilisateur de :
  - choisir un ou plusieurs dossiers dans lesquels fouiller (ex: 1A/MALDI, 2A/MALDI...)
  - définir le(s) préfixe(s) de code manip à reconnaître (UPA, SC, ASA, ...)
La position et le nom des spots restent codés en dur (hiérarchie fixe du MALDI).
La configuration (dossiers + préfixes) est sauvegardée à côté du script pour ne pas
avoir à la ressaisir à chaque lancement.
"""

import os
import re
import json
import threading
from datetime import datetime

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "maldi_finder_config.json")
DEFAULT_CODE_PREFIXES = ["UPA"]


def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"folders": [], "code_prefixes": DEFAULT_CODE_PREFIXES}


def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def normalize_spot(raw_spot: str) -> str | None:
    """
    Normalise et valide une position de plaque MALDI (A1 à P24).
    Accepte : 'A1', 'a1', 'A01', 'p24', 'h6', etc.
    Retourne la chaîne normalisée ex: 'A1', 'H6', 'P24' ou None si invalide.
    """
    if not raw_spot:
        return None
    raw = raw_spot.strip().upper()
    # Format lettre de A à P, chiffre de 1 à 24 (avec 0 optionnel devant)
    m = re.match(r"^([A-P])0*([1-9]|1[0-9]|2[0-4])$", raw)
    if not m:
        return None
    letter = m.group(1)
    number = int(m.group(2))
    return f"{letter}{number}"


def extract_date_from_acqus_or_folder(acqus_content: str, folder_name: str, file_path: str) -> str:
    """Extrait la date d'acquisition du spectre ou à défaut du nom de dossier."""
    # 1. Tentative depuis acqus (##$AQ_DATE= <2024-11-26T15:02:08+01:00>)
    if acqus_content:
        m_aq = re.search(r"##\$AQ_DATE=\s*<([^>]+)>", acqus_content)
        if m_aq:
            raw_date = m_aq.group(1).strip()
            # Parser ISO
            m_iso = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})", raw_date)
            if m_iso:
                return f"{m_iso.group(1)} {m_iso.group(2)}"
            m_date_only = re.match(r"(\d{4}-\d{2}-\d{2})", raw_date)
            if m_date_only:
                return m_date_only.group(1)

    # 2. Tentative depuis le nom de dossier (ex: 24-11-26, 23_04_07, 2025-01-09)
    m_f = re.search(r"(\d{2,4})[-_](\d{2})[-_](\d{2})", folder_name)
    if m_f:
        y, m, d = m_f.groups()
        if len(y) == 2:
            y = f"20{y}"
        return f"{y}-{m}-{d}"

    # 3. Date de modification du fichier
    try:
        ts = os.path.getmtime(file_path)
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except Exception:
        return "Inconnue"


def build_code_regex(code_prefixes: list[str]) -> re.Pattern | None:
    """Construit une regex reconnaissant n'importe lequel des préfixes de code manip."""
    prefixes = [p.strip() for p in code_prefixes if p.strip()]
    if not prefixes:
        return None
    alternation = "|".join(re.escape(p) for p in prefixes)
    return re.compile(rf"(({alternation})\s*\d+)", re.IGNORECASE)


SPOT_DIR_PATTERN = re.compile(r"^\d+_([A-Pa-p]0*(?:[1-9]|1[0-9]|2[0-4]))$")


def scan_maldi_spot(target_spot: str, search_dirs: list[str], code_prefixes: list[str]) -> list[dict]:
    """Recherche tous les échantillons mesurés sur la position MALDI cible dans les dossiers donnés.

    Hiérarchie fixe attendue, quel que soit le dossier choisi par l'utilisateur :
    .../EXPERIENCE/ECHANTILLON/SPOT/.../acqus. Le nom de l'expérience et de
    l'échantillon sont donc déduits en remontant depuis le dossier du spot repéré,
    et non depuis le premier niveau du dossier fouillé (qui peut varier).
    """
    normalized_target = normalize_spot(target_spot)
    if not normalized_target:
        return []

    code_regex = build_code_regex(code_prefixes)
    found_entries = []
    seen_keys = set()  # Pour dédoublonner si plusieurs scans (1SRef, 2SRef) existent pour le même échantillon

    for base_dir in search_dirs:
        if not base_dir or not os.path.isdir(base_dir):
            continue

        folder_label = os.path.basename(os.path.normpath(base_dir))

        for root, dirs, files in os.walk(base_dir):
            # On inspecte les fichiers de métadonnées Bruker acqus ou acqu
            if "acqus" not in files and "acqu" not in files:
                continue

            param_file = os.path.join(root, "acqus" if "acqus" in files else "acqu")
            content = ""
            try:
                with open(param_file, "r", encoding="latin-1", errors="ignore") as f:
                    content = f.read()
            except Exception:
                pass

            spot_detected = None

            # 1. Lecture du champ ##$SPOTNO= <...> dans acqus
            m_spot = re.search(r"##\$SPOTNO=\s*<([^>]*)>", content)
            if m_spot:
                spot_detected = normalize_spot(m_spot.group(1))

            # 2. Repérage du dossier de spot dans l'arborescence (ex: 0_H6, 1_H6)
            rel_path = os.path.relpath(root, base_dir)
            parts = rel_path.split(os.sep)

            spot_idx = None
            for idx, p in enumerate(parts):
                m_dir = SPOT_DIR_PATTERN.match(p)
                if m_dir:
                    spot_idx = idx
                    if not spot_detected:
                        spot_detected = normalize_spot(m_dir.group(1))
                    break

            if spot_detected != normalized_target:
                continue

            # Le dossier de spot est précédé de l'échantillon, lui-même précédé de l'expérience
            if spot_idx is not None and spot_idx - 1 >= 0:
                sample_name = parts[spot_idx - 1]
            else:
                sample_name = parts[0] if parts and parts[0] != "." else folder_label

            if spot_idx is not None and spot_idx - 2 >= 0:
                experience_name = parts[spot_idx - 2]
            else:
                experience_name = folder_label

            code_match = code_regex.search(experience_name) if code_regex else None
            manip_code = code_match.group(1).upper().replace(" ", "") if code_match else ""
            if not manip_code and code_regex:
                code_in_rel = code_regex.search(rel_path)
                if code_in_rel:
                    manip_code = code_in_rel.group(1).upper().replace(" ", "")
            if not manip_code:
                manip_code = "—"

            acq_date = extract_date_from_acqus_or_folder(content, experience_name, param_file)

            dedup_key = (folder_label, experience_name, sample_name, normalized_target)
            if dedup_key not in seen_keys:
                seen_keys.add(dedup_key)
                found_entries.append({
                    "folder_label": folder_label,
                    "code": manip_code,
                    "exp_folder": experience_name,
                    "sample": sample_name,
                    "spot": normalized_target,
                    "date": acq_date,
                    "folder_path": root,
                })

    found_entries.sort(key=lambda x: (x["date"], x["folder_label"], x["exp_folder"]))
    return found_entries


class MaldiFinderApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Recherche d'échantillons MALDI par spot")
        self.geometry("950x600")
        self.minsize(800, 500)

        self.config_data = load_config()
        self.last_results: list[dict] = []

        self._build_ui()

    # ---------- Construction de l'interface ----------
    def _build_ui(self):
        top_frame = ttk.Frame(self, padding=10)
        top_frame.pack(fill="x")

        # Dossiers à fouiller
        folders_frame = ttk.LabelFrame(top_frame, text="Dossiers à fouiller", padding=8)
        folders_frame.pack(fill="x", pady=(0, 8))

        self.folders_listbox = tk.Listbox(folders_frame, height=4, selectmode="extended")
        self.folders_listbox.pack(side="left", fill="both", expand=True)
        for folder in self.config_data.get("folders", []):
            self.folders_listbox.insert("end", folder)

        folders_btns = ttk.Frame(folders_frame)
        folders_btns.pack(side="left", fill="y", padx=(8, 0))
        ttk.Button(folders_btns, text="Ajouter…", command=self.add_folder).pack(fill="x", pady=2)
        ttk.Button(folders_btns, text="Retirer", command=self.remove_selected_folders).pack(fill="x", pady=2)

        # Préfixes de code manip
        codes_frame = ttk.LabelFrame(top_frame, text="Préfixe(s) de code manip (séparés par des virgules)", padding=8)
        codes_frame.pack(fill="x", pady=(0, 8))

        self.codes_var = tk.StringVar(value=", ".join(self.config_data.get("code_prefixes", DEFAULT_CODE_PREFIXES)))
        ttk.Entry(codes_frame, textvariable=self.codes_var).pack(fill="x")

        # Recherche
        search_frame = ttk.LabelFrame(top_frame, text="Position du spot (A1 à P24)", padding=8)
        search_frame.pack(fill="x")

        self.spot_var = tk.StringVar()
        spot_entry = ttk.Entry(search_frame, textvariable=self.spot_var, width=10)
        spot_entry.pack(side="left")
        spot_entry.bind("<Return>", lambda e: self.run_search())

        self.search_btn = ttk.Button(search_frame, text="Rechercher", command=self.run_search)
        self.search_btn.pack(side="left", padx=8)

        self.export_btn = ttk.Button(search_frame, text="Exporter en CSV", command=self.export_csv, state="disabled")
        self.export_btn.pack(side="left")

        self.status_var = tk.StringVar(value="Prêt.")
        ttk.Label(search_frame, textvariable=self.status_var).pack(side="left", padx=12)

        # Résultats
        results_frame = ttk.LabelFrame(self, text="Résultats", padding=8)
        results_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        columns = ("dossier", "code", "date", "echantillon", "experience")
        self.tree = ttk.Treeview(results_frame, columns=columns, show="headings")
        headings = {
            "dossier": "Dossier",
            "code": "Code manip",
            "date": "Date",
            "echantillon": "Échantillon",
            "experience": "Dossier expérience",
        }
        widths = {"dossier": 100, "code": 100, "date": 140, "echantillon": 220, "experience": 260}
        for col in columns:
            self.tree.heading(col, text=headings[col])
            self.tree.column(col, width=widths[col], anchor="w")

        vsb = ttk.Scrollbar(results_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="left", fill="y")

    # ---------- Persistance de la configuration ----------
    def _persist_config(self):
        folders = list(self.folders_listbox.get(0, "end"))
        code_prefixes = [c.strip() for c in self.codes_var.get().split(",") if c.strip()]
        save_config({"folders": folders, "code_prefixes": code_prefixes})

    # ---------- Callbacks ----------
    def add_folder(self):
        folder = filedialog.askdirectory(title="Choisir un dossier à fouiller")
        if folder:
            existing = list(self.folders_listbox.get(0, "end"))
            if folder not in existing:
                self.folders_listbox.insert("end", folder)
                self._persist_config()

    def remove_selected_folders(self):
        selected = list(self.folders_listbox.curselection())
        for index in reversed(selected):
            self.folders_listbox.delete(index)
        self._persist_config()

    def run_search(self):
        raw_spot = self.spot_var.get()
        spot = normalize_spot(raw_spot)
        if not spot:
            messagebox.showerror("Position invalide", f"'{raw_spot}' n'est pas une position valide (A1 à P24).")
            return

        folders = list(self.folders_listbox.get(0, "end"))
        if not folders:
            messagebox.showwarning("Aucun dossier", "Ajoutez au moins un dossier à fouiller.")
            return

        code_prefixes = [c.strip() for c in self.codes_var.get().split(",") if c.strip()]
        self._persist_config()

        self.search_btn.config(state="disabled")
        self.export_btn.config(state="disabled")
        self.status_var.set(f"Recherche en cours pour {spot}...")
        for row in self.tree.get_children():
            self.tree.delete(row)

        thread = threading.Thread(target=self._search_worker, args=(spot, folders, code_prefixes), daemon=True)
        thread.start()

    def _search_worker(self, spot, folders, code_prefixes):
        try:
            results = scan_maldi_spot(spot, folders, code_prefixes)
        except Exception as e:
            self.after(0, lambda: self._on_search_error(e))
            return
        self.after(0, lambda: self._on_search_done(spot, results))

    def _on_search_error(self, error):
        self.search_btn.config(state="normal")
        self.status_var.set("Erreur pendant la recherche.")
        messagebox.showerror("Erreur", str(error))

    def _on_search_done(self, spot, results):
        self.last_results = results
        self.search_btn.config(state="normal")
        for r in results:
            self.tree.insert("", "end", values=(r["folder_label"], r["code"], r["date"], r["sample"], r["exp_folder"]))
        self.status_var.set(f"{len(results)} occurrence(s) trouvée(s) pour {spot}.")
        self.export_btn.config(state="normal" if results else "disabled")

    def export_csv(self):
        if not self.last_results:
            return
        default_name = f"MALDI_Spot_{self.last_results[0]['spot']}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        filepath = filedialog.asksaveasfilename(
            title="Exporter les résultats",
            defaultextension=".csv",
            initialfile=default_name,
            filetypes=[("Fichier CSV", "*.csv")],
        )
        if not filepath:
            return
        try:
            import csv
            with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f, delimiter=";")
                writer.writerow(["Position", "Dossier", "Code manip", "Dossier expérience", "Échantillon", "Date", "Chemin dossier"])
                for r in self.last_results:
                    writer.writerow([r["spot"], r["folder_label"], r["code"], r["exp_folder"], r["sample"], r["date"], r["folder_path"]])
            messagebox.showinfo("Export réussi", f"Résultats exportés dans :\n{filepath}")
        except Exception as e:
            messagebox.showerror("Erreur d'export", str(e))


def main():
    app = MaldiFinderApp()
    app.mainloop()


if __name__ == "__main__":
    main()
