"""
文件操作工具。

FileOperator 类封装所有文件操作：
- save_to_workplace / write / edit / append: 文件写入
- read_safe / read_lines: 文件读取
- read_uploaded_file / list_uploaded_files: 上传文件处理
- list_dir / file_tree / find_files / get_file_info: 文件系统浏览

文档生成工具（create_document_file, save_ppt_file）在 document_generator.py 中。
"""

import os
import re
import time
import base64
import csv
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

from langchain.tools import tool
from langchain_core.messages import HumanMessage

from app.config import GLM_API_KEY, MULTIMODAL_DOC_ENABLED
from app.infra.llm import get_glm_vision_llm
from app.shared.paths import SERVER_DIR, WORKPLACE_DIR
from app.tools.registry import register


class FileOperator:
    """文件操作器，内置路径安全策略。"""

    # ── 安全配置 ────────────────────────────────────────────────

    ALLOWED_BASE_DIRS: list[Path] = [SERVER_DIR, WORKPLACE_DIR]

    BLOCKED_WRITE_PATTERNS: list[str] = [
        ".env",
        ".git/",
        "__pycache__/",
    ]

    # 允许安全读取的文件类型
    SAFE_READ_EXTENSIONS = {
        ".docx", ".pdf", ".html", ".md", ".log", ".xlsx", ".xls", ".csv", ".tsv",
    }

    # 目录浏览限制
    MAX_TREE_DEPTH = 5
    MAX_FIND_RESULTS = 100
    MAX_LIST_ENTRIES = 200

    # 上传文件限制
    UPLOAD_DIR = WORKPLACE_DIR / "chat-uploads"
    MAX_UPLOAD_CONTENT_CHARS = 15000
    MAX_UPLOAD_PDF_PAGES = 80
    MAX_UPLOAD_DOCX_PARAGRAPHS = 1200
    MAX_MULTIMODAL_PDF_PAGES = 8
    MULTIMODAL_DOC_ENABLED = MULTIMODAL_DOC_ENABLED
    MAX_MULTIMODAL_INPUT_CHARS = 6000
    MAX_EXCEL_SHEETS = 5
    MAX_EXCEL_ROWS_PER_SHEET = 120
    MAX_EXCEL_COLS = 20

    MAX_SAFE_READ_SIZE = 1 * 1024 * 1024  # 1MB
    MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB

    # ── 路径安全检查 ────────────────────────────────────────────

    def is_safe_path(self, file_path: Path) -> bool:
        """检查路径是否在允许的目录范围内。"""
        if not file_path:
            return False
        try:
            resolved = file_path.resolve()
            return any(
                str(resolved).startswith(str(base.resolve()))
                for base in self.ALLOWED_BASE_DIRS
            )
        except (OSError, ValueError, RuntimeError):
            return False

    def check_write_allowed(self, filepath: str) -> tuple[bool, Path, str]:
        """检查文件写入路径是否安全。

        Returns:
            (is_allowed, resolved_path, reason) 三元组
        """
        try:
            p = Path(filepath).resolve()
        except (OSError, ValueError) as e:
            return False, Path(filepath), f"路径解析失败: {e}"

        if not self.is_safe_path(p):
            return False, p, f"路径不在允许范围内: {p}"

        path_str = str(p)
        for pattern in self.BLOCKED_WRITE_PATTERNS:
            if pattern in path_str:
                return False, p, f"禁止写入受保护路径: {pattern}"

        return True, p, ""

    def resolve_path(self, filepath: str) -> Path:
        """将文件路径解析为绝对路径。"""
        path = Path(filepath)
        if not path.is_absolute():
            path = Path(SERVER_DIR) / path
        return path.resolve()

    def is_path_allowed(self, target: str) -> tuple[bool, Path]:
        """检查路径是否存在且在允许的目录范围内。"""
        try:
            p = Path(target).resolve()
            if not p.exists():
                return False, p
            return self.is_safe_path(p), p
        except (OSError, ValueError):
            return False, Path(target)

    # ── 文件读取（按类型）───────────────────────────────────────

    @staticmethod
    def _read_text(path: Path) -> str:
        """读取纯文本文件。"""
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    @staticmethod
    def _looks_like_text_bytes(raw: bytes) -> bool:
        if not raw:
            return True
        if b"\x00" in raw:
            return False
        sample = raw[:4096]
        try:
            decoded = sample.decode("utf-8", errors="replace")
        except Exception:
            return False
        if not decoded:
            return False
        printable = sum(1 for ch in decoded if ch.isprintable() or ch in "\r\n\t")
        ratio = printable / max(len(decoded), 1)
        return ratio >= 0.8

    @classmethod
    def _read_pdf(cls, path: Path) -> str:
        """读取 PDF 文件，提取文本内容。"""
        from pymupdf import open as pdf_open

        text_parts = []
        with pdf_open(str(path)) as doc:
            total_pages = len(doc)
            pages_to_read = min(total_pages, cls.MAX_UPLOAD_PDF_PAGES)
            for idx in range(pages_to_read):
                text_parts.append(doc[idx].get_text())
            if total_pages > cls.MAX_UPLOAD_PDF_PAGES:
                text_parts.append(
                    f"\n[...PDF共{total_pages}页，为保护性能仅提取前{cls.MAX_UPLOAD_PDF_PAGES}页...]"
                )
        return "\n".join(text_parts)

    @classmethod
    def _read_docx(cls, path: Path) -> str:
        """读取 Word 文档，提取段落文本。"""
        from docx import Document

        doc = Document(str(path))
        paragraphs = [para.text for para in doc.paragraphs if para.text.strip()]
        total_paragraphs = len(paragraphs)
        content = "\n".join(paragraphs[: cls.MAX_UPLOAD_DOCX_PARAGRAPHS])
        if total_paragraphs > cls.MAX_UPLOAD_DOCX_PARAGRAPHS:
            content += (
                f"\n\n[...DOCX共{total_paragraphs}段，为保护性能仅提取前{cls.MAX_UPLOAD_DOCX_PARAGRAPHS}段...]"
            )
        return content

    @classmethod
    def _read_excel(cls, path: Path) -> str:
        """读取 Excel/CSV/TSV 文件，提取结构化表格文本。"""
        suffix = path.suffix.lower()
        if suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            lines: list[str] = []
            with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
                reader = csv.reader(f, delimiter=delimiter)
                for i, row in enumerate(reader):
                    if i >= cls.MAX_EXCEL_ROWS_PER_SHEET:
                        lines.append(f"... (已截断，仅显示前 {cls.MAX_EXCEL_ROWS_PER_SHEET} 行)")
                        break
                    cells = [str(v).strip() for v in row[: cls.MAX_EXCEL_COLS]]
                    lines.append(" | ".join(cells))
            return "\n".join(lines).strip()

        if suffix == ".xlsx":
            from openpyxl import load_workbook

            wb = load_workbook(filename=str(path), read_only=True, data_only=True)
            output: list[str] = []
            for sheet_idx, ws in enumerate(wb.worksheets[: cls.MAX_EXCEL_SHEETS], start=1):
                output.append(f"[Sheet {sheet_idx}] {ws.title}")
                for row_idx, row in enumerate(
                    ws.iter_rows(min_row=1, max_row=cls.MAX_EXCEL_ROWS_PER_SHEET, values_only=True),
                    start=1,
                ):
                    cells = ["" if v is None else str(v).strip() for v in list(row)[: cls.MAX_EXCEL_COLS]]
                    if any(cells):
                        output.append(" | ".join(cells))
                output.append("")
            if len(wb.worksheets) > cls.MAX_EXCEL_SHEETS:
                output.append(f"... (已截断，仅分析前 {cls.MAX_EXCEL_SHEETS} 个工作表)")
            return "\n".join(output).strip()

        if suffix == ".xls":
            try:
                import pandas as pd
            except Exception as exc:
                return f".xls 解析依赖缺失：{exc}"

            sheets = pd.read_excel(str(path), sheet_name=None, dtype=str)
            output: list[str] = []
            for idx, (sheet_name, df) in enumerate(list(sheets.items())[: cls.MAX_EXCEL_SHEETS], start=1):
                output.append(f"[Sheet {idx}] {sheet_name}")
                df = df.fillna("").astype(str).head(cls.MAX_EXCEL_ROWS_PER_SHEET)
                cols = list(df.columns.astype(str))[: cls.MAX_EXCEL_COLS]
                if cols:
                    output.append(" | ".join(cols))
                for _, row in df.iterrows():
                    values = [str(row[c]).strip() for c in cols]
                    output.append(" | ".join(values))
                output.append("")
            if len(sheets) > cls.MAX_EXCEL_SHEETS:
                output.append(f"... (已截断，仅分析前 {cls.MAX_EXCEL_SHEETS} 个工作表)")
            return "\n".join(output).strip()

        return ""

    def _read_by_suffix(self, path: Path) -> str | None:
        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._read_pdf(path)
        if suffix == ".docx":
            return self._read_docx(path)
        if suffix in {".xlsx", ".xls", ".csv", ".tsv"}:
            return self._read_excel(path)
        if suffix in {".txt", ".md", ".log", ".html"}:
            return path.read_text(encoding="utf-8", errors="replace")
        return None

    def _analyze_with_multimodal(self, path: Path) -> str | None:
        """统一多模态分析入口：先尝试视觉/多模态总结。"""
        if not self.MULTIMODAL_DOC_ENABLED:
            return None
        if not GLM_API_KEY:
            return None

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._read_pdf_with_multimodal(path)

        base_content = self._read_by_suffix(path)
        if not base_content:
            return None
        snippet = base_content[: self.MAX_MULTIMODAL_INPUT_CHARS]
        if not snippet.strip():
            return None

        try:
            llm = get_glm_vision_llm(temperature=0.2)
            prompt = (
                "你是文档分析助手。请基于以下文档提取内容给出结构化分析：\n"
                "1) 文档主题与摘要\n"
                "2) 关键数据/条款/结论\n"
                "3) 风险点或待确认项\n"
                "4) 建议的后续问题\n\n"
                f"文档内容片段：\n{snippet}"
            )
            resp = llm.invoke([HumanMessage(content=prompt)])
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            text = (text or "").strip()
            return text or None
        except Exception:
            return None

    def _read_pdf_with_multimodal(self, path: Path) -> str | None:
        """使用多模态模型解析 PDF（优先版式识别），失败返回 None。"""
        if not self.MULTIMODAL_DOC_ENABLED:
            return None
        if not GLM_API_KEY:
            return None
        try:
            from pymupdf import open as pdf_open
        except Exception:
            return None

        try:
            content_blocks: list[dict] = [{
                "type": "text",
                "text": (
                    "请逐页识别并结构化提取该文档，输出中文："
                    "1) 关键主题；2) 章节与要点；3) 表格/数字信息；4) 需要注意的上下文与限制。"
                ),
            }]

            with pdf_open(str(path)) as doc:
                if len(doc) <= 0:
                    return None
                pages_to_read = min(len(doc), self.MAX_MULTIMODAL_PDF_PAGES)
                for idx in range(pages_to_read):
                    pix = doc[idx].get_pixmap(dpi=110, alpha=False)
                    png_bytes = pix.tobytes("png")
                    b64 = base64.b64encode(png_bytes).decode("ascii")
                    content_blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{b64}"},
                    })

            llm = get_glm_vision_llm(temperature=0.2)
            resp = llm.invoke([HumanMessage(content=content_blocks)])
            text = resp.content if isinstance(resp.content, str) else str(resp.content)
            text = (text or "").strip()
            if not text:
                return None
            if len(text) > self.MAX_UPLOAD_CONTENT_CHARS:
                text = text[:self.MAX_UPLOAD_CONTENT_CHARS] + "\n\n[...多模态解析结果过长，已截断...]"
            return text
        except Exception:
            return None

    def _try_read_text(self, path: Path) -> str | None:
        try:
            raw = path.read_bytes()
            if not self._looks_like_text_bytes(raw):
                return None
            text = raw.decode("utf-8", errors="replace")
            return text if text.strip() else None
        except Exception:
            return None

    def _try_read_pdf(self, path: Path) -> str | None:
        try:
            text = self._read_pdf(path)
            return text if text.strip() else None
        except Exception:
            return None

    def _try_read_docx(self, path: Path) -> str | None:
        try:
            text = self._read_docx(path)
            return text if text.strip() else None
        except Exception:
            return None

    # ── 辅助函数 ────────────────────────────────────────────────

    @staticmethod
    def _format_size(size: int) -> str:
        """将字节数格式化为可读字符串。"""
        if size < 1024:
            return f"{size} B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f} KB"
        elif size < 1024 * 1024 * 1024:
            return f"{size / (1024 * 1024):.1f} MB"
        else:
            return f"{size / (1024 * 1024 * 1024):.1f} GB"

    # ── 操作方法 ────────────────────────────────────────────────

    def save_to_workplace(
        self,
        sub_dir: Literal["mindmap", "content", "code", "quiz", "reading", "image", "video", "ppt"],
        topic: str,
        content: str,
        ext: str = "md",
    ) -> str:
        """将内容保存到 workplace 下的指定子目录，文件名按主题+时间戳生成。"""
        target_dir = WORKPLACE_DIR / sub_dir
        target_dir.mkdir(parents=True, exist_ok=True)

        safe_topic = re.sub(r'[\\/*?:"<>|]', "", topic).strip()[:50]
        if not safe_topic:
            safe_topic = "untitled"

        filename = f"{safe_topic}_{int(time.time())}.{ext}"
        filepath = target_dir / filename

        filepath.write_text(content, encoding="utf-8")
        return str(filepath)

    def write(self, filepath: str, content: str, create_dirs: bool = True) -> str:
        """创建或覆盖文件，写入指定内容。"""
        allowed, resolved, reason = self.check_write_allowed(filepath)
        if not allowed:
            return f"❌ {reason}"

        if len(content) > self.MAX_FILE_SIZE:
            return f"❌ 内容过大: {len(content)} 字节（最大 {self.MAX_FILE_SIZE} 字节）"

        try:
            if create_dirs:
                resolved.parent.mkdir(parents=True, exist_ok=True)

            resolved.write_text(content, encoding="utf-8")
            return f"✓ 文件已写入: {resolved} ({len(content)} 字符)"

        except Exception as e:
            return f"❌ 写入失败: {type(e).__name__}: {e}"

    def edit(self, filepath: str, start_line: int, end_line: int, new_content: str) -> str:
        """按行号范围替换文件内容。"""
        allowed, resolved, reason = self.check_write_allowed(filepath)
        if not allowed:
            return f"❌ {reason}"

        if not resolved.exists():
            return f"❌ 文件不存在: {filepath}"

        try:
            lines = resolved.read_text(encoding="utf-8").splitlines(keepends=True)
            total_lines = len(lines)

            if start_line < 1 or start_line > total_lines:
                return f"❌ 起始行号无效: {start_line}（文件共 {total_lines} 行）"
            if end_line < start_line:
                return f"❌ 结束行号不能小于起始行号: end={end_line} < start={start_line}"
            end_line = min(end_line, total_lines)

            new_lines = new_content.splitlines(keepends=True)
            if new_lines and not new_lines[-1].endswith("\n"):
                new_lines[-1] += "\n"

            replaced_count = end_line - start_line + 1
            new_all_lines = lines[: start_line - 1] + new_lines + lines[end_line:]

            resolved.write_text("".join(new_all_lines), encoding="utf-8")

            return (
                f"✓ 文件已编辑: {resolved}\n"
                f"  替换行 {start_line}-{end_line}（共 {replaced_count} 行）→ {len(new_lines)} 行\n"
                f"  文件总行数: {total_lines} → {len(new_all_lines)}"
            )

        except Exception as e:
            return f"❌ 编辑失败: {type(e).__name__}: {e}"

    def append(self, filepath: str, content: str) -> str:
        """追加内容到文件末尾（文件不存在则创建）。"""
        allowed, resolved, reason = self.check_write_allowed(filepath)
        if not allowed:
            return f"❌ {reason}"

        if len(content) > self.MAX_FILE_SIZE:
            return f"❌ 内容过大: {len(content)} 字节"

        try:
            resolved.parent.mkdir(parents=True, exist_ok=True)

            existing = ""
            if resolved.exists():
                existing = resolved.read_text(encoding="utf-8")
                if existing and not existing.endswith("\n"):
                    existing += "\n"

            resolved.write_text(existing + content, encoding="utf-8")

            return f"✓ 内容已追加: {resolved}（文件总大小: {self._format_size(len(existing + content))})"

        except Exception as e:
            return f"❌ 追加失败: {type(e).__name__}: {e}"

    def read_safe(self, file_path: str) -> str:
        """安全读取文件内容（仅允许指定目录和文件类型）。"""
        try:
            path = self.resolve_path(file_path)

            if not self.is_safe_path(path):
                return "❌ 拒绝访问：越权路径"

            if not path.exists():
                return "❌ 文件不存在"

            if not path.is_file():
                return "❌ 不是文件"

            if path.suffix not in self.SAFE_READ_EXTENSIONS:
                return f"❌ 不允许的文件类型: {path.suffix}"

            size = os.path.getsize(path)
            if size > self.MAX_SAFE_READ_SIZE:
                return f"❌ 文件过大: {size} bytes"

            suffix = path.suffix.lower()
            if suffix == ".pdf":
                content = self._read_pdf(path)
            elif suffix == ".docx":
                content = self._read_docx(path)
            else:
                content = self._read_text(path)

            return content if content else "⚠️ 文件为空"

        except Exception as e:
            return f"❌ 读取失败: {str(e)}"

    def read_lines(
        self,
        filepath: str,
        start_line: int = 1,
        end_line: int = 0,
        show_line_numbers: bool = True,
    ) -> str:
        """读取文件的指定行范围。"""
        try:
            path = self.resolve_path(filepath)

            if not self.is_safe_path(path):
                return "❌ 拒绝访问：越权路径"

            if not path.exists():
                return f"❌ 文件不存在: {filepath}"

            if path.stat().st_size > self.MAX_FILE_SIZE:
                return f"❌ 文件过大（超过 {self.MAX_FILE_SIZE} 字节）"

            content = path.read_text(encoding="utf-8", errors="replace")
            lines = content.splitlines()

            total_lines = len(lines)
            start = max(start_line, 1) - 1  # 转为 0-based
            end = end_line if end_line > 0 else total_lines
            end = min(end, total_lines)

            selected = lines[start:end]

            if show_line_numbers:
                numbered = [f"{i:>6}\t{line}" for i, line in enumerate(selected, start=start + 1)]
                result = "\n".join(numbered)
            else:
                result = "\n".join(selected)

            header = f"文件: {path} (行 {start+1}-{end}/{total_lines})\n{'─' * 50}\n"
            return header + result

        except Exception as e:
            return f"❌ 读取失败: {type(e).__name__}: {e}"

    # ── 上传文件操作 ────────────────────────────────────────────

    def _resolve_upload_path(self, file_url: str):
        from typing import Optional
        if file_url.startswith("/api/v1/ai/chat/uploads/"):
            relative = file_url.removeprefix("/api/v1/ai/chat/uploads/")
        elif file_url.startswith("/uploads/"):
            relative = file_url.removeprefix("/uploads/")
        else:
            # 允许直接传本地绝对路径（chat-uploads/<user>/<session>/<file>）
            try:
                path = Path(file_url).expanduser().resolve()
            except (OSError, RuntimeError, ValueError):
                return None
            upload_root = self.UPLOAD_DIR.resolve()
            if not str(path).startswith(str(upload_root)):
                return None
            if not path.exists():
                return None
            parts = list(path.relative_to(upload_root).parts)
            if len(parts) != 3:
                return None
            owner_part = parts[0]
            if not owner_part.isdigit():
                return None
            session_part, filename = parts[1], parts[2]
            if Path(session_part).name != session_part or Path(filename).name != filename:
                return None
            user_dir = (self.UPLOAD_DIR / owner_part).resolve()
            session_dir = (user_dir / session_part).resolve()
            if not str(path).startswith(str(session_dir)):
                return None
            return int(owner_part), path
        parts = [part for part in relative.split("/") if part]
        if len(parts) != 3:
            return None
        owner_part = parts[0]
        if not owner_part.isdigit():
            return None
        user_dir = (self.UPLOAD_DIR / owner_part).resolve()
        session_part, filename = parts[1], parts[2]
        if Path(session_part).name != session_part or Path(filename).name != filename:
            return None
        session_dir = (user_dir / session_part).resolve()
        path = (session_dir / filename).resolve()
        if not str(session_dir).startswith(str(user_dir)):
            return None
        if not str(path).startswith(str(session_dir)):
            return None
        if not path.exists():
            return None
        return int(owner_part), path

    def _read_uploaded_file_impl(self, path: Path) -> str:
        if not path.exists():
            return f"文件不存在: {path}"
        if not path.is_file():
            return f"路径不是文件: {path}"

        # 统一文档读取：并行执行「多模态分析」与「后缀解析」并合并结果。
        mm_text: str | None = None
        suffix_text: str | None = None
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                mm_future = pool.submit(self._analyze_with_multimodal, path)
                suffix_future = pool.submit(self._read_by_suffix, path)
                mm_text = mm_future.result()
                suffix_text = suffix_future.result()
        except Exception:
            mm_text = None
            suffix_text = None

        if not suffix_text:
            parsers = (self._try_read_text, self._try_read_pdf, self._try_read_docx)
            for parser in parsers:
                suffix_text = parser(path)
                if suffix_text:
                    break

        sections: list[str] = []
        if mm_text and mm_text.strip():
            sections.append(f"【多模态分析】\n{mm_text.strip()}")
        if suffix_text and suffix_text.strip():
            sections.append(f"【后缀结构提取】\n{suffix_text.strip()}")

        if not sections:
            return "无法识别该文档内容（可能是加密文件、损坏文件或不支持格式）。"

        content = "\n\n".join(sections)
        if len(content) > self.MAX_UPLOAD_CONTENT_CHARS:
            content = content[:self.MAX_UPLOAD_CONTENT_CHARS] + "\n\n[...文档内容过长，已截断...]"
        return content

    def read_uploaded_file(self, file_url: str) -> str:
        from app.shared.request_context import get_current_user_id
        current_user_id = get_current_user_id()
        if current_user_id is None:
            return "读取失败：缺少用户上下文。"
        resolved = self._resolve_upload_path(file_url)
        if resolved is None:
            return f"无法解析文件路径: {file_url}。请确认文件 URL 格式正确且文件存在。"
        owner_id, absolute_path = resolved
        if owner_id != current_user_id:
            return "无权限读取该文件。"
        return self._read_uploaded_file_impl(absolute_path)

    def list_uploaded_files(self) -> str:
        from app.shared.request_context import get_current_user_id
        current_user_id = get_current_user_id()
        if current_user_id is None:
            return "读取失败：缺少用户上下文。"
        user_dir = self.UPLOAD_DIR / str(current_user_id)
        if not user_dir.exists():
            return "用户暂无上传文件。"
        files = [f for f in user_dir.rglob("*") if f.is_file()]
        if not files:
            return "用户暂无上传文件。"
        return "用户上传的文件列表:\n" + "\n".join(
            f"- {f.relative_to(user_dir)} ({f.stat().st_size} bytes)" for f in files
        )

    # ── 目录浏览操作 ────────────────────────────────────────────

    def list_dir(self, path: str = "", show_hidden: bool = False, pattern: str = "") -> str:
        target = path or str(SERVER_DIR)
        allowed, resolved = self.is_path_allowed(target)
        if not allowed:
            return f"❌ 路径被拒绝: {target}（仅允许项目目录）"
        if not resolved.is_dir():
            return f"❌ 不是目录: {target}"
        try:
            entries = sorted(resolved.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
            lines = [f"📁 {resolved}/", ""]
            count = 0
            for entry in entries:
                if count >= self.MAX_LIST_ENTRIES:
                    lines.append(f"... (已截断，最多显示 {self.MAX_LIST_ENTRIES} 项)")
                    break
                if not show_hidden and entry.name.startswith("."):
                    continue
                if pattern and entry.is_file() and not entry.match(pattern):
                    continue
                if entry.is_dir():
                    lines.append(f"  [DIR]  {entry.name}/")
                else:
                    lines.append(f"  [FILE] {entry.name}  ({self._format_size(entry.stat().st_size)})")
                count += 1
            lines.append(f"\n共 {count} 项")
            return "\n".join(lines)
        except PermissionError:
            return f"❌ 权限不足: {target}"
        except Exception as e:
            return f"❌ 列出目录失败: {type(e).__name__}: {e}"

    def file_tree(self, path: str = "", max_depth: int = 3,
                  ignore_dirs: str = "__pycache__,.git,node_modules,.venv,.idea") -> str:
        target = path or str(SERVER_DIR)
        allowed, resolved = self.is_path_allowed(target)
        if not allowed:
            return f"❌ 路径被拒绝: {target}"
        if not resolved.is_dir():
            return f"❌ 不是目录: {target}"
        max_depth = min(max(max_depth, 1), self.MAX_TREE_DEPTH)
        ignore_set = set(d.strip() for d in ignore_dirs.split(",") if d.strip())
        lines: list[str] = [f"{resolved.name}/"]
        _build_tree(resolved, lines, "", 0, max_depth, ignore_set)
        return "\n".join(lines)

    def find_files(self, name_pattern: str = "", extension: str = "",
                   path: str = "", max_results: int = 50) -> str:
        target = path or str(SERVER_DIR)
        allowed, resolved = self.is_path_allowed(target)
        if not allowed:
            return f"❌ 路径被拒绝: {target}"
        if not resolved.is_dir():
            return f"❌ 不是目录: {target}"
        if extension and not extension.startswith("."):
            extension = f".{extension}"
        max_results = min(max_results, self.MAX_FIND_RESULTS)
        results: list[str] = []
        try:
            for root, dirs, files in os.walk(resolved):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
                for filename in sorted(files):
                    filepath = Path(root) / filename
                    if extension and filepath.suffix.lower() != extension.lower():
                        continue
                    if name_pattern and name_pattern.lower() not in filename.lower():
                        continue
                    try:
                        results.append(str(filepath.relative_to(resolved)))
                    except ValueError:
                        results.append(str(filepath))
                    if len(results) >= max_results:
                        break
                if len(results) >= max_results:
                    break
            if not results:
                return f"未找到匹配文件 (pattern={name_pattern!r}, ext={extension!r})"
            lines = [f"在 {resolved} 中找到 {len(results)} 个文件:", ""]
            lines.extend(f"  {r}" for r in results)
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 搜索失败: {type(e).__name__}: {e}"

    def get_file_info(self, path: str) -> str:
        allowed, resolved = self.is_path_allowed(path)
        if not allowed:
            return f"❌ 路径被拒绝: {path}"
        if not resolved.exists():
            return f"❌ 不存在: {path}"
        try:
            stat = resolved.stat()
            lines = [
                f"路径: {resolved}",
                f"类型: {'目录' if resolved.is_dir() else '文件'}",
                f"大小: {self._format_size(stat.st_size)}",
                f"修改时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_mtime))}",
                f"权限: {oct(stat.st_mode)[-3:]}",
            ]
            if resolved.is_file():
                lines.append(f"扩展名: {resolved.suffix or '(无)'}")
            if resolved.is_dir():
                try:
                    items = list(resolved.iterdir())
                    files = sum(1 for i in items if i.is_file())
                    dirs = sum(1 for i in items if i.is_dir())
                    lines.append(f"内容: {dirs} 个目录, {files} 个文件")
                except PermissionError:
                    pass
            return "\n".join(lines)
        except Exception as e:
            return f"❌ 获取信息失败: {type(e).__name__}: {e}"


def _build_tree(directory: Path, lines: list[str], prefix: str,
                depth: int, max_depth: int, ignore: set[str]) -> None:
    """递归构建目录树结构。"""
    if depth >= max_depth:
        return
    try:
        entries = sorted(directory.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
    except PermissionError:
        return
    entries = [e for e in entries if e.name not in ignore and not e.name.startswith(".")]
    for i, entry in enumerate(entries):
        is_last = i == len(entries) - 1
        connector = "└── " if is_last else "├── "
        child_prefix = "    " if is_last else "│   "
        if entry.is_dir():
            lines.append(f"{prefix}{connector}{entry.name}/")
            _build_tree(entry, lines, prefix + child_prefix, depth + 1, max_depth, ignore)
        else:
            lines.append(f"{prefix}{connector}{entry.name}")


# ──────────────────────────────────────────────────────────────
# 单例 + @tool 注册
# ──────────────────────────────────────────────────────────────

_file_op = FileOperator()


@tool("save_to_workplace")
def save_to_workplace(
    sub_dir: Literal["mindmap", "content", "code", "quiz", "reading", "image", "video", "ppt"],
    topic: str,
    content: str,
    ext: str = "md"
) -> str:
    """将内容保存到 workplace 下的指定子目录，文件名按主题+时间戳生成。"""
    return _file_op.save_to_workplace(sub_dir, topic, content, ext)


@tool("write_file")
def write_file(filepath: str, content: str, create_dirs: bool = True) -> str:
    """创建或覆盖文件，写入指定内容（必须在项目目录下）。"""
    return _file_op.write(filepath, content, create_dirs)


@tool("edit_file")
def edit_file(filepath: str, start_line: int, end_line: int, new_content: str) -> str:
    """按行号范围替换文件内容。"""
    return _file_op.edit(filepath, start_line, end_line, new_content)


@tool("append_file")
def append_file(filepath: str, content: str) -> str:
    """追加内容到文件末尾（文件不存在则创建）。"""
    return _file_op.append(filepath, content)


@tool("read_file_safe")
def read_file_safe(file_path: str) -> str:
    """安全读取文件内容，仅允许访问指定目录下的文本文件。"""
    return _file_op.read_safe(file_path)


@tool("read_file_lines")
def read_file_lines(filepath: str, start_line: int = 1, end_line: int = 0, show_line_numbers: bool = True) -> str:
    """读取文件的指定行范围（比 read_file_safe 更精确的行级读取）。"""
    return _file_op.read_lines(filepath, start_line, end_line, show_line_numbers)


@tool("read_uploaded_file")
def read_uploaded_file(file_url: str) -> str:
    """统一读取并分析当前用户上传文档（Word/PDF/Excel 等）：多模态优先 + 后缀并行解析。"""
    return _file_op.read_uploaded_file(file_url)


@tool("list_uploaded_files")
def list_uploaded_files() -> str:
    """列出当前用户上传的所有文件。"""
    return _file_op.list_uploaded_files()


@tool("list_directory")
def list_directory(path: str = "", show_hidden: bool = False, pattern: str = "") -> str:
    """列出指定目录下的文件和子目录。"""
    return _file_op.list_dir(path, show_hidden, pattern)


@tool("file_tree")
def file_tree(path: str = "", max_depth: int = 3,
              ignore_dirs: str = "__pycache__,.git,node_modules,.venv,.idea") -> str:
    """显示目录树结构。"""
    return _file_op.file_tree(path, max_depth, ignore_dirs)


@tool("find_files")
def find_files(name_pattern: str = "", extension: str = "", path: str = "",
               max_results: int = 50) -> str:
    """在目录中搜索文件。"""
    return _file_op.find_files(name_pattern, extension, path, max_results)


@tool("get_file_info")
def get_file_info(path: str) -> str:
    """获取文件或目录的详细信息。"""
    return _file_op.get_file_info(path)


# 自注册到工具注册表
register(save_to_workplace)
register(write_file)
register(edit_file)
register(append_file)
register(read_file_safe)
register(read_file_lines)
register(read_uploaded_file)
register(list_uploaded_files)
register(list_directory)
register(file_tree)
register(find_files)
register(get_file_info)
