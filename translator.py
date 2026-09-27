# -*- coding: utf-8 -*-
"""
剪贴板翻译器 —— 复制英文，自动弹出中文译文

零依赖：只用 Python 自带库（tkinter + urllib），不需要 pip install 任何东西。

用法：
    双击 启动.bat  (或者命令行 python translator.py)
"""

import html
import json
import queue
import re
import threading
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request


# ==================== 可调参数 ====================
POLL_MS = 400           # 多久检查一次剪贴板（毫秒）
MIN_LEN = 3             # 短于这个长度不翻译
MAX_LEN = 1500          # 长于这个长度不翻译（太长会拖慢/失败，直接跳过）
HTTP_TIMEOUT = 8        # 网络超时（秒）

WIN_W = 420             # 窗口宽度
WIN_H = 280             # 窗口高度
MARGIN = 24             # 距屏幕右下角的距离
TASKBAR = 48            # 给任务栏留的高度

BG = "#1e1e1e"          # 背景色
BG2 = "#252526"         # 标题栏背景色
FG = "#f0f0f0"          # 正文字色
DIM = "#8a8a8a"         # 次要文字颜色
GREEN = "#4ec9b0"       # 监听中
YELLOW = "#e0a030"      # 翻译中
RED = "#e05555"         # 出错

FONT_MAIN = ("Microsoft YaHei", 11)
FONT_SMALL = ("Microsoft YaHei", 9)

# 翻译引擎：MyMemory —— 公共免费接口，不用注册、不用密钥
API = "https://api.mymemory.translated.net/get"
CHUNK_LIMIT = 450       # 这个接口单次请求的字符上限，超了要分段

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

# 这些符号不算“英文内容”，判断语言时忽略掉
PUNCT = set(".,;:!?()[]{}\"'`~@#$^&*+=|\\/<>-_%—…、，。！？；：（）【】《》“”‘’·")


def is_mostly_chinese(text):
    """判断是不是主要用中文写的（是的话没必要翻译）"""
    cn = 0
    other = 0
    for ch in text:
        if "一" <= ch <= "鿿":
            cn += 1
        elif not ch.isspace() and not ch.isdigit() and ch not in PUNCT:
            other += 1
    if cn == 0:
        return False
    return cn >= other


def _split_chunks(text, limit=CHUNK_LIMIT):
    """把长文本按句子切开，保证每一块都不超过接口的长度上限"""
    chunks = []
    cur = ""
    for piece in re.split(r"(?<=[.!?;])\s+", text):
        while len(piece) > limit:          # 单句就超长，只能硬切
            if cur:
                chunks.append(cur)
                cur = ""
            chunks.append(piece[:limit])
            piece = piece[limit:]
        if not cur:
            cur = piece
        elif len(cur) + 1 + len(piece) <= limit:
            cur = cur + " " + piece
        else:
            chunks.append(cur)
            cur = piece
    if cur:
        chunks.append(cur)
    return chunks or [text[:limit]]


def _translate_chunk(text):
    """翻译一小段（不超过 CHUNK_LIMIT 个字符）"""
    params = urllib.parse.urlencode({"q": text, "langpair": "en|zh-CN"})
    req = urllib.request.Request(API + "?" + params, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))

    status = data.get("responseStatus")
    if status != 200:
        raise ValueError(data.get("responseDetails") or f"接口返回状态 {status}")
    if data.get("quotaFinished"):
        raise ValueError("今天的免费翻译额度用完了，明天自动恢复")

    out = html.unescape((data.get("responseData") or {}).get("translatedText") or "")
    if not out:
        raise ValueError("接口没有返回译文")
    if "MYMEMORY WARNING" in out.upper():
        raise ValueError("今天的免费翻译额度用完了，明天自动恢复")
    return out


def translate(text):
    """英译中。长文本自动分段，翻完再拼起来。"""
    return "".join(_translate_chunk(c) for c in _split_chunks(text))


class ClipTranslator:
    def __init__(self):
        self.enabled = True                 # 是否处于监听状态
        self.last_text = ""                 # 上一次处理过的剪贴板内容
        self.busy = False                   # 是否正在翻译
        self.q = queue.Queue()              # 后台翻译结果队列

        self.root = tk.Tk()
        self.root.title("剪贴板翻译器")
        self.root.overrideredirect(True)    # 去掉系统标题栏，做成悬浮窗
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BG)

        self._place_window()
        self._build_ui()

        # 启动时把当前剪贴板内容记为基线，避免一开机就翻译旧内容
        self.last_text = self._read_clipboard() or ""

        self._tick()

    # ---------- 界面 ----------
    def _place_window(self):
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = sw - WIN_W - MARGIN
        y = sh - WIN_H - MARGIN - TASKBAR
        self.root.geometry(f"{WIN_W}x{WIN_H}+{x}+{y}")

    def _build_ui(self):
        # ---- 标题栏（按住可以拖动窗口）----
        bar = tk.Frame(self.root, bg=BG2, height=30)
        bar.pack(fill="x", side="top")
        bar.pack_propagate(False)

        self.dot = tk.Label(bar, text="●", bg=BG2, fg=GREEN, font=FONT_SMALL)
        self.dot.pack(side="left", padx=(8, 2))

        self.status = tk.Label(bar, text="监听中", bg=BG2, fg=DIM, font=FONT_SMALL)
        self.status.pack(side="left")

        close = tk.Label(bar, text="✕", bg=BG2, fg=DIM, font=FONT_SMALL,
                         cursor="hand2", padx=8)
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: self.root.destroy())

        self.btn_toggle = tk.Label(bar, text="暂停", bg=BG2, fg=DIM,
                                   font=FONT_SMALL, cursor="hand2", padx=8)
        self.btn_toggle.pack(side="right")
        self.btn_toggle.bind("<Button-1>", lambda e: self._toggle())

        self.btn_copy = tk.Label(bar, text="复制译文", bg=BG2, fg=DIM,
                                 font=FONT_SMALL, cursor="hand2", padx=8)
        self.btn_copy.pack(side="right")
        self.btn_copy.bind("<Button-1>", lambda e: self._copy_result())

        for w in (bar, self.dot, self.status):
            w.bind("<Button-1>", self._drag_start)
            w.bind("<B1-Motion>", self._drag_move)

        # ---- 译文 ----
        self.txt_out = tk.Text(self.root, bg=BG, fg=FG, font=FONT_MAIN,
                               wrap="word", bd=0, highlightthickness=0,
                               padx=10, pady=8, height=6, cursor="arrow")
        self.txt_out.pack(fill="both", expand=True)

        # ---- 分隔线 ----
        tk.Frame(self.root, bg="#3a3a3a", height=1).pack(fill="x")

        # ---- 原文 ----
        self.txt_src = tk.Text(self.root, bg=BG, fg=DIM, font=FONT_SMALL,
                               wrap="word", bd=0, highlightthickness=0,
                               padx=10, pady=6, height=4, cursor="arrow")
        self.txt_src.pack(fill="x")

        self._set_text(self.txt_out, "复制一段英文试试～")
        self._set_text(self.txt_src, "")

    def _set_text(self, widget, content):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    def _set_status(self, text, color):
        self.status.configure(text=text)
        self.dot.configure(fg=color)

    # ---------- 拖动窗口 ----------
    def _drag_start(self, event):
        self._dx = event.x_root - self.root.winfo_x()
        self._dy = event.y_root - self.root.winfo_y()

    def _drag_move(self, event):
        self.root.geometry(f"+{event.x_root - self._dx}+{event.y_root - self._dy}")

    # ---------- 按钮 ----------
    def _toggle(self):
        self.enabled = not self.enabled
        self.btn_toggle.configure(text="继续" if not self.enabled else "暂停")
        if self.enabled:
            # 恢复时把当前剪贴板当作基线，避免立刻翻译暂停期间复制的东西
            self.last_text = self._read_clipboard() or ""
            self._set_status("监听中", GREEN)
        else:
            self._set_status("已暂停", DIM)

    def _copy_result(self):
        content = self.txt_out.get("1.0", "end").strip()
        if not content:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(content)
        self.last_text = content      # 防止把自己复制的译文又翻译一遍
        self._set_status("译文已复制", GREEN)

    # ---------- 剪贴板 ----------
    def _read_clipboard(self):
        try:
            return self.root.clipboard_get()
        except tk.TclError:
            # 剪贴板是空的，或者装的是图片/文件等非文字内容
            return None

    # ---------- 主循环 ----------
    def _tick(self):
        if self.enabled and not self.busy:
            text = self._read_clipboard()
            if text and text != self.last_text:
                self.last_text = text
                self._start_translate(text)
        self._drain()
        self.root.after(POLL_MS, self._tick)

    def _start_translate(self, text):
        t = text.strip()
        if len(t) < MIN_LEN or len(t) > MAX_LEN:
            return
        if is_mostly_chinese(t):
            return

        self.busy = True
        self._set_status("翻译中…", YELLOW)
        self._set_text(self.txt_src, t)
        self._set_text(self.txt_out, "翻译中…")

        threading.Thread(target=self._worker, args=(t,), daemon=True).start()

    def _worker(self, text):
        try:
            self.q.put(("ok", translate(text)))
        except urllib.error.URLError as exc:
            self.q.put(("err", f"网络连不上翻译服务器（{getattr(exc, 'reason', exc)}）"))
        except Exception as exc:
            self.q.put(("err", str(exc)))

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "ok":
                    self._set_text(self.txt_out, payload)
                    self._set_status("完成", GREEN)
                else:
                    self._set_text(self.txt_out, "翻译失败：" + payload)
                    self._set_status("失败", RED)
                self.busy = False
        except queue.Empty:
            pass

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    try:
        ClipTranslator().run()
    except Exception:
        import traceback
        with open("error.log", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise
