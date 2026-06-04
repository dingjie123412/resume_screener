import streamlit as st
import os
import json
import requests
import zipfile
import tempfile
import io
from docx import Document
from PyPDF2 import PdfReader
import pandas as pd
from typing import List, Dict, Any
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed

# 加载环境变量（优先使用 Streamlit Secrets，回退到 .env 文件）
load_dotenv(".env.resume")

# DeepSeek 配置（优先从 Streamlit Secrets 获取，回退到环境变量）
def get_secret(key: str, default: str = "") -> str:
    """获取配置值，优先从 Streamlit Secrets 获取"""
    try:
        # 检查 st.secrets 是否可用（Streamlit Cloud 环境）
        if hasattr(st, 'secrets') and st.secrets is not None:
            return st.secrets.get(key, os.getenv(key, default))
        else:
            return os.getenv(key, default)
    except Exception:
        # 本地运行时可能没有 secrets.toml，直接返回环境变量
        return os.getenv(key, default)

DEEPSEEK_API_KEY = get_secret("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = get_secret("DEEPSEEK_BASE_URL", "")
DEEPSEEK_MODEL = get_secret("DEEPSEEK_MODEL", "")

# 数据存储路径
JOB_DATA_PATH = "job_requirements.json"
RESUME_SCORES_PATH = "resume_scores.json"

def load_job_requirements() -> List[Dict[str, Any]]:
    """加载已保存的岗位需求"""
    if os.path.exists(JOB_DATA_PATH):
        try:
            with open(JOB_DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return []
    return []

def save_job_requirements(jobs: List[Dict[str, Any]]):
    """保存岗位需求"""
    with open(JOB_DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)

def load_resume_scores() -> Dict[str, List[Dict[str, Any]]]:
    """加载已保存的简历评分"""
    if os.path.exists(RESUME_SCORES_PATH):
        try:
            with open(RESUME_SCORES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_resume_scores(scores: Dict[str, List[Dict[str, Any]]]):
    """保存简历评分"""
    with open(RESUME_SCORES_PATH, "w", encoding="utf-8") as f:
        json.dump(scores, f, ensure_ascii=False, indent=2)

def extract_text_from_docx(file) -> str:
    """从docx文件提取文本"""
    doc = Document(file)
    return "\n".join([para.text for para in doc.paragraphs])

def extract_text_from_pdf(file) -> str:
    """从pdf文件提取文本"""
    reader = PdfReader(file)
    text = ""
    for page in reader.pages:
        text += page.extract_text() + "\n"
    return text

def extract_text_from_file(file) -> str:
    """根据文件类型提取文本"""
    file_name = file.name
    if file_name.endswith(".docx"):
        return extract_text_from_docx(file)
    elif file_name.endswith(".pdf"):
        return extract_text_from_pdf(file)
    elif file_name.endswith(".txt"):
        return file.read().decode("utf-8")
    else:
        return ""

def extract_files_from_zip(zip_file) -> List[tuple]:
    """从ZIP文件中提取所有支持的简历文件，解决中文文件名乱码问题"""
    extracted_files = []
    
    try:
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            # 获取ZIP文件中的所有文件名
            file_list = zip_ref.namelist()
            
            for file_name in file_list:
                # 修复中文文件名乱码问题
                try:
                    # 尝试使用GBK解码（Windows常见编码）
                    decoded_name = file_name.encode('cp437').decode('gbk')
                except:
                    try:
                        # 尝试使用utf-8解码
                        decoded_name = file_name.encode('utf-8').decode('utf-8')
                    except:
                        # 保留原始文件名
                        decoded_name = file_name
                
                # 跳过目录
                if decoded_name.endswith('/') or decoded_name.endswith('\\'):
                    continue
                
                # 只处理支持的文件类型
                if not decoded_name.lower().endswith(('.docx', '.pdf', '.txt')):
                    continue
                
                # 从ZIP中直接读取文件内容
                with zip_ref.open(file_name) as f:
                    content = f.read()
                
                # 根据文件类型提取文本
                file_obj = io.BytesIO(content)
                file_obj.name = decoded_name
                
                text = extract_text_from_file(file_obj)
                if text.strip():
                    extracted_files.append((decoded_name, text))
    
    except Exception as e:
        st.error(f"解压文件失败: {str(e)}")
        return []
    
    return extracted_files

def call_deepseek(prompt: str, temperature: float = 0.1, api_key: str = "", base_url: str = "", model: str = "") -> str:
    """调用 DeepSeek API"""
    # 使用传入的参数，如果为空则使用全局默认值
    current_api_key = api_key if api_key else DEEPSEEK_API_KEY
    current_base_url = base_url if base_url else DEEPSEEK_BASE_URL
    current_model = model if model else DEEPSEEK_MODEL
    
    headers = {
        "Authorization": f"Bearer {current_api_key}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": current_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature
    }
    
    try:
        response = requests.post(
            f"{current_base_url}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120
        )
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        st.error(f"调用 DeepSeek API 失败: {str(e)}")
        return ""

def get_default_score(reason: str) -> Dict[str, Any]:
    """返回默认评分"""
    return {
        "total_score": 0,
        "skill_score": 0,
        "experience_score": 0,
        "education_score": 0,
        "quality_score": 0,
        "skill_reason": reason,
        "experience_reason": reason,
        "education_reason": reason,
        "quality_reason": reason,
        "summary": f"评分失败：{reason}"
    }

def clean_json_response(response: str) -> str:
    """清理API返回的JSON字符串"""
    import re
    
    # 1. 去除首尾空白
    cleaned = response.strip()
    
    # 2. 移除markdown代码块
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    
    # 3. 移除"json"前缀
    if cleaned.lower().startswith("json"):
        cleaned = cleaned[4:].lstrip()
    
    # 4. 移除引号包裹
    if cleaned.startswith('"') and cleaned.endswith('"'):
        cleaned = cleaned[1:-1]
    
    # 5. 关键：移除所有控制字符（保留换行和制表符）
    # 但JSON中不能有未转义的换行，所以把换行和制表符也移除或转义
    cleaned = re.sub(r'[\x00-\x1F\x7F]', '', cleaned)
    
    # 6. 处理特殊情况：\N 等无效转义
    cleaned = re.sub(r'\\(?![\\"\/bfnrtu])', '\\\\', cleaned)
    
    # 7. 找到JSON边界
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start != -1 and end != -1 and start < end:
        cleaned = cleaned[start:end+1]
    
    return cleaned

def score_resume(job_requirement: str, resume_text: str, api_key: str = "", base_url: str = "", model: str = "") -> Dict[str, Any]:
    """使用 DeepSeek 对简历进行评分"""
    
    if not resume_text or len(resume_text.strip()) < 10:
        return get_default_score("简历内容为空或无法读取")
    
    # 限制简历长度，避免超token
    resume_text = resume_text[:4000]
    
    prompt = f"""你是一个专业的人力资源专家，请根据以下岗位需求对候选人的简历进行评分。

【岗位需求】
{job_requirement}

【候选人简历】
{resume_text}

【评分要求】
1. 请从以下几个维度进行评估：
   - 专业技能匹配度（0-30分）
   - 工作经验匹配度（0-30分）
   - 学历背景匹配度（0-20分）
   - 综合素质（0-20分）
   
2. 总分 = 专业技能 + 工作经验 + 学历背景 + 综合素质

3. 请提供详细的评分理由

【输出格式】
请只输出一个JSON对象，格式如下：
{{"total_score": 85, "skill_score": 25, "experience_score": 25, "education_score": 18, "quality_score": 17, "skill_reason": "评分理由", "experience_reason": "评分理由", "education_reason": "评分理由", "quality_reason": "评分理由", "summary": "总体评价"}}

【重要】不要输出任何其他内容，只输出JSON。所有字符串中不要包含换行符。"""
    
    response = call_deepseek(prompt, temperature=0.0, api_key=api_key, base_url=base_url, model=model)
    
    if not response or not response.strip():
        return get_default_score("API返回为空")
    
    # 清理响应
    cleaned_response = clean_json_response(response)
    
    try:
        result = json.loads(cleaned_response)
        # 验证必要字段
        required_fields = ['total_score', 'skill_score', 'experience_score', 'education_score', 'quality_score']
        for field in required_fields:
            if field not in result:
                result[field] = 0
        return result
    except json.JSONDecodeError as e:
        st.warning(f"JSON解析失败: {str(e)}")
        st.info(f"API返回内容: {response[:200]}...")
        return get_default_score(f"解析失败: {str(e)}")
    except Exception as e:
        return get_default_score(f"处理失败: {str(e)}")

def batch_score_resumes(job_requirement: str, resume_list: List[tuple], api_key: str, base_url: str, model: str, max_workers: int = 5, progress_callback=None) -> List[Dict]:
    """
    并发批量评分
    resume_list: [(file_name, resume_text), ...]
    max_workers: 并发数，默认为5
    """
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {}
        for file_name, resume_text in resume_list:
            future = executor.submit(
                score_resume,
                job_requirement,
                resume_text,
                api_key,
                base_url,
                model
            )
            future_to_file[future] = file_name
        
        for future in as_completed(future_to_file):
            file_name = future_to_file[future]
            try:
                score_result = future.result(timeout=60)
                score_result["file_name"] = file_name
                results.append(score_result)
            except Exception as e:
                results.append({
                    "file_name": file_name,
                    "total_score": 0,
                    "skill_score": 0,
                    "experience_score": 0,
                    "education_score": 0,
                    "quality_score": 0,
                    "skill_reason": f"评分失败: {str(e)}",
                    "experience_reason": f"评分失败: {str(e)}",
                    "education_reason": f"评分失败: {str(e)}",
                    "quality_reason": f"评分失败: {str(e)}",
                    "summary": f"评分失败: {str(e)}"
                })
            
            if progress_callback:
                progress_callback()
    
    return sorted(results, key=lambda x: x["total_score"], reverse=True)

def save_env_config(api_key, base_url, model):
    """保存API配置到.env.resume文件"""
    config_content = f"""# DeepSeek API配置（简历筛选工具）
DEEPSEEK_API_KEY={api_key}
DEEPSEEK_BASE_URL={base_url}
DEEPSEEK_MODEL={model}
"""
    with open(".env.resume", "w", encoding="utf-8") as f:
        f.write(config_content)

def get_current_api_config():
    """获取当前使用的API配置"""
    return {
        "api_key": st.session_state.get("api_key", DEEPSEEK_API_KEY),
        "base_url": st.session_state.get("base_url", DEEPSEEK_BASE_URL),
        "model": st.session_state.get("model", DEEPSEEK_MODEL)
    }

def main():
    st.set_page_config(
        page_title="简历筛选工具",
        page_icon="📄",
        layout="wide"
    )
    
   # st.title("📄 简历筛选工具")
   # st.markdown("---")
    
    # 加载数据
    jobs = load_job_requirements()
    all_scores = load_resume_scores()
    
    # 初始化session state
    if "api_key" not in st.session_state:
        st.session_state.api_key = DEEPSEEK_API_KEY
    if "base_url" not in st.session_state:
        st.session_state.base_url = DEEPSEEK_BASE_URL
    if "model" not in st.session_state:
        st.session_state.model = DEEPSEEK_MODEL
    if "max_workers" not in st.session_state:
        st.session_state.max_workers = 5
    
    menu_options = ["上传岗位需求", "筛选简历", "查看结果"]
    selected_menu = st.sidebar.selectbox("功能菜单", menu_options)
    # 侧边栏 - API配置
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ API配置")
    
    # API Key 显示脱敏版本（前4位 + 中间* + 后4位）
    def mask_api_key(key):
        if len(key) <= 8:
            return "*" * len(key)
        return key[:4] + "*" * (len(key) - 8) + key[-4:]
    
    # 如果已有API Key，显示脱敏版本；否则显示空
    displayed_key = mask_api_key(st.session_state.api_key) if st.session_state.api_key else ""
    
    # 可编辑的文本输入框显示脱敏的API Key
    new_key_input = st.sidebar.text_input(
        "API Key", 
        value=displayed_key, 
        placeholder="请输入DeepSeek API Key"
    )
    
    # 如果用户输入了新内容（不是脱敏格式），更新实际的API Key
    if new_key_input:
        # 如果输入的不是脱敏格式（不含*），认为是新的完整Key
        if "*" not in new_key_input:
            st.session_state.api_key = new_key_input
        # 如果输入的是空，清空API Key
    else:
        st.session_state.api_key = ""
    
    st.session_state.base_url = st.sidebar.text_input("API Base URL", value=st.session_state.base_url, placeholder="例如：https://api.deepseek.com")
    st.session_state.model = st.sidebar.text_input("模型名称", value=st.session_state.model, placeholder="例如：deepseek-v4-flash")
    
    if st.sidebar.button("保存配置"):
        if st.session_state.api_key and st.session_state.base_url and st.session_state.model:
            save_env_config(st.session_state.api_key, st.session_state.base_url, st.session_state.model)
            st.sidebar.success("配置已保存！")
        else:
            st.sidebar.warning("请填写完整的配置信息")
    
    # 并发数配置
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚡ 并发设置")
    st.session_state.max_workers = st.sidebar.slider(
        "简历处理并发数",
        min_value=1,
        max_value=10,
        value=5,
        step=1,
        help="并发数越高处理越快，但可能触发API限流。建议值为3-5。"
    )
    st.sidebar.info(f"当前并发数: {st.session_state.max_workers}")
    
    # 侧边栏导航
    #st.sidebar.markdown("---")

    
    if selected_menu == "上传岗位需求":
        st.subheader("上传岗位需求")
        
        # 添加Tab选项：新增岗位 和 管理岗位
        tab1, tab2 = st.tabs(["➕ 新增岗位", "📋 管理岗位"])
        
        with tab1:
            job_name = st.text_input("岗位名称", placeholder="例如：高级Python工程师")
            job_department = st.text_input("所属部门", placeholder="例如：技术部")
            job_description = st.text_area("岗位描述", height=200, placeholder="请详细描述岗位的职责和要求...")
            job_requirements = st.text_area("任职要求", height=200, placeholder="请列出具体的任职要求，包括技能、经验、学历等...")
            
            if st.button("保存岗位需求"):
                if job_name and job_description and job_requirements:
                    new_job = {
                        "id": len(jobs) + 1,
                        "name": job_name,
                        "department": job_department,
                        "description": job_description,
                        "requirements": job_requirements,
                        "created_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                    }
                    jobs.append(new_job)
                    save_job_requirements(jobs)
                    st.success(f"岗位「{job_name}」已保存！")
                else:
                    st.warning("请填写完整的岗位信息")
        
        with tab2:
            st.markdown("### 已上传岗位列表")
            
            if not jobs:
                st.info("暂无已上传的岗位需求")
            else:
                # 初始化编辑状态
                if "editing_job_id" not in st.session_state:
                    st.session_state.editing_job_id = None
                
                for job in jobs:
                    # 检查是否正在编辑此岗位
                    is_editing = st.session_state.editing_job_id == job["id"]
                    
                    if is_editing:
                        # 编辑模式
                        st.markdown(f"#### 编辑岗位: {job['name']}")
                        
                        edit_name = st.text_input("岗位名称", value=job["name"], key=f"edit_name_{job['id']}")
                        edit_department = st.text_input("所属部门", value=job["department"], key=f"edit_dept_{job['id']}")
                        edit_description = st.text_area("岗位描述", value=job["description"], height=150, key=f"edit_desc_{job['id']}")
                        edit_requirements = st.text_area("任职要求", value=job["requirements"], height=150, key=f"edit_req_{job['id']}")
                        
                        col1, col2 = st.columns(2)
                        with col1:
                            if st.button("保存修改", key=f"save_{job['id']}"):
                                job["name"] = edit_name
                                job["department"] = edit_department
                                job["description"] = edit_description
                                job["requirements"] = edit_requirements
                                job["updated_at"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
                                save_job_requirements(jobs)
                                st.session_state.editing_job_id = None
                                st.success("修改已保存！")
                                st.rerun()
                        with col2:
                            if st.button("取消编辑", key=f"cancel_{job['id']}"):
                                st.session_state.editing_job_id = None
                                st.rerun()
                    else:
                        # 显示模式
                        with st.expander(f"📌 {job['name']} (ID: {job['id']})"):
                            col1, col2, col3 = st.columns([1, 1, 2])
                            with col1:
                                st.markdown("**部门**:")
                            with col2:
                                st.markdown(job['department'])
                            with col3:
                                st.markdown(f"**创建时间**: {job['created_at']}")
                            
                            st.markdown("---")
                            st.markdown("**岗位描述**:")
                            st.markdown(job['description'])
                            
                            st.markdown("---")
                            st.markdown("**任职要求**:")
                            st.markdown(job['requirements'])
                            
                            col_edit, col_delete = st.columns(2)
                            with col_edit:
                                if st.button("编辑", key=f"edit_{job['id']}"):
                                    st.session_state.editing_job_id = job["id"]
                                    st.rerun()
                            with col_delete:
                                if st.button("删除", key=f"delete_{job['id']}"):
                                    jobs.remove(job)
                                    save_job_requirements(jobs)
                                    st.success(f"岗位「{job['name']}」已删除！")
                                    st.rerun()
    
    elif selected_menu == "筛选简历":
        st.subheader("筛选简历")
        
        if not jobs:
            st.warning("请先上传岗位需求")
            return
        
        # 选择岗位
        job_options = [f"{job['id']}. {job['name']}" for job in jobs]
        selected_job_str = st.selectbox("选择岗位", job_options)
        selected_job = jobs[int(selected_job_str.split(".")[0]) - 1]
        
        st.markdown(f"### 岗位信息")
        st.markdown(f"**部门**: {selected_job['department']}")
        st.markdown(f"**岗位描述**: {selected_job['description']}")
        st.markdown(f"**任职要求**: {selected_job['requirements']}")
        
        st.markdown("---")
        
        # 上传简历文件夹
        st.markdown("### 上传简历")
        
        # 添加Tab选项：单文件上传 和 批量上传
        tab1, tab2 = st.tabs(["📄 单文件上传", "📁 批量上传文件夹"])
        
        with tab1:
            uploaded_files = st.file_uploader(
                "选择简历文件（支持docx、pdf、txt格式）",
                type=["docx", "pdf", "txt"],
                accept_multiple_files=True,
                key="single_upload"
            )
            
            if uploaded_files:
                st.info(f"已选择 {len(uploaded_files)} 份简历")
                
                if st.button("开始评分", key="score_single"):
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    results = []
                    
                    # 先提取所有简历文本
                    resume_data = []
                    for file in uploaded_files:
                        resume_text = extract_text_from_file(file)
                        if resume_text.strip():
                            resume_data.append((file.name, resume_text))
                        else:
                            st.warning(f"无法读取 {file.name} 的内容，已跳过")
                    
                    if not resume_data:
                        st.error("没有可评分的简历")
                    else:
                        status_text.info(f"开始并发评分，共 {len(resume_data)} 份简历...")
                        
                        # 并发评分
                        completed = 0
                        def update_progress():
                            nonlocal completed
                            completed += 1
                            progress_bar.progress(completed / len(resume_data))
                            status_text.info(f"已完成: {completed}/{len(resume_data)}")
                        
                        results = batch_score_resumes(
                            selected_job['requirements'],
                            resume_data,
                            st.session_state.api_key,
                            st.session_state.base_url,
                            st.session_state.model,
                            st.session_state.max_workers,
                            update_progress
                        )
                        
                        status_text.empty()
                        
                        # 保存结果
                        job_key = f"job_{selected_job['id']}"
                        all_scores[job_key] = results
                        save_resume_scores(all_scores)
                        
                        st.success("评分完成！")
                        
                        # 显示排名
                        st.markdown("---")
                        st.info("""📊 评分参考：
- 90分以上：强烈推荐面试
- 75-90分：推荐面试
- 60-75分：可考虑
- 60分以下：不推荐
""")
                        
                        st.markdown("### 简历排名")
                        
                        for idx, result in enumerate(results, 1):
                            with st.expander(f"🏆 第{idx}名 - {result['file_name']} (得分: {result.get('total_score', 0)})"):
                                col1, col2 = st.columns(2)
                                with col1:
                                    st.markdown("**评分详情**")
                                    st.markdown(f"- 专业技能: {result.get('skill_score', 0)}/30")
                                    st.markdown(f"- 工作经验: {result.get('experience_score', 0)}/30")
                                    st.markdown(f"- 学历背景: {result.get('education_score', 0)}/20")
                                    st.markdown(f"- 综合素质: {result.get('quality_score', 0)}/20")
                                with col2:
                                    st.markdown("**评分理由**")
                                    st.markdown(f"📚 专业技能: {result.get('skill_reason', '未提供')}")
                                    st.markdown(f"💼 工作经验: {result.get('experience_reason', '未提供')}")
                                    st.markdown(f"🎓 学历背景: {result.get('education_reason', '未提供')}")
                                    st.markdown(f"🌟 综合素质: {result.get('quality_reason', '未提供')}")
                                st.markdown("---")
                                st.markdown(f"**总体评价**: {result.get('summary', '未提供')}")
        
        with tab2:
            st.info("💡 请上传包含简历的ZIP压缩包，系统将自动解压并评分所有简历")
            zip_file = st.file_uploader(
                "选择ZIP文件（包含docx、pdf、txt格式的简历）",
                type=["zip"],
                key="batch_upload"
            )
            
            if zip_file:
                st.info(f"已选择文件: {zip_file.name}")
                
                if st.button("开始批量评分", key="score_batch"):
                    with st.spinner("正在解压并分析简历..."):
                        # 提取ZIP中的所有简历
                        extracted_files = extract_files_from_zip(zip_file)
                        
                        if not extracted_files:
                            st.error("未在ZIP文件中找到支持的简历文件")
                        else:
                            st.info(f"找到 {len(extracted_files)} 份简历，开始并发评分...")
                            
                            progress_bar = st.progress(0)
                            status_text = st.empty()
                            
                            # 并发评分
                            completed = 0
                            def update_progress():
                                nonlocal completed
                                completed += 1
                                progress_bar.progress(completed / len(extracted_files))
                                status_text.info(f"已完成: {completed}/{len(extracted_files)}")
                            
                            results = batch_score_resumes(
                                selected_job['requirements'],
                                extracted_files,
                                st.session_state.api_key,
                                st.session_state.base_url,
                                st.session_state.model,
                                st.session_state.max_workers,
                                update_progress
                            )
                            
                            status_text.empty()
                            
                            # 保存结果
                            job_key = f"job_{selected_job['id']}"
                            all_scores[job_key] = results
                            save_resume_scores(all_scores)
                            
                            st.success("批量评分完成！")
                            
                            # 显示排名
                            st.markdown("---")
                            st.info("""📊 评分参考：
- 90分以上：强烈推荐面试
- 75-90分：推荐面试
- 60-75分：可考虑
- 60分以下：不推荐
""")
                            
                            st.markdown("### 简历排名")
                            
                            for idx, result in enumerate(results, 1):
                                with st.expander(f"🏆 第{idx}名 - {result['file_name']} (得分: {result.get('total_score', 0)})"):
                                    col1, col2 = st.columns(2)
                                    with col1:
                                        st.markdown("**评分详情**")
                                        st.markdown(f"- 专业技能: {result.get('skill_score', 0)}/30")
                                        st.markdown(f"- 工作经验: {result.get('experience_score', 0)}/30")
                                        st.markdown(f"- 学历背景: {result.get('education_score', 0)}/20")
                                        st.markdown(f"- 综合素质: {result.get('quality_score', 0)}/20")
                                    with col2:
                                        st.markdown("**评分理由**")
                                        st.markdown(f"📚 专业技能: {result.get('skill_reason', '未提供')}")
                                        st.markdown(f"💼 工作经验: {result.get('experience_reason', '未提供')}")
                                        st.markdown(f"🎓 学历背景: {result.get('education_reason', '未提供')}")
                                        st.markdown(f"🌟 综合素质: {result.get('quality_reason', '未提供')}")
                                    st.markdown("---")
                                    st.markdown(f"**总体评价**: {result.get('summary', '未提供')}")
    
    elif selected_menu == "查看结果":
        st.subheader("查看历史评分结果")
        
        if not all_scores:
            st.warning("暂无评分结果")
            return
        
        # 选择岗位查看结果
        job_keys = list(all_scores.keys())
        job_names = []
        for key in job_keys:
            job_id = int(key.split("_")[1])
            job = next((j for j in jobs if j["id"] == job_id), None)
            if job:
                job_names.append(f"{job['id']}. {job['name']}")
            else:
                job_names.append(key)
        
        selected_job_result = st.selectbox("选择岗位", job_names)
        
        # 找到对应的key
        selected_key = None
        for key in job_keys:
            job_id = int(key.split("_")[1])
            job = next((j for j in jobs if j["id"] == job_id), None)
            if job and f"{job['id']}. {job['name']}" == selected_job_result:
                selected_key = key
                break
        
        if selected_key and selected_key in all_scores:
            results = all_scores[selected_key]
            
            # 显示排名
            st.markdown("### 简历排名")
            for idx, result in enumerate(results, 1):
                with st.expander(f"🏆 第{idx}名 - {result['file_name']} (得分: {result.get('total_score', 0)})"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**评分详情**")
                        st.markdown(f"- 专业技能: {result.get('skill_score', 0)}/30")
                        st.markdown(f"- 工作经验: {result.get('experience_score', 0)}/30")
                        st.markdown(f"- 学历背景: {result.get('education_score', 0)}/20")
                        st.markdown(f"- 综合素质: {result.get('quality_score', 0)}/20")
                    with col2:
                        st.markdown("**评分理由**")
                        st.markdown(f"📚 专业技能: {result.get('skill_reason', '未提供')}")
                        st.markdown(f"💼 工作经验: {result.get('experience_reason', '未提供')}")
                        st.markdown(f"🎓 学历背景: {result.get('education_reason', '未提供')}")
                        st.markdown(f"🌟 综合素质: {result.get('quality_reason', '未提供')}")
                    st.markdown("---")
                    st.markdown(f"**总体评价**: {result.get('summary', '未提供')}")
            
            # 导出功能
            if st.button("导出评分结果"):
                df = pd.DataFrame(results)
                csv = df.to_csv(index=False, encoding="utf-8-sig")
                st.download_button(
                    label="下载CSV文件",
                    data=csv,
                    file_name=f"resume_scores_{selected_job_result}.csv",
                    mime="text/csv"
                )

if __name__ == "__main__":
    main()
