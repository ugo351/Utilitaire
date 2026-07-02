#!/usr/bin/env python3
"""
MALDI GUI v3 – Interface graphique complète pour l'extraction et la
visualisation de données MALDI à partir de fichiers Excel (masslists).
"""

import os
import re
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, colorchooser

import pandas as pd
import numpy as np
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import seaborn as sns


# ═══════════════════════════════════════════════════════════════════════════════
#  Détection des feuilles
# ═══════════════════════════════════════════════════════════════════════════════
# Patterns ordonnés du plus spécifique au plus générique
_PAT = [
    # 1) Code collé à conc décimale : A0.1_…  AcN1.0_…
    re.compile(r"^(?P<mat>[A-Za-z][A-Za-z0-9]*)(?P<conc>[01]\.\d+)_"),
    # 2) Code_conc décimale : HCCA_0.1_…  HOCCA_10.0_…
    re.compile(r"^(?P<mat>[A-Za-z]\w*)_(?P<conc>\d+\.\d+)_"),
    # 3) Code_concInt(2 chiffres)_rep : AcNHCCE_01_1_…  (01→0.1)
    re.compile(r"^(?P<mat>[A-Za-z]\w*)_(?P<conc>\d{2})_\d+"),
    # 4) Code_0ou1_repNonZero : ClCCE_1_1_… (1→1.0), only 0/1 followed by rep ≥ 1
    re.compile(r"^(?P<mat>[A-Za-z]\w*)_(?P<conc>[01])_[1-9]"),
    # 5) Fallback : préfixe alphanumérique (sans _) (conc=None)
    re.compile(r"^(?P<mat>[A-Za-z][A-Za-z0-9]*)[-_ ]"),
]


def _parse_conc(raw: str, pat_idx: int):
    """Convertit la chaîne concentration brute en float."""
    if pat_idx in (0, 1):
        return float(raw)
    if pat_idx == 2:          # "01" → 0.1 ;  "10" → 1.0
        return float(raw[0] + "." + raw[1:])
    if pat_idx == 3:          # "1" → 1.0 ;  "0" → 0 (peu probable)
        return float(raw + ".0")
    return None


def detect_sheets(sheet_names):
    """
    Retourne (groups, unmatched).
    groups : { raw_code : { conc_float|None : [sheet, …] } }
    """
    groups, unmatched = {}, []
    for sheet in sheet_names:
        hit = False
        for idx, pat in enumerate(_PAT):
            m = pat.match(sheet)
            if m:
                raw_code = m.group("mat")
                conc = _parse_conc(m.group("conc"), idx) if "conc" in m.groupdict() else None
                groups.setdefault(raw_code, {}).setdefault(conc, []).append(sheet)
                hit = True
                break
        if not hit:
            unmatched.append(sheet)
    return groups, unmatched


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialogue : mapping matrice + concentrations éditables
# ═══════════════════════════════════════════════════════════════════════════════
class MatrixMappingDialog(tk.Toplevel):
    def __init__(self, parent, raw_groups):
        super().__init__(parent)
        self.title("Mapping des matrices et concentrations")
        self.geometry("820x500")
        self.resizable(True, True)
        self.grab_set()
        self.result = None
        self._raw = raw_groups
        self._rows = []           # list of dicts
        self._build()
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.transient(parent)
        self._center(parent)

    def _center(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self):
        ttk.Label(self, text=(
            "Matrices détectées. Éditez le nom d'affichage et les concentrations.\n"
            "Le champ Conc. est une liste séparée par des virgules (ex: 0.1, 1.0).\n"
            "Décochez pour ignorer une matrice."
        ), wraplength=780, justify=tk.LEFT).pack(padx=10, pady=(10, 5))

        # ── Container scrollable ──
        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        canvas = tk.Canvas(container, highlightthickness=0)
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        self._inner = ttk.Frame(canvas)
        self._inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # En-têtes
        for col, txt in enumerate(["Actif", "Code brut", "Conc. détectées",
                                    "N feuilles", "Nom d'affichage", "Conc. (éditable)"]):
            ttk.Label(self._inner, text=txt, font="TkDefaultFont 9 bold").grid(
                row=0, column=col, padx=4, pady=2, sticky=tk.W)

        for i, (code, conc_dict) in enumerate(sorted(self._raw.items()), start=1):
            active = tk.BooleanVar(value=True)
            ttk.Checkbutton(self._inner, variable=active).grid(row=i, column=0)
            ttk.Label(self._inner, text=code).grid(row=i, column=1, padx=4, sticky=tk.W)

            detected = sorted(c for c in conc_dict if c is not None)
            det_str = ", ".join(str(c) for c in detected) if detected else "—"
            n = sum(len(v) for v in conc_dict.values())
            ttk.Label(self._inner, text=det_str).grid(row=i, column=2, padx=4)
            ttk.Label(self._inner, text=str(n)).grid(row=i, column=3, padx=4)

            disp = self._guess(code)
            name_entry = ttk.Entry(self._inner, width=16)
            name_entry.insert(0, disp)
            name_entry.grid(row=i, column=4, padx=4)

            conc_entry = ttk.Entry(self._inner, width=16)
            conc_entry.insert(0, det_str if det_str != "—" else "")
            conc_entry.grid(row=i, column=5, padx=4)

            self._rows.append(dict(code=code, active=active,
                                   name_entry=name_entry, conc_entry=conc_entry))

        # Boutons
        bf = ttk.Frame(self)
        bf.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(bf, text="Valider", command=self._ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text="Annuler", command=self._cancel).pack(side=tk.RIGHT, padx=5)

    @staticmethod
    def _guess(code):
        up = code.upper()
        if up in ("A", "HCCA"):
            return "HCCA"
        if up in ("E", "HCCE"):
            return "HCCE"
        if up.endswith("CCE") or up.endswith("CCA"):
            return code
        return code

    def _ok(self):
        result = {}                       # { display: { conc: [sheets] } }
        conc_labels_out = {}              # { conc_float: label_str }
        for r in self._rows:
            if not r["active"].get():
                continue
            display = r["name_entry"].get().strip() or r["code"]
            raw_concs_text = r["conc_entry"].get().strip()
            old_dict = self._raw[r["code"]]

            # Construire le nouveau conc_dict en re-mappant
            if raw_concs_text:
                try:
                    new_concs = [float(x.strip()) for x in raw_concs_text.split(",")]
                except ValueError:
                    messagebox.showwarning("Erreur",
                                          f"Concentrations invalides pour {display}: '{raw_concs_text}'",
                                          parent=self)
                    return
                # Réassigner les feuilles aux nouvelles conc
                old_concs = sorted(c for c in old_dict if c is not None)
                new_dict = {}
                if len(new_concs) == len(old_concs):
                    for oc, nc in zip(old_concs, new_concs):
                        new_dict[nc] = old_dict[oc]
                elif len(new_concs) == 1:
                    # Toutes les feuilles → même concentration
                    all_sheets = [s for sl in old_dict.values() for s in sl]
                    new_dict[new_concs[0]] = all_sheets
                else:
                    # Nombre différent → garder l'ancien mapping + None → 1ère new conc
                    for oc, sheets in old_dict.items():
                        if oc is not None and oc in new_concs:
                            new_dict[oc] = sheets
                        elif oc is None and new_concs:
                            new_dict[new_concs[0]] = new_dict.get(new_concs[0], []) + sheets
                        else:
                            new_dict.setdefault(oc, []).extend(sheets)
            else:
                new_dict = old_dict

            result[display] = new_dict
        self.result = result
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  Dialogue : éditeur de tags m/z
# ═══════════════════════════════════════════════════════════════════════════════
class TagEditorDialog(tk.Toplevel):
    def __init__(self, parent, existing=None):
        super().__init__(parent)
        self.title("Récepteurs / Tags m/z")
        self.geometry("520x420")
        self.resizable(True, True)
        self.grab_set()
        self.result = None
        self._rows = []
        self._grid_row = 1
        self._build(existing or {})
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.transient(parent)
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")

    def _build(self, existing):
        ttk.Label(self, text="Masses m/z et leur nom. Cochez +Na (+22 Da) et +K (+38 Da) pour inclure les adducts.",
                  wraplength=500, justify=tk.LEFT).pack(padx=10, pady=(10, 5))

        container = ttk.Frame(self)
        container.pack(fill=tk.BOTH, expand=True, padx=10, pady=5)
        canvas = tk.Canvas(container, highlightthickness=0, height=280)
        vsb = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        self._inner = ttk.Frame(canvas)
        self._inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=self._inner, anchor=tk.NW)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        for c, (txt, w) in enumerate([("m/z", 10), ("Nom", 18), ("+Na", 4), ("+K", 4), ("", 3)]):
            ttk.Label(self._inner, text=txt, font="TkDefaultFont 9 bold", width=w).grid(
                row=0, column=c, padx=4, pady=2)

        for mz, info in existing.items():
            if isinstance(info, dict):
                self._add(mz, info.get("name", ""), info.get("na", True), info.get("k", True))
            else:
                self._add(mz, info)

        bf = ttk.Frame(self)
        bf.pack(fill=tk.X, padx=10, pady=10)
        ttk.Button(bf, text="+ Ajouter", command=self._add).pack(side=tk.LEFT, padx=5)
        ttk.Button(bf, text="Valider", command=self._ok).pack(side=tk.RIGHT, padx=5)
        ttk.Button(bf, text="Annuler", command=self._cancel).pack(side=tk.RIGHT, padx=5)

    def _add(self, mz=None, name=None, use_na=True, use_k=True):
        r = self._grid_row; self._grid_row += 1
        mv = tk.StringVar(value=str(mz) if mz is not None else "")
        nv = tk.StringVar(value=name or "")
        na_var = tk.BooleanVar(value=use_na)
        k_var  = tk.BooleanVar(value=use_k)
        e1 = ttk.Entry(self._inner, textvariable=mv, width=10); e1.grid(row=r, column=0, padx=4, pady=2)
        e2 = ttk.Entry(self._inner, textvariable=nv, width=18); e2.grid(row=r, column=1, padx=4, pady=2)
        cb_na = ttk.Checkbutton(self._inner, variable=na_var); cb_na.grid(row=r, column=2, padx=6, pady=2)
        cb_k  = ttk.Checkbutton(self._inner, variable=k_var);  cb_k.grid(row=r, column=3, padx=6, pady=2)
        d = dict(mv=mv, nv=nv, na_var=na_var, k_var=k_var, w=[e1, e2, cb_na, cb_k], dead=False)
        b = ttk.Button(self._inner, text="✕", width=3, command=lambda: self._rm(d))
        b.grid(row=r, column=4, padx=2, pady=2)
        d["w"].append(b)
        self._rows.append(d)

    def _rm(self, d):
        d["dead"] = True
        for w in d["w"]: w.destroy()

    def _ok(self):
        res = {}
        for d in self._rows:
            if d["dead"]: continue
            ms = d["mv"].get().strip()
            ns = d["nv"].get().strip()
            if not ms: continue
            try:
                mz = float(ms)
            except ValueError:
                messagebox.showwarning("Erreur", f"'{ms}' invalide.", parent=self); return
            res[mz] = {"name": ns or f"m/z {mz}", "na": d["na_var"].get(), "k": d["k_var"].get()}
        if not res:
            messagebox.showwarning("Attention", "Au moins un tag requis.", parent=self); return
        self.result = res
        self.destroy()

    def _cancel(self):
        self.result = None; self.destroy()


# ═══════════════════════════════════════════════════════════════════════════════
#  Extraction
# ═══════════════════════════════════════════════════════════════════════════════
def extraire_donnees(filepath, matrix_mapping, mz_dict, sn_threshold=0, tol=0.5):
    """
    matrix_mapping : { display_name: { conc: [sheets] } }
    mz_dict        : { mz_float: label }
    tol            : tolérance m/z autour du pic
    """
    xl = pd.ExcelFile(filepath)
    mz_list = list(mz_dict.keys())
    resultats = []

    sheet_index = {}
    for disp, cd in matrix_mapping.items():
        for conc, sheets in cd.items():
            for s in sheets:
                sheet_index[s] = (disp, conc)

    for sheet in xl.sheet_names:
        if sheet not in sheet_index:
            continue
        mat_name, conc = sheet_index[sheet]
        df = xl.parse(sheet, header=2)
        df.columns = df.columns.str.strip()
        if "m/z" not in df.columns:
            continue
        df = df[pd.to_numeric(df["m/z"], errors="coerce").notnull()].copy()
        df["m/z"] = pd.to_numeric(df["m/z"])

        for mz in mz_list:
            info = mz_dict[mz]
            use_na = info.get("na", True) if isinstance(info, dict) else True
            use_k  = info.get("k",  True) if isinstance(info, dict) else True
            offsets = [0] + ([22] if use_na else []) + ([38] if use_k else [])
            mask = pd.Series(False, index=df.index)
            for mv in [mz + o for o in offsets]:
                mask |= (df["m/z"] >= mv - tol) & (df["m/z"] <= mv + tol)
            matches = df[mask]
            sn = matches["SN"].sum() if not matches.empty else 0
            intens = matches["Intens."].sum() if not matches.empty else 0
            res = matches["Res."].mean() if not matches.empty else 0
            resultats.append(dict(Matrice=mat_name, Feuille=sheet,
                                  Concentration=conc, **{"m/z": mz},
                                  SN=sn, **{"Intens.": intens}, **{"Res.": res},
                                  Groupe=re.sub(r"_\d+$", "", sheet)))

    df_res = pd.DataFrame(resultats)
    df_ok = df_res[(df_res["SN"] > sn_threshold) &
                   (df_res["Intens."] != 0) & (df_res["Res."] != 0)].copy()

    if df_ok.empty:
        agg = pd.DataFrame(columns=["Matrice", "Concentration", "m/z",
                                     "SN_mean", "SN_std", "SN_n",
                                     "Res_mean", "Res_std", "Intens_mean", "Intens_std"])
    else:
        agg = df_ok.groupby(["Matrice", "Concentration", "m/z"]).agg(
            SN_mean=("SN", "mean"), SN_std=("SN", "std"), SN_n=("SN", "count"),
            Res_mean=("Res.", "mean"), Res_std=("Res.", "std"),
            Intens_mean=("Intens.", "mean"), Intens_std=("Intens.", "std"),
        ).reset_index()
    return df_res, agg


# ═══════════════════════════════════════════════════════════════════════════════
#  Application principale
# ═══════════════════════════════════════════════════════════════════════════════
PALETTES = ["tab10", "tab20", "Set1", "Set2", "Set3", "Paired",
            "Dark2", "Pastel1", "Pastel2", "Accent"]


class MaldiGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("MALDI Extraction & Visualisation")
        self.geometry("1500x950")
        self.minsize(1100, 700)

        self.filepath = None
        self.df_indiv = None
        self.agg = None
        self.matrix_mapping = {}
        self.mz_dict = {}
        self.fig = None
        self.canvas = None

        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        plt.close("all")
        self.destroy()

    # ══════════════════════════════════════════════════════════════════════════
    #  UI
    # ══════════════════════════════════════════════════════════════════════════
    def _build_ui(self):
        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # ── Panneau contrôle scrollable ──
        ctrl_outer = ttk.Frame(paned, width=400)
        paned.add(ctrl_outer, weight=0)

        self._ctrl_canvas = tk.Canvas(ctrl_outer, highlightthickness=0, width=390)
        csb = ttk.Scrollbar(ctrl_outer, orient=tk.VERTICAL, command=self._ctrl_canvas.yview)
        ctrl = ttk.Frame(self._ctrl_canvas)
        ctrl.bind("<Configure>",
                  lambda e: self._ctrl_canvas.configure(scrollregion=self._ctrl_canvas.bbox("all")))
        self._ctrl_canvas.create_window((0, 0), window=ctrl, anchor=tk.NW)
        self._ctrl_canvas.configure(yscrollcommand=csb.set)
        self._ctrl_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        csb.pack(side=tk.RIGHT, fill=tk.Y)
        self._ctrl_canvas.bind_all("<MouseWheel>",
                                   lambda e: self._ctrl_canvas.yview_scroll(int(-e.delta / 120), "units"))

        self.plot_frame = ttk.Frame(paned)
        paned.add(self.plot_frame, weight=1)

        # ── 1. Fichier ──
        lf = ttk.LabelFrame(ctrl, text="Fichier Excel", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=(5, 2))
        self.file_var = tk.StringVar(value="Aucun fichier sélectionné")
        ttk.Label(lf, textvariable=self.file_var, wraplength=350, foreground="gray").pack(anchor=tk.W)
        ttk.Button(lf, text="Ouvrir un fichier…", command=self._open_file).pack(fill=tk.X, pady=(3, 0))

        # ── 2. Matrices (réordonnables) ──
        lf = ttk.LabelFrame(ctrl, text="Matrices détectées (ordre = ordre du graphique)", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=2)

        mat_inner = ttk.Frame(lf)
        mat_inner.pack(fill=tk.X)

        self.mat_listbox = tk.Listbox(mat_inner, selectmode=tk.EXTENDED,
                                       height=8, activestyle="none",
                                       font="TkDefaultFont 9")
        mat_sb = ttk.Scrollbar(mat_inner, orient=tk.VERTICAL,
                               command=self.mat_listbox.yview)
        self.mat_listbox.configure(yscrollcommand=mat_sb.set)
        self.mat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        mat_sb.pack(side=tk.LEFT, fill=tk.Y)

        # Boutons ▲ ▼ à droite de la Listbox
        move_frame = ttk.Frame(mat_inner)
        move_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(4, 0))
        ttk.Button(move_frame, text="▲", width=3,
                   command=self._mat_move_up).pack(pady=(0, 2))
        ttk.Button(move_frame, text="▼", width=3,
                   command=self._mat_move_down).pack(pady=(0, 2))
        ttk.Button(move_frame, text="✓/✗", width=3,
                   command=self._mat_toggle_sel).pack(pady=(6, 2))

        # mat_active tracks active state per matrix name
        self.mat_active: dict[str, bool] = {}
        # mat_order stores display order
        self.mat_order: list[str] = []

        br = ttk.Frame(lf); br.pack(fill=tk.X, pady=(3, 0))
        ttk.Button(br, text="Tout", width=6,
                   command=self._mat_select_all).pack(side=tk.LEFT, padx=2)
        ttk.Button(br, text="Rien", width=6,
                   command=self._mat_select_none).pack(side=tk.LEFT, padx=2)
        ttk.Button(br, text="Re-mapper…", width=12,
                   command=self._remap_matrices).pack(side=tk.RIGHT, padx=2)

        # ── 3. Tags ──
        lf = ttk.LabelFrame(ctrl, text="Récepteurs / Tags (m/z)", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=2)
        self.tag_frame = ttk.Frame(lf); self.tag_frame.pack(fill=tk.X)
        self.tag_vars = {}
        self.tag_info = ttk.Label(lf, text="Aucun tag. Cliquez Éditer.", foreground="gray")
        self.tag_info.pack(anchor=tk.W)
        br = ttk.Frame(lf); br.pack(fill=tk.X, pady=(3, 0))
        ttk.Button(br, text="Éditer les tags…", command=self._edit_tags).pack(side=tk.LEFT, padx=2)
        ttk.Button(br, text="Tout", width=6,
                   command=lambda: self._toggle(self.tag_vars, True)).pack(side=tk.LEFT, padx=2)
        ttk.Button(br, text="Rien", width=6,
                   command=lambda: self._toggle(self.tag_vars, False)).pack(side=tk.LEFT, padx=2)

        # ── 4. Tolérance m/z ──
        lf = ttk.LabelFrame(ctrl, text="Tolérance m/z (± Da)", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=2)
        self.tol_var = tk.DoubleVar(value=0.5)
        r = ttk.Frame(lf); r.pack(fill=tk.X)
        ttk.Scale(r, from_=0.01, to=2.0, variable=self.tol_var, orient=tk.HORIZONTAL,
                  command=lambda _: self._tol_lbl.config(text=f"{self.tol_var.get():.2f}")
                  ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._tol_lbl = ttk.Label(r, text="0.50", width=5)
        self._tol_lbl.pack(side=tk.LEFT, padx=(5, 0))
        r2 = ttk.Frame(lf); r2.pack(fill=tk.X, pady=(3, 0))
        ttk.Label(r2, text="Valeur :").pack(side=tk.LEFT)
        ttk.Entry(r2, textvariable=self.tol_var, width=7).pack(side=tk.LEFT, padx=5)

        # ── 5. Seuil S/N ──
        lf = ttk.LabelFrame(ctrl, text="Seuil S/N minimum", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=2)
        self.sn_var = tk.DoubleVar(value=0)
        r = ttk.Frame(lf); r.pack(fill=tk.X)
        self.sn_scale = ttk.Scale(r, from_=0, to=100, variable=self.sn_var, orient=tk.HORIZONTAL,
                                  command=lambda _: self._sn_lbl.config(text=f"{self.sn_var.get():.1f}"))
        self.sn_scale.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self._sn_lbl = ttk.Label(r, text="0.0", width=6)
        self._sn_lbl.pack(side=tk.LEFT, padx=(5, 0))
        r2 = ttk.Frame(lf); r2.pack(fill=tk.X, pady=(3, 0))
        ttk.Label(r2, text="Valeur :").pack(side=tk.LEFT)
        ttk.Entry(r2, textvariable=self.sn_var, width=7).pack(side=tk.LEFT, padx=5)

        # ── 6. Concentrations ──
        lf = ttk.LabelFrame(ctrl, text="Labels concentrations", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(lf, text="Format: valeur=label, séparés par ;",
                  foreground="gray", font="TkDefaultFont 8").pack(anchor=tk.W)
        self.conc_labels_var = tk.StringVar(value="1.0=1 mg/mL ; 0.1=0.1 mg/mL")
        ttk.Entry(lf, textvariable=self.conc_labels_var).pack(fill=tk.X, pady=(2, 0))

        # ── 7. Métrique ──
        lf = ttk.LabelFrame(ctrl, text="Métrique", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=2)
        self.metric_var = tk.StringVar(value="SN")
        for t, v in [("S/N ratio", "SN"), ("Résolution", "Res"), ("Intensité", "Intens")]:
            ttk.Radiobutton(lf, text=t, value=v, variable=self.metric_var).pack(anchor=tk.W)

        # ── 8. Disposition ──
        lf = ttk.LabelFrame(ctrl, text="Disposition", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=2)
        r = ttk.Frame(lf); r.pack(fill=tk.X)
        ttk.Label(r, text="Lignes:").pack(side=tk.LEFT)
        self.rows_var = tk.IntVar(value=2)
        ttk.Spinbox(r, from_=1, to=6, textvariable=self.rows_var, width=4).pack(side=tk.LEFT, padx=(2, 10))
        ttk.Label(r, text="Col:").pack(side=tk.LEFT)
        self.cols_var = tk.IntVar(value=4)
        ttk.Spinbox(r, from_=1, to=8, textvariable=self.cols_var, width=4).pack(side=tk.LEFT, padx=2)
        self.auto_layout = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf, text="Auto", variable=self.auto_layout).pack(anchor=tk.W, pady=(3, 0))

        # ── 9. Graphique : personnalisation ──
        lf = ttk.LabelFrame(ctrl, text="Personnalisation du graphique", padding=5)
        lf.pack(fill=tk.X, padx=5, pady=2)

        # Échelle Y
        r = ttk.Frame(lf); r.pack(fill=tk.X, pady=1)
        ttk.Label(r, text="Échelle Y :").pack(side=tk.LEFT)
        self.yscale_var = tk.StringVar(value="log")
        ttk.Radiobutton(r, text="Log", value="log", variable=self.yscale_var).pack(side=tk.LEFT, padx=3)
        ttk.Radiobutton(r, text="Lin", value="linear", variable=self.yscale_var).pack(side=tk.LEFT, padx=3)

        # Bornes Y
        r = ttk.Frame(lf); r.pack(fill=tk.X, pady=1)
        ttk.Label(r, text="Y min :").pack(side=tk.LEFT)
        self.ymin_var = tk.StringVar(value="auto")
        ttk.Entry(r, textvariable=self.ymin_var, width=7).pack(side=tk.LEFT, padx=2)
        ttk.Label(r, text="Y max :").pack(side=tk.LEFT, padx=(8, 0))
        self.ymax_var = tk.StringVar(value="auto")
        ttk.Entry(r, textvariable=self.ymax_var, width=7).pack(side=tk.LEFT, padx=2)
        ttk.Label(lf, text="(tapez 'auto' pour automatique)", foreground="gray",
                  font="TkDefaultFont 8").pack(anchor=tk.W)

        # Barres d'erreur
        self.errbar_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(lf, text="Afficher les barres d'erreur (std)",
                        variable=self.errbar_var).pack(anchor=tk.W, pady=1)

        # Palette
        r = ttk.Frame(lf); r.pack(fill=tk.X, pady=1)
        ttk.Label(r, text="Palette :").pack(side=tk.LEFT)
        self.palette_var = tk.StringVar(value="tab10")
        ttk.Combobox(r, textvariable=self.palette_var, values=PALETTES,
                     state="readonly", width=12).pack(side=tk.LEFT, padx=4)

        # Largeur barres
        r = ttk.Frame(lf); r.pack(fill=tk.X, pady=1)
        ttk.Label(r, text="Largeur barre :").pack(side=tk.LEFT)
        self.barw_var = tk.DoubleVar(value=0.08)
        ttk.Entry(r, textvariable=self.barw_var, width=6).pack(side=tk.LEFT, padx=4)

        # Taille police titres
        r = ttk.Frame(lf); r.pack(fill=tk.X, pady=1)
        ttk.Label(r, text="Taille titre :").pack(side=tk.LEFT)
        self.title_fs_var = tk.IntVar(value=10)
        ttk.Spinbox(r, from_=6, to=20, textvariable=self.title_fs_var, width=4).pack(side=tk.LEFT, padx=4)

        # Taille figure
        r = ttk.Frame(lf); r.pack(fill=tk.X, pady=1)
        ttk.Label(r, text="Taille fig (w×h) :").pack(side=tk.LEFT)
        self.fig_w_var = tk.DoubleVar(value=3.5)
        ttk.Entry(r, textvariable=self.fig_w_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(r, text="×").pack(side=tk.LEFT)
        self.fig_h_var = tk.DoubleVar(value=3.5)
        ttk.Entry(r, textvariable=self.fig_h_var, width=5).pack(side=tk.LEFT, padx=2)
        ttk.Label(r, text="par subplot").pack(side=tk.LEFT, padx=4)

        # DPI export
        r = ttk.Frame(lf); r.pack(fill=tk.X, pady=1)
        ttk.Label(r, text="DPI export :").pack(side=tk.LEFT)
        self.dpi_var = tk.IntVar(value=150)
        ttk.Spinbox(r, from_=72, to=600, textvariable=self.dpi_var, width=5).pack(side=tk.LEFT, padx=4)

        # ── 10. Boutons ──
        af = ttk.Frame(ctrl)
        af.pack(fill=tk.X, padx=5, pady=(8, 2))
        self.btn_plot = ttk.Button(af, text="Générer le graphique",
                                   command=self._generate, state=tk.DISABLED)
        self.btn_plot.pack(fill=tk.X, pady=2)
        self.btn_export = ttk.Button(af, text="Exporter les données…",
                                     command=self._export, state=tk.DISABLED)
        self.btn_export.pack(fill=tk.X, pady=2)
        self.btn_save = ttk.Button(af, text="Sauvegarder la figure…",
                                   command=self._save_figure, state=tk.DISABLED)
        self.btn_save.pack(fill=tk.X, pady=2)

        # ── Status ──
        self.status_var = tk.StringVar(value="Prêt. Ouvrez un fichier Excel.")
        ttk.Label(self, textvariable=self.status_var, relief=tk.SUNKEN,
                  anchor=tk.W, padding=(5, 2)).pack(fill=tk.X, side=tk.BOTTOM)

    # ══════════════════════════════════════════════════════════════════════════
    #  Helpers
    # ══════════════════════════════════════════════════════════════════════════
    @staticmethod
    def _toggle(d, state):
        for v in d.values():
            v.set(state)

    def _parse_conc_labels(self):
        """Parse 'val=label; …' → dict."""
        out = {}
        for part in self.conc_labels_var.get().split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                try:
                    out[float(k.strip())] = v.strip()
                except ValueError:
                    pass
        return out

    def _populate_matrices(self):
        self.mat_listbox.delete(0, tk.END)
        self.mat_active.clear()
        self.mat_order = sorted(self.matrix_mapping.keys())
        for mat in self.mat_order:
            self.mat_active[mat] = True
        self._refresh_mat_listbox()

    def _mat_label(self, mat: str) -> str:
        """Build display string for a matrix entry."""
        n = sum(len(s) for s in self.matrix_mapping[mat].values())
        concs = sorted(c for c in self.matrix_mapping[mat] if c is not None)
        ct = " | ".join(str(c) for c in concs) if concs else "?"
        prefix = "✓" if self.mat_active.get(mat, True) else "✗"
        return f"{prefix}  {mat}  ({ct})  [{n}]"

    def _refresh_mat_listbox(self):
        """Redraw the listbox contents from mat_order + mat_active."""
        sel_indices = list(self.mat_listbox.curselection())
        self.mat_listbox.delete(0, tk.END)
        for mat in self.mat_order:
            self.mat_listbox.insert(tk.END, self._mat_label(mat))
            if not self.mat_active.get(mat, True):
                self.mat_listbox.itemconfig(tk.END, fg="gray")
        # Restore selection
        for i in sel_indices:
            if i < self.mat_listbox.size():
                self.mat_listbox.selection_set(i)
        self.update_idletasks()
        self._ctrl_canvas.configure(scrollregion=self._ctrl_canvas.bbox("all"))

    def _mat_move_up(self):
        sel = list(self.mat_listbox.curselection())
        if not sel or sel[0] == 0:
            return
        for i in sel:
            self.mat_order[i - 1], self.mat_order[i] = (
                self.mat_order[i], self.mat_order[i - 1])
        self._refresh_mat_listbox()
        # Move selection up
        self.mat_listbox.selection_clear(0, tk.END)
        for i in sel:
            self.mat_listbox.selection_set(i - 1)

    def _mat_move_down(self):
        sel = list(self.mat_listbox.curselection())
        if not sel or sel[-1] >= len(self.mat_order) - 1:
            return
        for i in reversed(sel):
            self.mat_order[i + 1], self.mat_order[i] = (
                self.mat_order[i], self.mat_order[i + 1])
        self._refresh_mat_listbox()
        # Move selection down
        self.mat_listbox.selection_clear(0, tk.END)
        for i in sel:
            self.mat_listbox.selection_set(i + 1)

    def _mat_toggle_sel(self):
        """Toggle active/inactive for selected items."""
        sel = list(self.mat_listbox.curselection())
        if not sel:
            return
        for i in sel:
            mat = self.mat_order[i]
            self.mat_active[mat] = not self.mat_active[mat]
        self._refresh_mat_listbox()

    def _mat_select_all(self):
        for mat in self.mat_order:
            self.mat_active[mat] = True
        self._refresh_mat_listbox()

    def _mat_select_none(self):
        for mat in self.mat_order:
            self.mat_active[mat] = False
        self._refresh_mat_listbox()

    def _populate_tags(self):
        for w in self.tag_frame.winfo_children():
            w.destroy()
        self.tag_vars.clear()
        if not self.mz_dict:
            self.tag_info.config(text="Aucun tag. Cliquez Éditer.")
            return
        self.tag_info.config(text=f"{len(self.mz_dict)} tag(s)")
        for mz, info in self.mz_dict.items():
            name = info["name"] if isinstance(info, dict) else info
            if isinstance(info, dict):
                parts = [a for a in ("+Na" if info.get("na") else "", "+K" if info.get("k") else "") if a]
                adduct_str = f" [{', '.join(parts)}]" if parts else ""
            else:
                adduct_str = ""
            v = tk.BooleanVar(value=True)
            self.tag_vars[mz] = v
            ttk.Checkbutton(self.tag_frame, text=f"{name}  ({mz} m/z){adduct_str}",
                            variable=v).pack(anchor=tk.W)
        self.update_idletasks()
        self._ctrl_canvas.configure(scrollregion=self._ctrl_canvas.bbox("all"))

    def _update_btn(self):
        ok = bool(self.filepath and self.matrix_mapping and self.mz_dict)
        self.btn_plot.config(state=tk.NORMAL if ok else tk.DISABLED)

    # ══════════════════════════════════════════════════════════════════════════
    #  Fichier / matrices / tags
    # ══════════════════════════════════════════════════════════════════════════
    def _open_file(self):
        fp = filedialog.askopenfilename(
            title="Fichier masslist Excel",
            filetypes=[("Excel", "*.xlsx *.xls"), ("Tous", "*.*")])
        if not fp:
            return
        self.filepath = fp
        self.file_var.set(os.path.basename(fp))
        self.status_var.set(f"Analyse de {os.path.basename(fp)}…")
        self.update_idletasks()

        try:
            xl = pd.ExcelFile(fp)
            raw_groups, unmatched = detect_sheets(xl.sheet_names)
        except Exception as e:
            messagebox.showerror("Erreur", str(e)); return

        if not raw_groups:
            messagebox.showwarning("Attention", "Aucune matrice détectée."); return

        dlg = MatrixMappingDialog(self, raw_groups)
        self.wait_window(dlg)
        if dlg.result is None:
            self.status_var.set("Annulé."); return

        self.matrix_mapping = dlg.result
        self._populate_matrices()

        # Auto-alimenter les labels de concentration
        all_concs = set()
        for cd in self.matrix_mapping.values():
            for c in cd:
                if c is not None:
                    all_concs.add(c)
        parts = []
        for c in sorted(all_concs, reverse=True):
            parts.append(f"{c}={c} mg/mL")
        if parts:
            self.conc_labels_var.set(" ; ".join(parts))

        n_un = f", {len(unmatched)} non reconnues" if unmatched else ""
        self.status_var.set(f"{len(self.matrix_mapping)} matrices{n_un}. Définissez les tags.")
        self._update_btn()

    def _remap_matrices(self):
        if not self.filepath:
            messagebox.showinfo("Info", "Ouvrez d'abord un fichier."); return
        try:
            xl = pd.ExcelFile(self.filepath)
            raw_groups, _ = detect_sheets(xl.sheet_names)
        except Exception as e:
            messagebox.showerror("Erreur", str(e)); return
        dlg = MatrixMappingDialog(self, raw_groups)
        self.wait_window(dlg)
        if dlg.result is not None:
            self.matrix_mapping = dlg.result
            self._populate_matrices()
            self._update_btn()

    def _edit_tags(self):
        dlg = TagEditorDialog(self, self.mz_dict)
        self.wait_window(dlg)
        if dlg.result is not None:
            self.mz_dict = dlg.result
            self._populate_tags()
            self._update_btn()

    # ══════════════════════════════════════════════════════════════════════════
    #  Génération
    # ══════════════════════════════════════════════════════════════════════════
    def _generate(self):
        sel_mat = [m for m in self.mat_order if self.mat_active.get(m, False)]
        sel_mz = {mz: self.mz_dict[mz] for mz, v in self.tag_vars.items() if v.get()}
        if not sel_mat:
            messagebox.showwarning("Attention", "Sélectionnez au moins une matrice."); return
        if not sel_mz:
            messagebox.showwarning("Attention", "Sélectionnez au moins un tag."); return

        mapping = {m: v for m, v in self.matrix_mapping.items() if m in sel_mat}
        sn = self.sn_var.get()
        tol = self.tol_var.get()
        metric = self.metric_var.get()

        self.btn_plot.config(state=tk.DISABLED)
        self.status_var.set("Extraction…")
        self.update_idletasks()

        try:
            di, ag = extraire_donnees(self.filepath, mapping, sel_mz, sn, tol)
            self.df_indiv = di
            self.agg = ag
            self._plot(ag, sel_mz, sel_mat, metric)
        except Exception as e:
            messagebox.showerror("Erreur", str(e))
            self.status_var.set("Erreur.")
        finally:
            self.btn_plot.config(state=tk.NORMAL)

    # ══════════════════════════════════════════════════════════════════════════
    #  Tracé
    # ══════════════════════════════════════════════════════════════════════════
    def _plot(self, agg, mz_dict, sel_matrices, metric):
        mz_list = list(mz_dict.keys())
        mz_names = mz_dict
        conc_labels = self._parse_conc_labels()

        # Couleurs
        pal = self.palette_var.get()
        colors = sns.color_palette(pal, n_colors=max(len(mz_list), 1))
        mz_color = {(mz_names[mz]["name"] if isinstance(mz_names[mz], dict) else mz_names[mz]): colors[i]
                    for i, mz in enumerate(mz_list)}

        # Ordre (défini par l'utilisateur via la listbox)
        matrices = list(sel_matrices)
        n_mat = len(matrices)

        # Layout
        if self.auto_layout.get():
            nc = min(4, n_mat) if n_mat else 1
            nr = max(1, -(-n_mat // nc))
        else:
            nr, nc = self.rows_var.get(), self.cols_var.get()

        # Métrique
        mmap = {"SN": ("SN_mean", "SN_std", "S/N ratio"),
                "Res": ("Res_mean", "Res_std", "Résolution"),
                "Intens": ("Intens_mean", "Intens_std", "Intensité")}
        ycol, yerrc, ylabel = mmap[metric]

        bar_w = self.barw_var.get()
        group_gap = 0.7
        show_err = self.errbar_var.get()
        title_fs = self.title_fs_var.get()
        fw = self.fig_w_var.get()
        fh = self.fig_h_var.get()

        # Y bounds
        ymin_s, ymax_s = self.ymin_var.get().strip(), self.ymax_var.get().strip()
        ymin = None if ymin_s.lower() == "auto" else float(ymin_s)
        ymax = None if ymax_s.lower() == "auto" else float(ymax_s)

        for w in self.plot_frame.winfo_children():
            w.destroy()
        if self.fig:
            plt.close(self.fig)

        fig, axes = plt.subplots(nr, nc, figsize=(fw * nc, fh * nr), squeeze=False)
        self.fig = fig

        for idx in range(nr * nc):
            ri, ci = divmod(idx, nc)
            ax = axes[ri][ci]

            if idx >= n_mat:
                ax.axis("off")
                if idx == n_mat:
                    h, ll = axes[0][0].get_legend_handles_labels()
                    bl = dict(zip(ll, h))
                    if bl:
                        ax.legend(bl.values(), bl.keys(), title="Composés",
                                  loc="upper left", fontsize=9, title_fontsize=10,
                                  frameon=True, framealpha=0.9,
                                  bbox_to_anchor=(0.05, 0.95))
                        ax.text(0.05, 0.05, "* = mesure unique (n=1)",
                                transform=ax.transAxes, fontsize=8, style="italic", va="bottom")
                continue

            mat = matrices[idx]
            sub = agg[agg["Matrice"] == mat]
            stars = []
            gcenters = []
            xlabels = []

            concs_used = sorted(sub["Concentration"].dropna().unique(), reverse=True)
            if not len(concs_used):
                concs_used = [1.0]

            for i, conc in enumerate(concs_used):
                data = sub[sub["Concentration"] == conc]
                xpos = []
                offsets = np.linspace(-(len(mz_list) - 1) / 2,
                                     (len(mz_list) - 1) / 2,
                                     len(mz_list)) * bar_w * 1.1

                for j, mz in enumerate(mz_list):
                    val = data[data["m/z"] == mz]
                    lbl = mz_names[mz]["name"] if isinstance(mz_names[mz], dict) else mz_names[mz]
                    x = i * group_gap + offsets[j]
                    xpos.append(x)

                    y = val[ycol].values[0] if not val.empty else 0
                    ye = val[yerrc].values[0] if not val.empty else 0
                    ye_zero = (ye == 0) or pd.isna(ye)

                    if not show_err or ye_zero or y == 0:
                        ax.bar(x, y, width=bar_w, color=mz_color[lbl],
                               label=lbl if i == 0 else "")
                        if ye_zero and y != 0:
                            stars.append((x, y))
                    else:
                        ax.bar(x, y, yerr=ye, width=bar_w, color=mz_color[lbl],
                               label=lbl if i == 0 else "", capsize=2, ecolor="black")

                if xpos:
                    gcenters.append(sum(xpos) / len(xpos))
                    xlabels.append(conc_labels.get(conc, f"{conc} mg/mL"))

            ax.set_xticks(gcenters or [0])
            ax.set_xticklabels(xlabels or [""], fontsize=8)
            ax.set_xlabel("Concentration", fontsize=8)
            ax.set_ylabel(ylabel, fontsize=9)
            ax.set_title(mat, fontsize=title_fs, fontweight="bold")

            if self.yscale_var.get() == "log":
                ax.set_yscale("log")
                if ymin is None:
                    ax.set_ylim(bottom=1)

            if ymin is not None:
                ax.set_ylim(bottom=ymin)
            if ymax is not None:
                ax.set_ylim(top=ymax)

            ax.yaxis.set_tick_params(labelsize=8)

            for xs, ys in stars:
                yo = ys * 1.08 if ys > 0 else 0.05
                ax.text(xs, yo, "*", ha="center", va="bottom",
                        fontsize=10, color="black", fontweight="bold")

        if n_mat >= nr * nc:
            h, ll = axes[0][0].get_legend_handles_labels()
            bl = dict(zip(ll, h))
            if bl:
                fig.legend(bl.values(), bl.keys(), title="Composés",
                           loc="upper right", fontsize=8, title_fontsize=9,
                           frameon=True, framealpha=0.9)

        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self.plot_frame)
        canvas.draw()
        tb = NavigationToolbar2Tk(canvas, self.plot_frame)
        tb.update()
        tb.pack(side=tk.TOP, fill=tk.X)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        self.canvas = canvas

        self.btn_export.config(state=tk.NORMAL)
        self.btn_save.config(state=tk.NORMAL)
        self.status_var.set(f"Graphique : {n_mat} matrices, {len(mz_dict)} tags, "
                            f"SN>{self.sn_var.get():.1f}, tol={self.tol_var.get():.2f}")

    # ══════════════════════════════════════════════════════════════════════════
    #  Export / Save
    # ══════════════════════════════════════════════════════════════════════════
    def _export(self):
        if self.agg is None:
            return
        d = filedialog.askdirectory(title="Dossier de sortie")
        if not d:
            return
        self.agg.to_csv(os.path.join(d, "stats_maldi.csv"), index=False)
        with pd.ExcelWriter(os.path.join(d, "stats_maldi.xlsx"), engine="openpyxl") as w:
            self.df_indiv.to_excel(w, index=False, sheet_name="Individuel")
            self.agg.to_excel(w, index=False, sheet_name="Stats")
        self.status_var.set(f"Export → {d}")
        messagebox.showinfo("Export", f"Fichiers exportés dans :\n{d}")

    def _save_figure(self):
        if self.fig is None:
            return
        fp = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG", "*.png"), ("SVG", "*.svg"), ("PDF", "*.pdf"), ("JPEG", "*.jpg")])
        if not fp:
            return
        self.fig.savefig(fp, dpi=self.dpi_var.get(), bbox_inches="tight")
        self.status_var.set(f"Figure → {os.path.basename(fp)}")


if __name__ == "__main__":
    app = MaldiGUI()
    app.mainloop()
