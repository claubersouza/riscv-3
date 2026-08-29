#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

APP_DIR = Path(__file__).resolve().parent
SCRIPT_DECODER = APP_DIR / "decoder3.py"
SCRIPT_ADDI = APP_DIR / "customizar_addi.py"
SCRIPT_LW = APP_DIR / "customizar_lw.py"
SCRIPT_SW = APP_DIR / "customizar_sw.py"

HEX_RE = re.compile(r"^[0-9a-fA-F]{8}$")


def carregar_decoder():
    spec = importlib.util.spec_from_file_location("decoder3_gui", SCRIPT_DECODER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Não foi possível carregar {SCRIPT_DECODER}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GrupoCard(ttk.Frame):
    def __init__(self, master, app: "OptimizerGUI", indice: int, grupo: list[str]):
        super().__init__(master, padding=10, relief="ridge")
        self.app = app
        self.indice = indice
        self.grupo = grupo
        self.hexes = [app.decoder.extrair_hex(x) for x in grupo]
        self.hexes = [x for x in self.hexes if x]
        self.tipo = self._detectar_tipo()

        cab = ttk.Frame(self)
        cab.pack(fill="x")

        ttk.Label(
            cab,
            text=f"Grupo {indice}",
            font=("TkDefaultFont", 11, "bold"),
        ).pack(side="left")

        tipo_texto = self.tipo.upper() if self.tipo else "OUTRO"
        ttk.Label(cab, text=f"Tipo detectado: {tipo_texto}").pack(side="left", padx=14)
        ttk.Label(cab, text=f"{len(self.hexes)} instrução(ões)").pack(side="right")

        body = ttk.Frame(self)
        body.pack(fill="x", pady=(8, 6))

        texto = tk.Text(body, height=max(2, min(len(grupo), 8)), wrap="none")
        texto.pack(side="left", fill="x", expand=True)
        for linha in grupo:
            texto.insert("end", linha + "\n")
        texto.configure(state="disabled")

        scroll = ttk.Scrollbar(body, orient="vertical", command=texto.yview)
        scroll.pack(side="right", fill="y")
        texto.configure(yscrollcommand=scroll.set)

        botoes = ttk.Frame(self)
        botoes.pack(fill="x", pady=(2, 0))

        self.btn_addi = ttk.Button(
            botoes, text="Otimizar ADDI", command=lambda: self.otimizar("addi")
        )
        self.btn_addi.pack(side="left", padx=(0, 6))

        self.btn_lw = ttk.Button(
            botoes, text="Otimizar LW", command=lambda: self.otimizar("lw")
        )
        self.btn_lw.pack(side="left", padx=6)

        self.btn_sw = ttk.Button(
            botoes, text="Otimizar SW", command=lambda: self.otimizar("sw")
        )
        self.btn_sw.pack(side="left", padx=6)

        # Mantemos os três botões visíveis, como solicitado, mas apenas o
        # compatível fica habilitado. Os customizadores validam o tipo também.
        self.btn_addi.configure(state="normal" if self.tipo == "addi" else "disabled")
        self.btn_lw.configure(state="normal" if self.tipo == "lw" else "disabled")
        self.btn_sw.configure(state="normal" if self.tipo == "sw" else "disabled")

        if len(self.hexes) < 2:
            self._desabilitar_todos()
        elif len(self.hexes) % 2:
            ttk.Label(
                botoes,
                text="A última instrução ficará fora: o grupo possui quantidade ímpar.",
            ).pack(side="left", padx=12)

    def _detectar_tipo(self) -> str | None:
        if not self.grupo:
            return None
        primeira = self.grupo[0].lower()
        if "assembly: addi " in primeira:
            return "addi"
        if "assembly: lw " in primeira:
            return "lw"
        if "assembly: sw " in primeira:
            return "sw"
        return None

    def _desabilitar_todos(self):
        for b in (self.btn_addi, self.btn_lw, self.btn_sw):
            b.configure(state="disabled")

    def otimizar(self, tipo: str):
        if tipo != self.tipo:
            messagebox.showerror("Tipo incompatível", f"Este grupo é {self.tipo or 'desconhecido'}.")
            return

        # Os scripts trabalham com pares. Se houver 5 instruções, por exemplo,
        # enviamos as quatro primeiras (2 pares) e preservamos a última.
        qtd = len(self.hexes) - (len(self.hexes) % 2)
        originais = self.hexes[:qtd]
        if len(originais) < 2:
            messagebox.showwarning("Grupo pequeno", "São necessárias pelo menos duas instruções.")
            return

        self.app.executar_otimizacao(tipo, originais, self.indice)


class ScrollableFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.inner.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.window, width=e.width),
        )

        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Windows/macOS
        self.canvas.bind("<MouseWheel>", self._wheel)
        self.inner.bind("<MouseWheel>", self._wheel)

        # Linux/X11: a roda do mouse chega como Button-4 / Button-5.
        self.canvas.bind("<Button-4>", self._wheel_linux_up)
        self.canvas.bind("<Button-5>", self._wheel_linux_down)
        self.inner.bind("<Button-4>", self._wheel_linux_up)
        self.inner.bind("<Button-5>", self._wheel_linux_down)

        # Quando o cursor entra na região dos grupos, também capturamos eventos
        # vindos dos widgets filhos (Text/Frame/Label).
        self.canvas.bind("<Enter>", self._bind_wheel_global)
        self.canvas.bind("<Leave>", self._unbind_wheel_global)
        self.inner.bind("<Enter>", self._bind_wheel_global)
        self.inner.bind("<Leave>", self._unbind_wheel_global)

    def _bind_wheel_global(self, _event=None):
        self.bind_all("<MouseWheel>", self._wheel)
        self.bind_all("<Button-4>", self._wheel_linux_up)
        self.bind_all("<Button-5>", self._wheel_linux_down)

    def _unbind_wheel_global(self, _event=None):
        self.unbind_all("<MouseWheel>")
        self.unbind_all("<Button-4>")
        self.unbind_all("<Button-5>")

    def _wheel(self, event):
        delta = getattr(event, "delta", 0)
        if delta:
            # Windows normalmente usa múltiplos de 120; macOS pode usar valores menores.
            passos = -1 if delta > 0 else 1
            self.canvas.yview_scroll(passos, "units")

    def _wheel_linux_up(self, _event):
        self.canvas.yview_scroll(-1, "units")

    def _wheel_linux_down(self, _event):
        self.canvas.yview_scroll(1, "units")


class OptimizerGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Otimizador de Instruções RISC-V")
        self.geometry("1180x820")
        self.minsize(900, 650)

        self.decoder = carregar_decoder()
        self.executando = False
        self.cards = []
        self.fila_otimizacao = []
        self.modo_otimizar_todos = False
        self.total_otimizacoes_lote = 0
        self.otimizacoes_lote_concluidas = 0
        self.inicio_lote = None
        self.timer_lote_after_id = None
        self.loading_after_id = None
        self.loading_frame = 0
        self.popup_progresso = None
        self.simulando = False
        self.tempo_simulacao_antes = None
        self.tempo_simulacao_depois = None
        self.modo_simulacao_atual = None
        self.ultimo_time_simulacao = None

        self.var_base = tk.StringVar()
        self.var_destino = tk.StringVar()
        self.var_hex = tk.StringVar()
        self.var_saida = tk.StringVar()
        self.var_aplicar_base = tk.BooleanVar(value=True)
        self.var_status = tk.StringVar(value="Selecione a pasta RTL e o arquivo HEX.")
        self.var_tempo_lote = tk.StringVar(value="Tempo: 00:00:00")
        self.var_restantes_lote = tk.StringVar(value="Restam: 0 grupos")
        self.var_loading_lote = tk.StringVar(value="")

        self._montar_ui()
        self._preencher_defaults()

    def _montar_ui(self):
        topo = ttk.LabelFrame(self, text="Arquivos do projeto", padding=10)
        topo.pack(fill="x", padx=10, pady=(10, 6))
        topo.columnconfigure(1, weight=1)

        ttk.Label(topo, text="Pasta RTL base:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(topo, textvariable=self.var_base).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(topo, text="Selecionar...", command=self.selecionar_base).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(topo, text="Pasta RTL destino:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(topo, textvariable=self.var_destino).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(topo, text="Selecionar...", command=self.selecionar_destino).grid(row=1, column=2, padx=(8, 0), pady=4)

        ttk.Label(topo, text="HEX de entrada:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(topo, textvariable=self.var_hex).grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Button(topo, text="Selecionar...", command=self.selecionar_hex).grid(row=2, column=2, padx=(8, 0), pady=4)

        ttk.Label(topo, text="HEX de saída:").grid(row=3, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(topo, textvariable=self.var_saida).grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Button(topo, text="Selecionar...", command=self.selecionar_saida).grid(row=3, column=2, padx=(8, 0), pady=4)

        acoes = ttk.Frame(topo)
        acoes.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.btn_analisar = ttk.Button(
            acoes,
            text="Analisar / Recarregar grupos",
            command=self.analisar_recarregar_e_simular,
        )
        self.btn_analisar.pack(side="left")

        self.btn_otimizar_todos = ttk.Button(
            acoes,
            text="Otimizar todos os grupos",
            command=self.otimizar_todos_os_grupos,
        )
        self.btn_otimizar_todos.pack(side="left", padx=(8, 0))

        self.btn_simulacao = ttk.Button(
            acoes,
            text="Rodar simulação",
            command=self.rodar_simulacao,
        )
        self.btn_simulacao.pack(side="left", padx=(8, 0))

        ttk.Checkbutton(
            acoes,
            text="Aplicar alterações RTL de volta na pasta base",
            variable=self.var_aplicar_base,
        ).pack(side="left", padx=18)

        ttk.Label(
            acoes,
            text="Cada grupo é enviado em pares: [1,2], [3,4], ...",
        ).pack(side="right")

        meio = ttk.Panedwindow(self, orient="vertical")
        meio.pack(fill="both", expand=True, padx=10, pady=6)

        grupos_box = ttk.LabelFrame(meio, text="Grupos encontrados", padding=4)
        self.var_contagem_grupos = tk.StringVar(value="0 grupos")
        barra_grupos = ttk.Frame(grupos_box)
        barra_grupos.pack(fill="x", padx=4, pady=(0, 4))
        ttk.Label(
            barra_grupos,
            textvariable=self.var_contagem_grupos,
            font=("TkDefaultFont", 10, "bold"),
        ).pack(side="left")
        ttk.Label(
            barra_grupos,
            text="Use a barra lateral ou a roda do mouse para ver todos os grupos.",
        ).pack(side="right")

        self.scroll = ScrollableFrame(grupos_box)
        self.scroll.pack(fill="both", expand=True)
        meio.add(grupos_box, weight=4)

        log_box = ttk.LabelFrame(meio, text="Log da otimização", padding=5)
        self.log = ScrolledText(log_box, height=10, wrap="word")
        self.log.pack(fill="both", expand=True)
        meio.add(log_box, weight=1)

        status = ttk.Frame(self, padding=(10, 4, 10, 8))
        status.pack(fill="x")
        ttk.Label(status, textvariable=self.var_status).pack(side="left")
        self.progress = ttk.Progressbar(status, mode="indeterminate", length=180)
        self.progress.pack(side="right")

    def _preencher_defaults(self):
        cwd = Path.cwd()
        modules = cwd / "modules"
        modules_custom = cwd / "modules_custom"
        if modules.is_dir():
            self.var_base.set(str(modules))
        if modules_custom.is_dir():
            self.var_destino.set(str(modules_custom))
        elif modules.is_dir():
            self.var_destino.set(str(modules_custom))

        busca = modules if modules.is_dir() else cwd
        for nome in ("imem_custom.hex", "imem.hex"):
            p = busca / nome
            if p.exists():
                self.var_hex.set(str(p))
                self._atualizar_saida_automatica(p)
                break

    def selecionar_base(self):
        p = filedialog.askdirectory(title="Selecione a pasta BASE (ex.: modules)")
        if p:
            self.var_base.set(p)
            base = Path(p)
            if not self.var_destino.get().strip():
                self.var_destino.set(str(base.parent / f"{base.name}_custom"))
            if self.var_hex.get().strip():
                self._atualizar_saida_automatica(Path(self.var_hex.get()))

    def selecionar_destino(self):
        p = filedialog.askdirectory(title="Selecione a pasta DESTINO (ex.: modules_custom)")
        if p:
            self.var_destino.set(p)
            if self.var_hex.get().strip():
                self._atualizar_saida_automatica(Path(self.var_hex.get()))

    def selecionar_hex(self):
        p = filedialog.askopenfilename(
            title="Selecione o HEX",
            filetypes=[("HEX / texto", "*.hex *.txt"), ("Todos", "*.*")],
        )
        if p:
            self.var_hex.set(p)
            self._atualizar_saida_automatica(Path(p))
            self.carregar_grupos()

    def selecionar_saida(self):
        p = filedialog.asksaveasfilename(
            title="HEX de saída",
            defaultextension=".hex",
            filetypes=[("HEX", "*.hex"), ("Todos", "*.*")],
        )
        if p:
            self.var_saida.set(p)

    def _atualizar_saida_automatica(self, entrada: Path):
        destino_txt = self.var_destino.get().strip()
        if destino_txt:
            destino = Path(destino_txt).expanduser()
            self.var_saida.set(str(destino / entrada.name))
        else:
            self.var_saida.set(str(entrada.with_name(entrada.stem + "_otimizado.hex")))

    def _limpar_cards(self):
        for w in self.scroll.inner.winfo_children():
            w.destroy()

    def analisar_recarregar_e_simular(self):
        """Analisa os grupos e roda automaticamente a simulação de referência."""
        if self.executando:
            messagebox.showinfo(
                "Otimização em andamento",
                "Aguarde a otimização terminar antes de analisar.",
            )
            return

        if self.simulando:
            messagebox.showinfo(
                "Simulação em andamento",
                "Já existe uma simulação em execução.",
            )
            return

        ok = self.carregar_grupos()
        if not ok:
            return

        self.tempo_simulacao_antes = None
        self.tempo_simulacao_depois = None

        self.log.insert("end", "\n" + "#" * 80 + "\n")
        self.log.insert("end", "SIMULAÇÃO DE REFERÊNCIA (ANTES DA OTIMIZAÇÃO)\n")
        self.log.insert("end", "#" * 80 + "\n")
        self.log.see("end")

        self._iniciar_simulacao("antes")

    def carregar_grupos(self):
        if self.executando or self.simulando:
            return False
        try:
            hex_path = Path(self.var_hex.get()).expanduser().resolve()
            if not hex_path.exists():
                raise FileNotFoundError(f"Arquivo HEX não encontrado: {hex_path}")

            linhas = hex_path.read_text(encoding="utf-8", errors="replace").splitlines()
            grupos = self.decoder.agrupar_instrucoes(linhas, minimo_grupo=self.decoder.MINIMO_GRUPO)

            self._limpar_cards()
            self.cards = []
            self.var_contagem_grupos.set(f"{len(grupos)} grupo(s) encontrado(s)")
            if not grupos:
                ttk.Label(self.scroll.inner, text="Nenhum grupo consecutivo foi encontrado.", padding=20).pack(fill="x")
                self.var_status.set("Nenhum grupo encontrado.")
                return True

            compativeis = 0
            for i, grupo in enumerate(grupos, 1):
                card = GrupoCard(self.scroll.inner, self, i, grupo)
                card.pack(fill="x", expand=True, padx=5, pady=5)
                self.cards.append(card)
                if card.tipo in {"addi", "lw", "sw"}:
                    compativeis += 1

            self.scroll.canvas.update_idletasks()
            self.scroll.canvas.configure(scrollregion=self.scroll.canvas.bbox("all"))
            self.scroll.canvas.yview_moveto(0.0)
            self.var_status.set(f"{len(grupos)} grupo(s) encontrado(s); {compativeis} compatível(is) com ADDI/LW/SW.")
            return True
        except Exception as exc:
            messagebox.showerror("Erro ao analisar", str(exc))
            self.var_status.set("Erro durante a análise.")
            return False

    def _abrir_popup_progresso(self):
        if self.popup_progresso is not None and self.popup_progresso.winfo_exists():
            self.popup_progresso.lift()
            return

        pop = tk.Toplevel(self)
        self.popup_progresso = pop
        pop.title("Otimização em andamento")
        pop.geometry("470x270")
        pop.resizable(False, False)
        pop.transient(self)
        pop.protocol("WM_DELETE_WINDOW", lambda: None)

        # Centraliza sobre a janela principal.
        self.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - 470) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - 270) // 2)
        pop.geometry(f"+{x}+{y}")

        frame = ttk.Frame(pop, padding=20)
        frame.pack(fill="both", expand=True)

        self.lbl_popup_loading = ttk.Label(
            frame,
            textvariable=self.var_loading_lote,
            font=("TkDefaultFont", 16, "bold"),
            anchor="center",
        )
        self.lbl_popup_loading.pack(fill="x", pady=(0, 12))

        self.var_popup_grupo = tk.StringVar(value="Preparando...")
        ttk.Label(
            frame,
            textvariable=self.var_popup_grupo,
            font=("TkDefaultFont", 11, "bold"),
            anchor="center",
        ).pack(fill="x", pady=(0, 10))

        info = ttk.Frame(frame)
        info.pack(fill="x", pady=8)
        info.columnconfigure(0, weight=1)
        info.columnconfigure(1, weight=1)

        ttk.Label(
            info,
            textvariable=self.var_tempo_lote,
            font=("TkDefaultFont", 11),
            anchor="center",
        ).grid(row=0, column=0, sticky="ew", padx=5)

        ttk.Label(
            info,
            textvariable=self.var_restantes_lote,
            font=("TkDefaultFont", 11),
            anchor="center",
        ).grid(row=0, column=1, sticky="ew", padx=5)

        self.var_popup_concluidos = tk.StringVar(value="Concluídos: 0")
        ttk.Label(
            frame,
            textvariable=self.var_popup_concluidos,
            anchor="center",
        ).pack(fill="x", pady=(6, 10))

        self.popup_progress = ttk.Progressbar(
            frame,
            mode="determinate",
            maximum=max(1, self.total_otimizacoes_lote),
            value=0,
        )
        self.popup_progress.pack(fill="x", pady=(4, 0))

        pop.grab_set()
        pop.lift()

    def _atualizar_popup_progresso(self, tipo=None, grupo_indice=None):
        if self.popup_progresso is None or not self.popup_progresso.winfo_exists():
            return

        concluidos = self.otimizacoes_lote_concluidas
        total = self.total_otimizacoes_lote
        restantes = max(0, total - concluidos)

        self.var_popup_concluidos.set(
            f"Concluídos: {concluidos}/{total}"
        )

        if hasattr(self, "popup_progress"):
            self.popup_progress.configure(maximum=max(1, total))
            self.popup_progress["value"] = concluidos

        if tipo is not None and grupo_indice is not None:
            atual = min(total, concluidos + 1)
            self.var_popup_grupo.set(
                f"Grupo atual: {grupo_indice} ({tipo.upper()})  •  "
                f"{atual}/{total}"
            )
        elif restantes == 0 and total > 0:
            self.var_popup_grupo.set("Todos os grupos foram processados.")

    def _finalizar_popup_progresso(self, sucesso=True):
        if self.popup_progresso is None or not self.popup_progresso.winfo_exists():
            return

        pop = self.popup_progresso

        if sucesso:
            self.var_loading_lote.set("✓ Concluído")
            self.var_popup_grupo.set("Todos os grupos foram processados.")
            self.var_restantes_lote.set("Restam: 0 grupos")
            self.var_popup_concluidos.set(
                f"Concluídos: {self.otimizacoes_lote_concluidas}/"
                f"{self.total_otimizacoes_lote}"
            )
            if hasattr(self, "popup_progress"):
                self.popup_progress["value"] = self.total_otimizacoes_lote
        else:
            self.var_loading_lote.set("Falha na otimização")

        # Libera o modal e oferece botão para fechar.
        try:
            pop.grab_release()
        except Exception:
            pass

        if not hasattr(self, "btn_fechar_popup") or not self.btn_fechar_popup.winfo_exists():
            self.btn_fechar_popup = ttk.Button(
                pop,
                text="Fechar",
                command=self._fechar_popup_progresso,
            )
            self.btn_fechar_popup.pack(pady=(0, 14))

    def _fechar_popup_progresso(self):
        if self.popup_progresso is not None:
            try:
                self.popup_progresso.grab_release()
            except Exception:
                pass
            try:
                self.popup_progresso.destroy()
            except Exception:
                pass
        self.popup_progresso = None

    def _formatar_tempo(self, segundos: float) -> str:
        total = max(0, int(segundos))
        horas, resto = divmod(total, 3600)
        minutos, segundos = divmod(resto, 60)
        return f"{horas:02d}:{minutos:02d}:{segundos:02d}"

    def _iniciar_indicadores_lote(self):
        self.inicio_lote = time.monotonic()
        self.loading_frame = 0
        self.var_tempo_lote.set("Tempo: 00:00:00")
        self._atualizar_restantes_lote()
        self._abrir_popup_progresso()
        self._atualizar_popup_progresso()
        self._atualizar_timer_lote()
        self._animar_loading_lote()

    def _parar_indicadores_lote(self, manter_tempo: bool = True):
        if self.timer_lote_after_id is not None:
            try:
                self.after_cancel(self.timer_lote_after_id)
            except Exception:
                pass
            self.timer_lote_after_id = None

        if self.loading_after_id is not None:
            try:
                self.after_cancel(self.loading_after_id)
            except Exception:
                pass
            self.loading_after_id = None

        if manter_tempo and self.inicio_lote is not None:
            decorrido = time.monotonic() - self.inicio_lote
            self.var_tempo_lote.set(
                f"Tempo total: {self._formatar_tempo(decorrido)}"
            )

        if not self.modo_otimizar_todos:
            pass
        self.inicio_lote = None

    def _atualizar_timer_lote(self):
        if not self.modo_otimizar_todos or self.inicio_lote is None:
            self.timer_lote_after_id = None
            return

        decorrido = time.monotonic() - self.inicio_lote
        self.var_tempo_lote.set(
            f"Tempo: {self._formatar_tempo(decorrido)}"
        )
        self._atualizar_popup_progresso()
        self.timer_lote_after_id = self.after(
            250,
            self._atualizar_timer_lote,
        )

    def _animar_loading_lote(self):
        if not self.modo_otimizar_todos:
            self.var_loading_lote.set("")
            self.loading_after_id = None
            return

        frames = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
        self.var_loading_lote.set(
            f"{frames[self.loading_frame % len(frames)]} Processando"
        )
        self.loading_frame += 1
        self.loading_after_id = self.after(
            100,
            self._animar_loading_lote,
        )

    def _atualizar_restantes_lote(self):
        restantes = max(
            0,
            self.total_otimizacoes_lote - self.otimizacoes_lote_concluidas,
        )

        if self.total_otimizacoes_lote > 0:
            self.var_restantes_lote.set(
                f"Restam: {restantes}/{self.total_otimizacoes_lote} grupos"
            )
        else:
            self.var_restantes_lote.set("Restam: 0 grupos")

        self._atualizar_popup_progresso()

    def otimizar_todos_os_grupos(self):
        """Otimiza todos os grupos compatíveis em sequência."""
        if self.simulando:
            messagebox.showinfo(
                "Simulação em andamento",
                "Aguarde a simulação terminar antes de otimizar os grupos.",
            )
            return

        if self.executando:
            messagebox.showinfo("Em execução", "Já existe uma otimização em andamento.")
            return

        if not self.cards:
            self.carregar_grupos()
            if not self.cards:
                return

        fila = []
        for card in self.cards:
            if card.tipo not in {"addi", "lw", "sw"}:
                continue

            qtd = len(card.hexes) - (len(card.hexes) % 2)
            originais = card.hexes[:qtd]
            if len(originais) < 2:
                continue

            fila.append((card.tipo, list(originais), card.indice))

        if not fila:
            messagebox.showwarning(
                "Nenhum grupo",
                "Não há grupos ADDI/LW/SW com pelo menos um par para otimizar.",
            )
            return

        try:
            self._validar_config()
        except Exception as exc:
            messagebox.showerror("Configuração inválida", str(exc))
            return

        scripts = {"addi": SCRIPT_ADDI, "lw": SCRIPT_LW, "sw": SCRIPT_SW}
        ausentes = [
            str(scripts[tipo])
            for tipo in {tipo for tipo, _originais, _indice in fila}
            if not scripts[tipo].exists()
        ]
        if ausentes:
            messagebox.showerror(
                "Script ausente",
                "Os seguintes customizadores não foram encontrados:\n\n"
                + "\n".join(ausentes),
            )
            return

        self.fila_otimizacao = fila
        self.modo_otimizar_todos = True
        self.total_otimizacoes_lote = len(fila)
        self.otimizacoes_lote_concluidas = 0
        self._iniciar_indicadores_lote()

        self.log.insert("end", "\n" + "#" * 80 + "\n")
        self.log.insert(
            "end",
            f"OTIMIZAÇÃO EM LOTE: {len(fila)} grupo(s) serão processados em sequência.\n",
        )
        self.log.insert(
            "end",
            "A saída de cada otimização será usada como entrada da próxima.\n",
        )
        self.log.insert("end", "#" * 80 + "\n")
        self.log.see("end")

        self.btn_otimizar_todos.configure(state="disabled")
        self._executar_proximo_grupo_lote()

    def _executar_proximo_grupo_lote(self):
        if not self.modo_otimizar_todos:
            return

        if not self.fila_otimizacao:
            self.modo_otimizar_todos = False
            self.executando = False
            self.progress.stop()
            self.btn_analisar.configure(state="normal")
            self.btn_otimizar_todos.configure(state="normal")
            self.btn_simulacao.configure(state="normal")

            total = self.otimizacoes_lote_concluidas
            self._atualizar_restantes_lote()
            self._parar_indicadores_lote(manter_tempo=True)
            self._finalizar_popup_progresso(sucesso=True)
            self.var_status.set(
                f"Otimização em lote concluída: {total} grupo(s) processado(s)."
            )
            self.carregar_grupos()

            messagebox.showinfo(
                "Otimização concluída",
                f"Todos os grupos compatíveis foram processados.\n\n"
                f"Total otimizado: {total} grupo(s).",
            )
            return

        tipo, originais, grupo_indice = self.fila_otimizacao.pop(0)
        atual = self.otimizacoes_lote_concluidas + 1

        self._atualizar_restantes_lote()
        self._atualizar_popup_progresso(tipo, grupo_indice)
        self.var_status.set(
            f"Otimização em lote {atual}/{self.total_otimizacoes_lote}: "
            f"grupo {grupo_indice} ({tipo.upper()})..."
        )

        self.executar_otimizacao(
            tipo,
            originais,
            grupo_indice,
            permitir_lote=True,
        )

    def rodar_simulacao(self):
        """Roda a simulação DEPOIS e compara com a referência capturada."""
        if self.tempo_simulacao_antes is None:
            messagebox.showwarning(
                "Tempo de referência ausente",
                "Clique primeiro em 'Analisar / Recarregar grupos'.\n\n"
                "A GUI rodará automaticamente a simulação inicial e capturará "
                "o tempo ANTES da otimização.",
            )
            return
        self._iniciar_simulacao("depois")

    def _iniciar_simulacao(self, modo: str):
        """Executa `make addition` e captura o último campo time= da saída."""
        if self.executando:
            messagebox.showinfo(
                "Otimização em andamento",
                "Aguarde a otimização terminar antes de rodar a simulação.",
            )
            return

        if self.simulando:
            messagebox.showinfo(
                "Simulação em andamento",
                "Já existe uma simulação em execução.",
            )
            return

        if modo not in {"antes", "depois"}:
            messagebox.showerror("Erro", f"Modo de simulação inválido: {modo}")
            return

        simulation_dir = Path("~/lab/lab16/riscv-3/simulation").expanduser().resolve()

        if not simulation_dir.is_dir():
            messagebox.showerror(
                "Pasta de simulação não encontrada",
                f"Não foi encontrada a pasta:\n{simulation_dir}",
            )
            return

        makefile = simulation_dir / "Makefile"
        if not makefile.exists():
            messagebox.showerror(
                "Makefile não encontrado",
                f"Não foi encontrado Makefile em:\n{simulation_dir}",
            )
            return

        titulo_modo = (
            "ANTES DA OTIMIZAÇÃO" if modo == "antes" else "DEPOIS DA OTIMIZAÇÃO"
        )

        self.log.insert("end", "\n" + "=" * 80 + "\n")
        self.log.insert("end", f"RODANDO SIMULAÇÃO - {titulo_modo}\n")
        self.log.insert("end", f"Pasta: {simulation_dir}\n")
        self.log.insert("end", "Comando: make addition\n")
        self.log.insert("end", "=" * 80 + "\n\n")
        self.log.see("end")

        self.modo_simulacao_atual = modo
        self.ultimo_time_simulacao = None
        self.simulando = True
        self.btn_simulacao.configure(state="disabled")
        self.btn_analisar.configure(state="disabled")
        self.btn_otimizar_todos.configure(state="disabled")
        self.btn_simulacao.configure(state="disabled")
        self.progress.start(10)
        self.var_status.set("Rodando simulação: make addition...")

        threading.Thread(
            target=self._worker_simulacao,
            args=(simulation_dir, modo),
            daemon=True,
        ).start()

    def _worker_simulacao(self, simulation_dir: Path, modo: str):
        try:
            proc = subprocess.Popen(
                ["make", "addition"],
                cwd=str(simulation_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )

            assert proc.stdout is not None
            ultimo_time = None
            time_re = re.compile(
                r"\btime=(\d+)\s+PC=[0-9a-fA-FxX]+\s+"
                r"instruction=[0-9a-fA-FxX]+\s+"
                r"x10=[0-9a-fA-FxX]+\s+x15=[0-9a-fA-FxX]+"
            )

            for line in proc.stdout:
                match = time_re.search(line)
                if match:
                    ultimo_time = int(match.group(1))
                self.after(0, self._append_log, line)

            rc = proc.wait()
            self.after(0, self._fim_simulacao, rc, modo, ultimo_time)

        except Exception as exc:
            self.after(0, self._erro_simulacao, str(exc))

    def _erro_simulacao(self, erro: str):
        self.simulando = False
        self.progress.stop()
        self.btn_simulacao.configure(state="normal")
        self.btn_analisar.configure(state="normal")
        self.btn_otimizar_todos.configure(state="normal")
        self.var_status.set("Falha ao executar a simulação.")

        self.log.insert("end", "\n[ERRO AO RODAR SIMULAÇÃO]\n")
        self.log.insert("end", erro + "\n")
        self.log.see("end")

        messagebox.showerror("Erro na simulação", erro)

    def _fim_simulacao(self, rc: int, modo: str, tempo_capturado):
        self.simulando = False
        self.modo_simulacao_atual = None
        self.progress.stop()
        self.btn_simulacao.configure(state="normal")
        self.btn_analisar.configure(state="normal")
        self.btn_otimizar_todos.configure(state="normal")

        self.log.insert("end", "\n" + "-" * 80 + "\n")

        if rc != 0:
            self.log.insert(
                "end",
                f"SIMULAÇÃO TERMINOU COM ERRO - código de retorno {rc}\n",
            )
            self.var_status.set(f"Simulação terminou com erro (código {rc}).")
            self.log.insert("end", "-" * 80 + "\n")
            self.log.see("end")
            return

        if tempo_capturado is None:
            self.log.insert(
                "end",
                "SIMULAÇÃO CONCLUÍDA, MAS O TIME FINAL NÃO FOI ENCONTRADO.\n",
            )
            self.var_status.set(
                "Simulação concluída, mas o campo time final não foi encontrado."
            )
            self.log.insert("end", "-" * 80 + "\n")
            self.log.see("end")
            messagebox.showwarning(
                "Time não encontrado",
                "Formato esperado, por exemplo:\n\n"
                "time=29010 PC=0000143c instruction=00000013 "
                "x10=81dc9bdb x15=81dc9bdb",
            )
            return

        self.ultimo_time_simulacao = tempo_capturado

        if modo == "antes":
            self.tempo_simulacao_antes = tempo_capturado
            self.tempo_simulacao_depois = None
            self.log.insert("end", f"TIME ANTES CAPTURADO: {tempo_capturado}\n")
            self.var_status.set(
                f"Referência capturada: time={tempo_capturado}. "
                "Agora faça as otimizações e clique em 'Rodar simulação'."
            )
        else:
            self.tempo_simulacao_depois = tempo_capturado
            self.log.insert("end", f"TIME DEPOIS CAPTURADO: {tempo_capturado}\n")
            self.var_status.set(f"Simulação final concluída: time={tempo_capturado}.")

        self.log.insert("end", "SIMULAÇÃO CONCLUÍDA COM SUCESSO\n")
        self.log.insert("end", "-" * 80 + "\n")
        self.log.see("end")

        if modo == "depois":
            self._mostrar_grafico_comparacao()

    def _mostrar_grafico_comparacao(self):
        antes = self.tempo_simulacao_antes
        depois = self.tempo_simulacao_depois
        if antes is None or depois is None:
            return

        diferenca = antes - depois
        percentual = (diferenca / antes * 100.0) if antes else 0.0

        pop = tk.Toplevel(self)
        pop.title("Comparação de desempenho")
        pop.geometry("650x470")
        pop.minsize(560, 420)
        pop.transient(self)

        frame = ttk.Frame(pop, padding=16)
        frame.pack(fill="both", expand=True)

        ttk.Label(
            frame,
            text="Comparação do tempo de simulação",
            font=("TkDefaultFont", 14, "bold"),
        ).pack(pady=(0, 8))

        resumo = ttk.Frame(frame)
        resumo.pack(fill="x", pady=(0, 10))

        ttk.Label(
            resumo,
            text=f"Antes: {antes}",
            font=("TkDefaultFont", 11, "bold"),
        ).pack(side="left", expand=True)

        ttk.Label(
            resumo,
            text=f"Depois: {depois}",
            font=("TkDefaultFont", 11, "bold"),
        ).pack(side="left", expand=True)

        if diferenca > 0:
            resultado = (
                f"Redução: {diferenca} unidades de tempo  •  "
                f"Ganho: {percentual:.2f}%"
            )
        elif diferenca < 0:
            resultado = (
                f"Aumento: {abs(diferenca)} unidades de tempo  •  "
                f"Piora: {abs(percentual):.2f}%"
            )
        else:
            resultado = "Sem alteração no tempo de processamento."

        ttk.Label(
            frame,
            text=resultado,
            font=("TkDefaultFont", 11, "bold"),
            anchor="center",
        ).pack(fill="x", pady=(0, 10))

        canvas = tk.Canvas(
            frame,
            height=280,
            highlightthickness=1,
            highlightbackground="#888888",
            background="white",
        )
        canvas.pack(fill="both", expand=True, pady=(4, 10))

        def desenhar(_event=None):
            canvas.delete("all")
            w = max(canvas.winfo_width(), 400)
            h = max(canvas.winfo_height(), 240)

            ml, mr, mt, mb = 70, 30, 25, 55
            y_base = h - mb
            area_h = y_base - mt
            maximo = max(antes, depois, 1)

            canvas.create_line(ml, mt, ml, y_base, fill="#555555", width=2)
            canvas.create_line(ml, y_base, w - mr, y_base, fill="#555555", width=2)

            valores = [("Antes", antes), ("Depois", depois)]
            area_w = w - ml - mr
            bar_w = min(120, int(area_w * 0.22))
            centers = [ml + area_w * 0.30, ml + area_w * 0.70]
            fills = ["#6c8ebf", "#82b366"]

            for i, ((rotulo, valor), cx) in enumerate(zip(valores, centers)):
                altura = (valor / maximo) * (area_h * 0.88)
                x1, x2 = cx - bar_w / 2, cx + bar_w / 2
                y1 = y_base - altura
                canvas.create_rectangle(
                    x1, y1, x2, y_base,
                    fill=fills[i], outline="#444444"
                )
                canvas.create_text(
                    cx, y1 - 12,
                    text=str(valor),
                    font=("TkDefaultFont", 11, "bold"),
                    fill="#222222",
                )
                canvas.create_text(
                    cx, y_base + 22,
                    text=rotulo,
                    font=("TkDefaultFont", 11, "bold"),
                    fill="#222222",
                )

            canvas.create_text(
                16,
                (mt + y_base) / 2,
                text="time",
                angle=90,
                font=("TkDefaultFont", 10, "bold"),
                fill="#333333",
            )

        canvas.bind("<Configure>", desenhar)
        pop.after(50, desenhar)

        ttk.Button(frame, text="Fechar", command=pop.destroy).pack()

        self.update_idletasks()
        pop.update_idletasks()
        x = self.winfo_rootx() + max(0, (self.winfo_width() - pop.winfo_width()) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - pop.winfo_height()) // 2)
        pop.geometry(f"+{x}+{y}")
        pop.lift()


    def _validar_config(self):
        base = Path(self.var_base.get()).expanduser().resolve()
        destino = Path(self.var_destino.get()).expanduser().resolve()
        entrada = Path(self.var_hex.get()).expanduser().resolve()
        saida = Path(self.var_saida.get()).expanduser().resolve()

        if not base.is_dir():
            raise ValueError("Selecione uma pasta RTL BASE válida.")
        if base == destino:
            raise ValueError("BASE e DESTINO precisam ser pastas diferentes (ex.: modules e modules_custom).")
        obrigatorios = ["pipeline.v", "IF_ID.v", "execute.v"]
        faltando = [x for x in obrigatorios if not (base / x).exists()]
        if faltando:
            raise ValueError("A pasta base não contém: " + ", ".join(faltando))
        if not entrada.exists():
            raise ValueError("O HEX de entrada não existe.")

        # Reproduz o fluxo validado no terminal: entrada vem da BASE e saída vai
        # para DESTINO. Isso impede SameFileError e permite --aplicar-no-base.
        if entrada == saida:
            raise ValueError(
                "HEX de entrada e HEX de saída não podem ser o mesmo arquivo. "
                "Use, por exemplo, modules/imem_custom.hex -> modules_custom/imem_custom.hex."
            )
        saida.parent.mkdir(parents=True, exist_ok=True)
        return base, destino, entrada, saida

    def executar_otimizacao(
        self,
        tipo: str,
        originais: list[str],
        grupo_indice: int,
        permitir_lote: bool = False,
    ):
        if self.simulando:
            messagebox.showinfo(
                "Simulação em andamento",
                "Aguarde a simulação terminar antes de iniciar uma otimização.",
            )
            return

        if self.executando and not permitir_lote:
            messagebox.showinfo("Em execução", "Já existe uma otimização em andamento.")
            return

        try:
            base, destino, entrada, saida = self._validar_config()
        except Exception as exc:
            messagebox.showerror("Configuração inválida", str(exc))
            return

        script = {"addi": SCRIPT_ADDI, "lw": SCRIPT_LW, "sw": SCRIPT_SW}[tipo]
        if not script.exists():
            messagebox.showerror("Script ausente", str(script))
            return

        # Usa exatamente BASE e DESTINO escolhidos, como no comando de terminal:
        # python3 customizar_lw.py modules modules_custom ...
        cmd = [
            sys.executable,
            str(script),
            str(base),
            str(destino),
            "--hex-entrada", str(entrada),
            "--hex-saida", str(saida),
            "--originais",
            *originais,
            "--sobrescrever",
        ]
        if self.var_aplicar_base.get():
            cmd.append("--aplicar-no-base")

        self.log.insert("end", "\n" + "=" * 80 + "\n")
        self.log.insert("end", f"Grupo {grupo_indice} -> {tipo.upper()}\n")
        self.log.insert("end", "Pares enviados:\n")
        for i in range(0, len(originais), 2):
            self.log.insert("end", f"  {originais[i]}  +  {originais[i+1]}\n")
        self.log.insert("end", "\nComando executado:\n  " + " ".join(cmd) + "\n\n")
        self.log.see("end")

        self.executando = True
        self.btn_analisar.configure(state="disabled")
        self.btn_otimizar_todos.configure(state="disabled")
        self.progress.start(10)
        self.var_status.set(f"Otimizando grupo {grupo_indice} como {tipo.upper()}...")

        threading.Thread(
            target=self._worker_subprocess,
            args=(cmd, base, saida, tipo, grupo_indice),
            daemon=True,
        ).start()

    def _worker_subprocess(self, cmd, base: Path, saida: Path, tipo: str, grupo_indice: int):
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                self.after(0, self._append_log, line)
            rc = proc.wait()
            self.after(0, self._fim_execucao, rc, base, saida, tipo, grupo_indice)
        except Exception as exc:
            self.after(0, self._erro_worker, str(exc))

    def _append_log(self, line: str):
        self.log.insert("end", line)
        self.log.see("end")

    def _erro_worker(self, erro: str):
        self.executando = False
        self.progress.stop()
        self.btn_analisar.configure(state="normal")
        self.btn_otimizar_todos.configure(state="normal")
        self.btn_simulacao.configure(state="normal")
        self.fila_otimizacao = []
        estava_em_lote = self.modo_otimizar_todos
        self.modo_otimizar_todos = False
        if estava_em_lote:
            self._parar_indicadores_lote(manter_tempo=True)
            self._finalizar_popup_progresso(sucesso=False)
        self.var_status.set("Falha ao executar o customizador.")
        messagebox.showerror("Erro", erro)

    def _fim_execucao(self, rc: int, base: Path, saida: Path, tipo: str, grupo_indice: int):
        self.executando = False
        self.progress.stop()
        self.btn_analisar.configure(state="normal")
        if not self.modo_otimizar_todos:
            self.btn_otimizar_todos.configure(state="normal")
            self.btn_simulacao.configure(state="normal")

        if rc != 0:
            estava_em_lote = self.modo_otimizar_todos
            self.fila_otimizacao = []
            self.modo_otimizar_todos = False
            self.btn_otimizar_todos.configure(state="normal")
            self.btn_simulacao.configure(state="normal")
            if estava_em_lote:
                self._parar_indicadores_lote(manter_tempo=True)
                self._finalizar_popup_progresso(sucesso=False)
            self.var_status.set(f"Falha ao otimizar grupo {grupo_indice} ({tipo.upper()}).")
            messagebox.showerror(
                "Otimização falhou",
                (
                    "O customizador retornou erro. Veja o log na parte inferior da janela."
                    + (
                        "\n\nA otimização em lote foi interrompida neste grupo."
                        if estava_em_lote else ""
                    )
                ),
            )
            return

        if not saida.exists():
            self.var_status.set("O customizador terminou, mas o HEX de saída não foi encontrado.")
            messagebox.showerror("HEX ausente", f"Saída esperada: {saida}")
            return

        # Com --aplicar-no-base, os customizadores copiam o HEX gerado de volta
        # para BASE usando o mesmo nome do arquivo de saída. Portanto a próxima
        # entrada deve ser BASE/<nome_saida>, exatamente como no fluxo manual.
        if self.var_aplicar_base.get():
            hex_aplicado = base / saida.name
            if not hex_aplicado.exists():
                self.var_status.set("Otimização terminou, mas o HEX aplicado na BASE não foi encontrado.")
                messagebox.showerror(
                    "HEX aplicado ausente",
                    f"Era esperado após --aplicar-no-base:\n{hex_aplicado}",
                )
                return
            self.var_hex.set(str(hex_aplicado))
            # Mantém a saída no DESTINO com o mesmo nome, reproduzindo:
            # modules/imem_custom.hex -> modules_custom/imem_custom.hex
            self.var_saida.set(str(saida))
            hex_atual = hex_aplicado
        else:
            # Sem aplicar na BASE, o resultado vive no DESTINO. Para evitar que
            # entrada e saída virem o mesmo arquivo numa próxima execução, a GUI
            # cria automaticamente um nome alternado.
            self.var_hex.set(str(saida))
            proxima = saida.with_name(saida.stem + "_next.hex")
            self.var_saida.set(str(proxima))
            hex_atual = saida

        if self.modo_otimizar_todos:
            self.otimizacoes_lote_concluidas += 1
            self._atualizar_restantes_lote()
            self._atualizar_popup_progresso()
            self.log.insert(
                "end",
                f"\n[Lote] Grupo {grupo_indice} ({tipo.upper()}) concluído "
                f"({self.otimizacoes_lote_concluidas}/{self.total_otimizacoes_lote}).\n",
            )
            self.log.see("end")
            self.after(50, self._executar_proximo_grupo_lote)
            return

        self.var_status.set(f"Grupo {grupo_indice} otimizado como {tipo.upper()}. Reanalisando HEX...")
        self.carregar_grupos()

        messagebox.showinfo(
            "Concluído",
            f"Grupo {grupo_indice} otimizado como {tipo.upper()}.\n\n"
            f"O HEX atual agora é:\n{hex_atual}",
        )


def main():
    app = OptimizerGUI()
    app.mainloop()


if __name__ == "__main__":
    main()