# 简历筛选工具

一个基于 Streamlit 和 DeepSeek 的简历自动筛选评分工具，帮助 HR 部门快速筛选应聘者简历。

## 功能特性

- 📝 **岗位需求管理**：上传、编辑、删除岗位招聘需求
- 📄 **简历上传**：支持单文件和批量文件夹上传
- 🤖 **智能评分**：使用 DeepSeek 大模型自动评分
- 📊 **排名展示**：按评分排序展示应聘者排名
- ⚡ **并发处理**：支持可配置的并发数，提升处理速度
- 📤 **结果导出**：支持导出评分结果为 CSV

## 评分维度（总分100分）

- 专业技能匹配度（0-30分）
- 工作经验匹配度（0-30分）
- 学历背景匹配度（0-20分）
- 综合素质（0-20分）

## 技术栈

- Python 3.8+
- Streamlit 1.30+
- DeepSeek API
- python-docx（Word文档处理）
- PyPDF2（PDF文档处理）

## 本地运行

```bash
# 安装依赖
pip install -r requirements.txt

# 运行应用
streamlit run resume_screening.py
```

## 配置说明

在侧边栏配置 DeepSeek API：
- API Key：您的 DeepSeek API 密钥
- API Base URL：`https://api.deepseek.com`
- 模型名称：`deepseek-v4-flash`

## 部署到 Streamlit Community Cloud

1. 将代码上传到 GitHub 仓库
2. 访问 [share.streamlit.io](https://share.streamlit.io/)
3. 连接您的 GitHub 仓库
4. 选择主分支和 `resume_screening.py` 文件
5. 在 Secrets 中添加环境变量：
   - `DEEPSEEK_API_KEY`
   - `DEEPSEEK_BASE_URL`
   - `DEEPSEEK_MODEL`

## 使用流程

1. 上传岗位需求
2. 选择岗位并上传简历
3. 点击开始评分
4. 查看排名结果