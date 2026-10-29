"""tkinter card preview, hosted as a Toplevel on the shared UI-thread root.

Non-blocking: it never runs its own mainloop — it is driven by the single UI
thread's event loop, so it renders reliably.  Accepts an empty candidate list
(no dictionary hit found); in that case the user can still fill the fields by
hand and add the card.

Candidates are shown as a grouped, expandable tree: one parent row per German
word form (e.g. 'das Haus' as a noun, 'sprechen' as a verb, 'das Sprechen' as
an alternative deverbal noun), with one child row per proposed en-de/pl-de
translation pair.  A source-language filter hides pairs of other languages,
and the "Show weaker matches" toggle visibly adds/removes lower-ranked groups.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from cards.builder import CardCandidate


def _split_article(full: str, current_article: str) -> tuple[str, str]:
    """Split a leading article off `full`; return (article_or_'', bare).

    Only strips when the leading token is *exactly* der/die/das followed by a
    space — a user term that merely starts with an article-like token but is
    not one (e.g. "diesel") is left untouched.
    """
    full = full.strip()
    for art in ("der", "die", "das"):
        if full.lower().startswith(art + " "):
            return art, full[len(art) + 1:].strip()
    return "", full


class PreviewWindow:
    """Editable card-preview dialog as a Toplevel (driven by the UI mainloop)."""

    def __init__(self, candidates: list[CardCandidate],
                 on_submit: Optional[Callable[[CardCandidate | None], None]] = None,
                 master: Optional[tk.Tk] = None,
                 title: str = "AnkiExt — Card Preview",
                 topmost: bool = True,
                 strong_count: int | None = None):
        self.candidates = list(candidates)
        # Number of "strong" groups shown by default; the rest are only
        # revealed when the user enables "Show weaker matches".
        self.strong_count = (strong_count if strong_count is not None
                             else len(self.candidates))
        self.show_weaker = tk.BooleanVar(value=False)
        self.lang_filter = tk.StringVar(value="all")
        self.on_submit = on_submit
        self.result: Optional[CardCandidate] = None
        self._items: dict[str, tuple[int, int | None]] = {}
        self._sel: Optional[CardCandidate] = None

        # We must reuse the shared root (or a fresh one if none provided),
        # never create a second Tk() alongside the running mainloop.
        self.master = master or tk.Tk()
        self.root = tk.Toplevel(self.master)
        self.root.title(title)
        self.root.geometry("760x620")
        self.root.minsize(620, 440)
        if topmost:
            self.root.attributes("-topmost", True)
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        self._build()
        self._populate()
        self._select_first()
        self.root.lift()
        self.root.focus_force()
        self._focus_first()

    # -- grouping -------------------------------------------------------
    def _groups(self) -> list[dict]:
        """Group candidates by (German display word, pos) in first-seen order.

        Each group: {"cand": representative, "children": [candidates],
        "weak": bool}.  The German word form (e.g. 'das Sprechen' noun vs
        'sprechen' verb) is the group; child rows are the proposed en-de /
        pl-de translation pairs.
        """
        groups: list[dict] = []
        seen: dict[tuple[str, str], int] = {}
        for c in self.candidates:
            key = ((c.word_field or c.german or "").casefold(), c.pos or "-")
            gi = seen.get(key)
            if gi is None:
                gi = len(groups)
                seen[key] = gi
                groups.append({"cand": c, "children": [],
                               "weak": gi >= self.strong_count})
            groups[gi]["children"].append(c)
        return groups

    def _visible(self) -> list[tuple[int, int, CardCandidate]]:
        """(group_index, child_index, candidate) rows currently displayed."""
        out: list[tuple[int, int, CardCandidate]] = []
        flt = self.lang_filter.get()
        for gi, g in enumerate(self._groups()):
            if g["weak"] and not self.show_weaker.get():
                continue
            kids = [(ci, c) for ci, c in enumerate(g["children"])
                    if flt == "all" or c.source_lang == flt]
            if flt != "all" and not kids:
                continue
            for ci, c in kids:
                out.append((gi, ci, c))
        return out

    def _focus_first(self) -> None:
        """Move input focus to the first editable field for immediate typing."""
        try:
            self.entries[0].focus_set()
        except (IndexError, AttributeError):
            pass

    # -- UI construction -------------------------------------------------
    def _build(self) -> None:
        self.source_var = tk.StringVar()
        self.word_var = tk.StringVar()
        self.plural_var = tk.StringVar()
        self.note_var = tk.StringVar()
        self.lang_var = tk.StringVar(value="en")
        self.entries: list[ttk.Entry] = []

        style = ttk.Style(self.root)
        style.configure("Preview.Treeview", rowheight=22)
        self.tree = ttk.Treeview(
            self.root, columns=("german", "info", "source"), show="tree headings",
            style="Preview.Treeview", selectmode="browse")
        self.tree.heading("german", text="German")
        self.tree.heading("info", text="pos / conf")
        self.tree.heading("source", text="proposed pairs (source word — lang)")
        self.tree.column("#0", width=24, stretch=False)
        self.tree.column("german", width=190, anchor="w")
        self.tree.column("info", width=110, anchor="w")
        self.tree.column("source", width=360, anchor="w")
        self.tree.tag_configure("group", font=("Segoe UI", 9, "bold"))
        self.tree.tag_configure("weak", foreground="#8a8a8a")
        self.tree.tag_configure("child", foreground="#222222")
        self.tree.bind("<<TreeviewSelect>>", self._on_select)

        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        # toolbar: language filter + weaker toggle + expand/collapse
        bar = ttk.Frame(main)
        bar.pack(fill="x", pady=(0, 6))
        ttk.Label(bar, text="Show:").pack(side="left")
        self.filter_combo = ttk.Combobox(bar, textvariable=self.lang_filter,
                                         values=["all", "en", "pl", "de"],
                                         state="readonly", width=5)
        self.filter_combo.pack(side="left", padx=(4, 12))
        self.filter_combo.bind("<<ComboboxSelected>>", lambda _e: self._populate())
        weak_total = max(0, len(self._groups()) - self.strong_count)
        if weak_total > 0:
            self.weak_check = ttk.Checkbutton(
                bar, text=f"Show weaker matches ({weak_total})",
                variable=self.show_weaker, command=self._populate)
            self.weak_check.pack(side="left", padx=(0, 12))
        self.count_label = ttk.Label(bar, text="")
        self.count_label.pack(side="left", padx=6)
        ttk.Button(bar, text="Expand all", width=10,
                   command=self._expand_all).pack(side="right", padx=2)
        ttk.Button(bar, text="Collapse", width=9,
                   command=self._collapse_all).pack(side="right", padx=2)

        # candidate tree
        tree_frame = ttk.Frame(main)
        tree_frame.pack(fill="both", expand=True, pady=(0, 8))
        scroll = ttk.Scrollbar(tree_frame, orient="vertical",
                               command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        # editable fields (a selected row fills these; user may override)
        fields = [
            ("Source (word/phrase)", self.source_var),
            ("German (article + word)", self.word_var),
            ("Plural", self.plural_var),
            ("Note / example", self.note_var),
        ]
        for label, var in fields:
            row = ttk.Frame(main)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=label, width=24, anchor="e").pack(side="left", padx=(0, 4))
            ent = ttk.Entry(row, textvariable=var)
            ent.pack(side="left", fill="x", expand=True)
            self.entries.append(ent)

        # language row + status
        info_row = ttk.Frame(main)
        info_row.pack(fill="x", pady=(2, 8))
        ttk.Label(info_row, text="Source lang:", width=24, anchor="e").pack(side="left", padx=(0, 4))
        ttk.Combobox(info_row, textvariable=self.lang_var,
                     values=["en", "pl", "de"], state="readonly", width=6).pack(side="left")
        self.pos_label = ttk.Label(info_row, text="", foreground="#444")
        self.pos_label.pack(side="left", padx=14)

        btns = ttk.Frame(main)
        btns.pack(pady=(2, 0))
        ttk.Button(btns, text="Add to Anki", command=self.submit).pack(side="left", padx=4)
        ttk.Button(btns, text="Cancel", command=self.cancel).pack(side="left", padx=4)

    # -- tree population ------------------------------------------------
    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self._items = {}
        flt = self.lang_filter.get()
        visible = self._visible()
        for gi, ci, c in visible:
            g = self._groups()[gi]
            parent_iid = f"g{gi}"
            if parent_iid not in self._items:
                self.tree.insert(
                    "", "end", iid=parent_iid, open=True,
                    text="",
                    values=(g["cand"].word_field or g["cand"].german,
                            g["cand"].pos or "-", ""),
                    tags=("group",))
                self._items[parent_iid] = (gi, None)
            conf = getattr(c, "confidence", 1.0)
            conf_s = f"{conf * 100:.0f}%" if 0 <= conf < 1.0 else ""
            method = (getattr(c, "method", "") or "")
            info = " ".join(x for x in (c.pos or "-", conf_s, method) if x)
            iid = f"g{gi}c{ci}"
            tags = ("weak",) if g["weak"] else ("child",)
            self.tree.insert(parent_iid, "end", iid=iid, text="",
                             values=("", info, f"{c.source}  ({c.source_lang})"),
                             tags=tags)
            self._items[iid] = (gi, ci)
        n = len(visible)
        langs = {c.source_lang for _, _, c in visible}
        shown = len(self.tree.get_children(""))
        self.count_label.config(
            text=f"{n} pair(s) · {shown} German form(s)"
                 + (f" · filter: {flt}" if flt != "all" else "")
                 + (f" · langs: {', '.join(sorted(langs))}" if langs and flt == "all" else ""))
        if not self.candidates:
            self.pos_label.config(text="no automated suggestion")
        if n == 0 and self.candidates:
            self.pos_label.config(text="no pair matches this filter")

    def _expand_all(self) -> None:
        for iid in self.tree.get_children(""):
            self.tree.item(iid, open=True)

    def _collapse_all(self) -> None:
        for iid in self.tree.get_children(""):
            self.tree.item(iid, open=False)

    def _on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        gi, ci = self._items.get(iid, (None, None))
        if gi is None:
            return
        g = self._groups()[gi]
        if ci is None:
            # parent row: pick its first visible child
            first = next((c for g2i, ci2, c in self._visible()
                          if g2i == gi), g["children"][0] if g["children"] else g["cand"])
            self._show_candidate(first)
        else:
            c = g["children"][ci]
            self._show_candidate(c)

    def _show_candidate(self, c: CardCandidate) -> None:
        self._sel = c
        self.source_var.set(c.source)
        self.word_var.set(c.word_field)
        self.plural_var.set(c.plural_field)
        self.note_var.set(c.note)
        self.lang_var.set(c.source_lang)
        conf = getattr(c, "confidence", 1.0)
        pct = f" · {conf * 100:.0f}%" if 0 <= conf < 1.0 else ""
        method = (getattr(c, "method", "") or "")
        self.pos_label.config(
            text="pos=" + (c.pos or "-") + pct + (f" · {method}" if method else ""))

    def _select_first(self) -> None:
        visible = self._visible()
        if not visible:
            self._sel = None
            self.source_var.set("")
            self.word_var.set("")
            self.plural_var.set("")
            self.note_var.set("")
            self.lang_var.set("en")
            if not self.candidates:
                self.pos_label.config(text="no automated suggestion")
            return
        gi, ci, c = visible[0]
        if ci is not None:
            try:
                self.tree.selection_set(f"g{gi}c{ci}")
                self.tree.see(f"g{gi}c{ci}")
            except tk.TclError:
                pass
        self._show_candidate(c)

    # -- actions -------------------------------------------------------
    def _edited_candidate(self) -> CardCandidate:
        """Rebuild a CardCandidate from whatever is in the fields (allows manual)."""
        full = self.word_var.get().strip()
        art, rest = _split_article(full, "")
        # If the user hand-typed the plural *with* an article (e.g. "die
        # Hunde"), pull the article out so plural_field doesn't produce
        # "die die Hunde" when plural_article is also set.
        plural_text = self.plural_var.get().strip()
        p_art, plural = _split_article(plural_text, "")
        base = (self._sel if self._sel is not None
                else (self.candidates[0] if self.candidates else None))
        if base is not None:
            pa = p_art or base.plural_article
        else:
            base = CardCandidate(source="", source_lang=self.lang_var.get(), german="")
            pa = p_art or "die"
        return CardCandidate(
            source=self.source_var.get().strip(),
            source_lang=self.lang_var.get(),
            german=rest or full,
            gender=base.gender,
            article=art or base.article,
            plural=plural or plural_text,
            plural_article=pa,
            pos=base.pos,
            tags=base.tags,
            note=self.note_var.get(),
        )

    def submit(self) -> None:
        c = self._edited_candidate()
        self.result = c
        self._finish()

    def cancel(self) -> None:
        self.result = None
        self._finish()

    def _finish(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass
        if self.on_submit:
            self.on_submit(self.result)
