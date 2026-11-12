一个初步论文筛选脚本，指定论文目录后，工作内容包括调用一个LLM API 筛选论文中符合要求的目标作者，高亮作者，参考文献位置中目标文献编号以及正文中的被引用文献。该脚本谨作初步筛选。

运行前请执行 `pip install -r requirements.txt` 安装项目依赖。

## 筛选结果汇总

每次运行 `process.py` 后，程序会在 `output_papers/summary.csv` 自动生成本次批量筛选的汇总报告。报告按 PDF 文件记录处理状态、作者筛选结果、识别出的目标作者、通过质量判断的引用数量及标题，以及可用的错误信息。

常见状态包括：

- `matched`：作者筛选通过，且找到至少一条有效引用。
- `author_rejected`：作者筛选未通过。
- `no_valid_citation`：作者筛选通过，但没有找到有效引用。
- `author_check_error`：作者筛选 API 请求失败。
- `pdf_error`：PDF 无法打开。
- `processing_error`：处理该 PDF 时发生未捕获的异常。

CSV 使用 UTF-8 with BOM 编码，方便使用 Excel 打开。原有的高亮 PDF 输出方式保持不变。
