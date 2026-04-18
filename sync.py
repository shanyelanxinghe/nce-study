import os
import re
import subprocess
from notion_client import Client
from notion_client.helpers import collect_paginated_api
from md2notion.client import NotionClient as MD2NotionClient  # 新增：MD转Notion工具

# ====================== 1. 初始化客户端 ======================
# Notion 客户端（读取/更新 Notion）
notion_token = os.getenv("NOTION_TOKEN")
if not notion_token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=notion_token)

# MD2Notion 客户端（将 MD 转换回 Notion）
md2notion_token = os.getenv("NOTION_TOKEN")  # 复用同一份 Token
md2notion = MD2NotionClient(token=md2notion_token)

# GitHub 仓库信息
repo_owner = "shanyelanxinghe"  # 你的 GitHub 用户名
repo_name = "nce-study"         # 你的仓库名

# ====================== 2. 父页面 ID（对应你的 Secrets） ======================
PARENT_PAGE_IDS = [
    os.getenv("NOTION_PAGE_ID"),
    os.getenv("WEEKLY_PAGE_ID"),
    os.getenv("DESKTOP_PAGE_ID"),
    os.getenv("MONTHLY_PAGE_ID"),
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid and len(pid) == 32]

visited_page_ids = set()  # 记录已处理的页面，避免重复

# ====================== 3. 工具函数 ======================
def safe_filename(title, max_len=60):
    """生成安全的文件名（替换特殊字符，截断长度）"""
    safe = re.sub(r'[<>:"/\\|?*]', '_', title)
    safe = re.sub(r'\s+', '_', safe).strip('_')
    return safe[:max_len]

def get_page_title(page_info):
    """从 Notion 页面信息中提取标题"""
    title_prop = page_info.get("properties", {}).get("title", {})
    if title_prop and title_prop.get("title"):
        return title_prop["title"][0]["plain_text"]
    return "Untitled"

def get_page_content_blocks(page_id):
    """递归获取 Notion 页面的所有内容块（含子页）"""
    blocks = []
    for block in collect_paginated_api(notion.blocks.children.list, block_id=page_id):
        block_type = block["type"]
        block_data = block[block_type]
        
        # 处理子页（递归获取子页内容）
        if block_type == "child_page":
            child_title = block_data.get("title", "Untitled")
            child_blocks = get_page_content_blocks(block["id"])  # 递归
            blocks.append({
                "type": "child_page",
                "title": child_title,
                "blocks": child_blocks
            })
        else:
            # 处理普通块（文本、列表、标题等）
            blocks.append({
                "type": block_type,
                "content": block_data.get("rich_text", []) if "rich_text" in block_data else []
            })
    return blocks

def blocks_to_md(blocks, level=1):
    """将 Notion 块结构转换为 Markdown 文本（支持标题、列表、段落、子页）"""
    md_lines = []
    for block in blocks:
        if block["type"] == "child_page":
            # 子页：用标题+递归内容（子页作为独立 MD 文件？或嵌入？这里选择嵌入）
            child_title = block["title"]
            child_md = blocks_to_md(block["blocks"], level + 1)
            md_lines.append(f"{'#' * level} {child_title}\n{child_md}")
        elif block["type"] in ["heading_1", "heading_2", "heading_3"]:
            # 标题
            level_map = {"heading_1": 1, "heading_2": 2, "heading_3": 3}
            md_lines.append(f"{'#' * level_map[block['type']]} {''.join([t['plain_text'] for t in block['content']])}")
        elif block["type"] in ["paragraph", "bulleted_list_item", "numbered_list_item"]:
            # 段落/列表项
            text = "".join([t['plain_text'] for t in block['content']])
            if block["type"] == "bulleted_list_item":
                md_lines.append(f"- {text}")
            elif block["type"] == "numbered_list_item":
                md_lines.append(f"1. {text}")
            else:
                md_lines.append(text)
        elif block["type"] in ["code", "quote", "divider"]:
            # 代码块/引用/分割线（简化支持）
            text = "".join([t['plain_text'] for t in block['content']])
            if block["type"] == "code":
                md_lines.append(f"```\n{text}\n```")
            elif block["type"] == "quote":
                md_lines.append(f"> {text}")
            else:
                md_lines.append("---")
    return "\n\n".join(md_lines)

def md_to_blocks(md_content, page_id=None):
    """将 Markdown 文本转换为 Notion 块结构（用于反向同步）"""
    blocks = []
    lines = md_content.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue
        
        # 标题（# / ## / ###）
        if line.startswith("#"):
            level = line.count("#")
            title = line.lstrip("#").strip()
            blocks.append({
                "object": "block",
                "type": f"heading_{level}",
                f"heading_{level}": {
                    "rich_text": [{"type": "text", "text": {"content": title}}]
                }
            })
            i += 1
        # 无序列表（- / *）
        elif line.startswith(("- ", "* ")):
            text = line[2:].strip()
            blocks.append({
                "object": "block",
                "type": "bulleted_list_item",
                "bulleted_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            })
            i += 1
        # 有序列表（1. / 2.）
        elif re.match(r"^\d+\.\s", line):
            text = re.sub(r"^\d+\.\s", "", line).strip()
            blocks.append({
                "object": "block",
                "type": "numbered_list_item",
                "numbered_list_item": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            })
            i += 1
        # 代码块（```...```）
        elif line.startswith("```"):
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].startswith("```"):
                i += 1
            blocks.append({
                "object": "block",
                "type": "code",
                "code": {
                    "rich_text": [{"type": "text", "text": {"content": "\n".join(code)}}],
                    "language": "plaintext"  # 简化处理，可识别语言
                }
            })
        # 引用（> ...）
        elif line.startswith(">"):
            text = line.lstrip(">").strip()
            blocks.append({
                "object": "block",
                "type": "quote",
                "quote": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            })
            i += 1
        # 段落（其他内容）
        else:
            text = line
            # 合并后续空行或非特殊行
            j = i + 1
            while j < len(lines) and lines[j].strip() and not lines[j].startswith(("#", "-", "*", "1.", "`", ">")):
                text += " " + lines[j].strip()
                j += 1
            i = j
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": text}}]
                }
            })
    return blocks

# ====================== 4. Notion → GitHub 同步（生成/更新 MD 文件） ======================
def sync_notion_to_github():
    print("🔄 开始 Notion → GitHub 同步...")
    for parent_id in PARENT_PAGE_IDS:
        traverse_pages(parent_id)
    print("✅ Notion → GitHub 同步完成！")

def traverse_pages(page_id):
    if page_id in visited_page_ids:
        return
    visited_page_ids.add(page_id)
    
    # 获取页面信息（标题、内容块）
    page_info = notion.pages.retrieve(page_id=page_id)
    title = get_page_title(page_info)
    filename = safe_filename(title) + ".md"
    file_path = os.path.join("notion_pages", filename)
    
    # 获取页面所有内容块（含子页）
    content_blocks = get_page_content_blocks(page_id)
    md_content = blocks_to_md(content_blocks)
    
    # 写入 MD 文件（覆盖/创建）
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
    print(f"📄 已同步：{title} -> {file_path}")

# ====================== 5. GitHub → Notion 同步（解析 MD 更新 Notion） ======================
def sync_github_to_notion():
    print("🔄 开始 GitHub → Notion 同步...")
    # 1. 获取所有 MD 文件
    md_files = [f for f in os.listdir("notion_pages") if f.endswith(".md")]
    for md_file in md_files:
        file_path = os.path.join("notion_pages", md_file)
        with open(file_path, "r", encoding="utf-8") as f:
            md_content = f.read()
        
        # 2. 从文件名提取页面标题（假设文件名=页面标题）
        page_title = os.path.splitext(md_file)[0].replace("_", " ")
        
        # 3. 查找对应的 Notion 页面（通过标题匹配）
        target_page_id = None
        for parent_id in PARENT_PAGE_IDS:
            # 递归查找页面（简化：先查父页，再查子页）
            pages = collect_paginated_api(notion.search, query=page_title)
            for page in pages:
                if page["properties"].get("title", {}).get("title", [{}])[0].get("plain_text") == page_title:
                    target_page_id = page["id"]
                    break
            if target_page_id:
                break
        
        if not target_page_id:
            print(f"⚠️ 未找到 Notion 页面：{page_title}，跳过更新！")
            continue
        
        # 4. 将 MD 转换为 Notion 块
        new_blocks = md_to_blocks(md_content)
        
        # 5. 清空原页面的块（保留页面属性，只更新内容）
        existing_blocks = collect_paginated_api(notion.blocks.children.list, block_id=target_page_id)
        for block in existing_blocks:
            notion.blocks.delete(block_id=block["id"])
        
        # 6. 批量写入新块
        for block in new_blocks:
            notion.blocks.children.append(block_id=target_page_id, children=[block])
        print(f"✅ 已更新 Notion 页面：{page_title} -> {target_page_id}")
    print("✅ GitHub → Notion 同步完成！")

# ===================
