import csv
import os
import time
import re
import json
import warnings
import fitz  # PyMuPDF
from openai import OpenAI

# ================= 🛡️ 配置区域 =================

# 1. 填入 OpenAI/DeepSeek API Key

OPENAI_API_KEY = "填入你的API"

# 2. 模型选择
MODEL_NAME = "deepseek-chat"  # 或 deepseek-chat

# 3. 路径配置
MY_PAPERS_DIR = "./my_papers"
SOURCE_DIR = "./source_papers"
OUTPUT_DIR = "./output_papers"

SUMMARY_FIELDS = [
    "paper_file",
    "status",
    "author_passed",
    "target_author",
    "matched_citation_count",
    "matched_citations",
    "error",
]


def write_summary_report(results, output_dir=OUTPUT_DIR):
    """Write one CSV row for each source PDF processed in this run."""
    os.makedirs(output_dir, exist_ok=True)
    summary_path = os.path.join(output_dir, "summary.csv")
    with open(summary_path, "w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=SUMMARY_FIELDS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(results)
    return summary_path


# ==============================================

warnings.filterwarnings("ignore")
client = OpenAI(api_key=OPENAI_API_KEY, base_url="https://api.deepseek.com" if "deepseek" in MODEL_NAME else None)


class PaperProcessor:
    def __init__(self, pdf_path, my_titles):
        self.pdf_path = pdf_path
        self.filename = os.path.basename(pdf_path)
        try:
            self.doc = fitz.open(pdf_path)
        except Exception as e:
            print(f"  [!] PDF 损坏: {e}")
            self.doc = None
            self.pdf_error = str(e)
        self.my_titles = my_titles
        self.pdf_error = ""

    def _summary_result(
        self,
        status,
        author_passed="",
        target_author="",
        matched_citations=None,
        error="",
    ):
        matched_citations = matched_citations or []
        return {
            "paper_file": self.filename,
            "status": status,
            "author_passed": author_passed,
            "target_author": target_author or "",
            "matched_citation_count": len(matched_citations),
            "matched_citations": "; ".join(matched_citations),
            "error": error,
        }

    def get_text_safe(self, page_num):
        if self.doc and page_num < len(self.doc):
            return self.doc[page_num].get_text()
        return ""

    def check_authors(self):
        """步骤1: 严格筛选正教授 (Full Professor Only)"""
        if not self.doc: return {"passed": False}
        text = self.get_text_safe(0)[:3500]  # 多读一点，防止简介在后面
        # 有些期刊作者介绍在最后，尝试读取最后2页拼上来
        if len(self.doc) > 2:
            text += "\n" + self.doc[-1].get_text() + "\n" + self.doc[-2].get_text()

        print(f"    [🔍] 正在严格核查作者职级...", end="\r")

        system_prompt = "You are a strict academic reviewer. Output JSON only."
        user_prompt = f"""
        Analyze the author biographies or affiliations in the text below.

        Strict Criteria (Pass if ANY is true):
        1. Contains a **Full Professor** from a non-Chinese university.
           - ❌ EXCLUDE: "Assistant Professor", "Associate Professor", "Lecturer", "Reader".
           - ✅ INCLUDE: "Professor", "Chair Professor", "Distinguished Professor".
        2. Contains an IEEE Fellow or ACM Fellow.

        Text:
        {text[:5000]}

        JSON Output: 
        {{ 
            "passed": boolean, 
            "target_author_name": "Name of the Full Professor/Fellow", 
            "title_detected": "e.g. Assistant Professor (Fail) / Full Professor (Pass)",
            "reason": "Explain why it passed or failed based on the title" 
        }}
        """
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            res = json.loads(response.choices[0].message.content)

            # 打印一下 AI 看到的职级，方便你确认
            if res.get('passed'):
                pass
            else:
                print(f"    [⛔] 职级不符: {res.get('target_author_name')} is {res.get('title_detected')}")

            return res
        except Exception as e:
            print(f"      [!] API请求失败: {e}")
            return None

    def find_citation_marker(self, target_title):
        """步骤2: 强力容错搜索"""
        if not self.doc: return None
        clean_target = re.sub(r'[^a-zA-Z0-9]', '', target_title).lower()[:30]
        raw_text = ""
        for i in range(max(0, len(self.doc) - 10), len(self.doc)):
            raw_text += self.doc[i].get_text()
        fuzzy_pattern = ""
        for char in clean_target:
            fuzzy_pattern += re.escape(char) + r'[^a-zA-Z0-9]*'
        match = re.search(fuzzy_pattern, raw_text, re.IGNORECASE)
        if not match: return None
        title_start_idx = match.start()
        pre_text = raw_text[max(0, title_start_idx - 1500):title_start_idx]
        bracket_matches = re.findall(r'\[(\d+)\]', pre_text)
        if bracket_matches: return f"[{bracket_matches[-1]}]"
        dot_matches = re.findall(r'(\n|^|\s)(\d+)\.', pre_text)
        if dot_matches: return dot_matches[-1][1]
        return None

    def evaluate_citation_quality(self, marker, target_title):
        """步骤3: AI 判质量"""
        if not self.doc: return False
        contexts = []
        escaped_marker = re.escape(marker)
        for page in self.doc:
            text = page.get_text().replace('\n', ' ')
            for match in re.finditer(escaped_marker, text):
                snippet = text[match.start():match.end() + 100]
                if target_title.lower()[:15] in snippet.lower(): continue
                start = max(0, match.start() - 200)
                end = min(len(text), match.end() + 200)
                contexts.append(text[start:end])
        if not contexts: return False

        print(f"      [⚖️] 正在鉴定引用质量...", end="\r")
        system_prompt = "Strict reviewer. JSON only."
        user_prompt = f"""
        Marker "{marker}" in contexts: {json.dumps(contexts)}
        Determine if ANY is a "Meaningful Citation" (Discusses/Compares/Uses).
        Skip if it's just a list [1, 2].
        JSON: {{ "passed": boolean, "reason": "Text" }}
        """
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
                response_format={"type": "json_object"}, temperature=0.1
            )
            res = json.loads(response.choices[0].message.content)
            return res.get("passed")
        except:
            return True

    def apply_all_highlights(self, author_name, all_markers):
        """步骤4: 分步稳定高亮"""
        if not self.doc: return
        if author_name:
            rects = self.doc[0].search_for(author_name)
            if not rects:
                parts = author_name.split()
                if len(parts) > 1: rects = self.doc[0].search_for(parts[-1])
            for rect in rects:
                try:
                    annot = self.doc[0].add_highlight_annot(rect)
                    if annot: annot.set_colors(stroke=(1, 1, 0)); annot.update()
                except:
                    pass
        unique_markers = list(set(all_markers))
        for marker in unique_markers:
            for page in self.doc:
                hits = page.search_for(marker)
                for rect in hits:
                    try:
                        annot = page.add_highlight_annot(rect)
                        if annot: annot.set_colors(stroke=(0, 1, 0)); annot.update()
                    except:
                        pass

    def save_to_subfolders(self, valid_citations):
        """分发保存 (带文件名截断)"""
        for my_title in valid_citations:
            safe_folder_name = re.sub(r'[\\/*?:"<>|]', "_", my_title)[:50].strip()
            sub_folder = os.path.join(OUTPUT_DIR, safe_folder_name)
            sub_folder = os.path.abspath(sub_folder)
            if not os.path.exists(sub_folder): os.makedirs(sub_folder)

            name_part, ext = os.path.splitext(self.filename)
            safe_name_part = re.sub(r'[\\/*?:"<>|]', "_", name_part)[:80].strip()
            final_filename = f"Result_{safe_name_part}{ext}"
            save_path = os.path.join(sub_folder, final_filename)
            try:
                self.doc.save(save_path)
                print(f"  [💾] 已分发至: .../{safe_folder_name}/{final_filename}")
            except Exception as e:
                import time
                short_path = os.path.join(sub_folder, f"Res_{int(time.time())}{ext}")
                try:
                    self.doc.save(short_path)
                    print(f"  [💾] 已另存为: {short_path}")
                except:
                    pass

    def run(self):
        if not self.doc:
            return self._summary_result("pdf_error", error=self.pdf_error)

        print(f"正在处理: {self.filename}")

        auth_res = self.check_authors()
        if auth_res is None:
            return self._summary_result(
                "author_check_error",
                error="Author screening request failed; see console output.",
            )
        if not auth_res.get("passed"):
            return self._summary_result(
                "author_rejected",
                author_passed=False,
                target_author=auth_res.get("target_author_name", ""),
            )

        target_author = auth_res.get("target_author_name", "")
        print(f"  [👤] 正教授/Fellow达标: {target_author}")

        valid_hits_map = {}
        all_markers = []
        for my_title in self.my_titles:
            marker = self.find_citation_marker(my_title)
            if marker and self.evaluate_citation_quality(marker, my_title):
                print(f"    - 命中目标: {my_title[:15]}... -> {marker}")
                valid_hits_map[my_title] = marker
                all_markers.append(marker)

        if valid_hits_map:
            self.apply_all_highlights(target_author, all_markers)
            self.save_to_subfolders(valid_hits_map.keys())
            return self._summary_result(
                "matched",
                author_passed=True,
                target_author=target_author,
                matched_citations=list(valid_hits_map.keys()),
            )

        print("  [⚠️] 未找到有效引用")
        return self._summary_result(
            "no_valid_citation",
            author_passed=True,
            target_author=target_author,
        )


if __name__ == "__main__":
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    my_titles = []
    if os.path.exists(MY_PAPERS_DIR):
        for f in os.listdir(MY_PAPERS_DIR):
            if f.endswith(".pdf"):
                my_titles.append(os.path.splitext(f)[0])
    source_files = [f for f in os.listdir(SOURCE_DIR) if f.endswith(".pdf")]
    print(f"🚀 [正教授严格版] 启动")

    results = []
    for filename in source_files:
        path = os.path.join(SOURCE_DIR, filename)
        try:
            result = PaperProcessor(path, my_titles).run()
        except Exception as e:
            print(f"  [!] 处理失败: {filename}: {e}")
            result = {
                "paper_file": filename,
                "status": "processing_error",
                "author_passed": "",
                "target_author": "",
                "matched_citation_count": 0,
                "matched_citations": "",
                "error": str(e),
            }
        results.append(result)
        print("-" * 40)

    summary_path = write_summary_report(results)
    print(f"📊 筛选汇总报告已保存: {summary_path}")