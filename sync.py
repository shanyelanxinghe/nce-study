import os
import re
from notion_client import Client

# ====================== 1. 初始化 & 目录创建 ======================
os.makedirs("notion_pages", exist_ok=True)

token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)

# ====================== 2. 6 个父页面 ID（从环境变量读） ======================
PARENT_PAGE_IDS = [
    os.getenv("NCE_PAGE_ID"),
    os.getenv("WEEKLY_PAGE_ID"),
    os.getenv("DESKTOP_PAGE_ID"),
    os.getenv("MONTHLY_PAGE_ID"),
    os.getenv("INCOME_PAGE_ID"),
    os.getenv("EXPENSES_PAGE_ID"),
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid and len(pid) == 32]  # 过滤空/非法ID

visited_page_ids = set()

# ====================== 3. 工具函数：安全文件名 & 提取标题 ======================
def safe_filename(title, max_len=60):
    """把标题转成安全文件名（去特殊字符、截断）"""
    safe = re.sub(r'[<>:"/\\|?*]', '_', title)  # 替换所有非法字符
    safe = re.sub(r'\s+', '_', safe).strip('_.')
    return safe[:max_len] if len(safe) > max_len else safe

def get_page_title(page_info):
    """优先从 properties.title 取标题，否则取首段文本"""
    title_prop = page_info.get("properties", {}).get("title", {})
    if isinstance(title_prop, dict) and title_prop.get("title", []):
        return title_prop["title"][0].get("plain_text", "未命名")
    # 兜底：取首段文本
    blocks = notion.blocks.children.list(block_id=page_info["id"]).get("results", [])
    for b in blocks:
        if b["type"] == "paragraph" and b["paragraph"].get("rich_text"):
            return b["paragraph"]["rich_text"][0]["text"]["content"]
    return "未命名"

# ====================== 4. 核心：单个页面双向同步 ======================
def sync_page_content(page_id, page_title):
    if page_id in visited_page_ids:
        return
    visited_page_ids.add(page_id)

    # 1. 读 Notion 内容（段落 + 标题）
    blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
    notion_text = f"# {page_title}\n\n"
    for b in blocks:
        if b["type"] in ["paragraph", "heading_1", "heading_2"]:
            rich_text = b[b["type"]].get("rich_text", [])
            if rich_text:
                line = rich_text[0]["text"]["content"]
                if b["type"] == "heading_1": line = f"# {line}"
                if b["type"] == "heading_2": line = f"## {line}"
                notion_text += line + "\n\n"

    # 2. 写/读 GitHub MD（文件名带 ID 防冲突）
    safe_title = safe_filename(page_title)
    filename = f"notion_pages/{safe_title}_{page_id[:8]}.md"
    github_md = ""
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            github_md = f.read()

    # 3. 双向判断（按长度简化，也可改哈希比对）
    if len(github_md) > len(notion_text):  # GitHub 更新 → 写回 Notion
        # 先清空 Notion 页所有块（避免重复）
        for b in blocks:
            notion.blocks.delete(block_id=b["id"])
        # 写入 GitHub 内容（分段插入更稳）
        lines = github_md.split('\n')
        batch = []
        for line in lines:
            if line.strip():
                batch.append({
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
                })
        if batch:
            notion.blocks.children.append(block_id=page_id, children=batch)
        print(f"📥 [{page_title}] GitHub → Notion（已覆盖）")
    else:  # Notion 更新 → 写 GitHub
        with open(filename, "w", encoding="utf-8") as f:
            f.write(notion_text)
        print(f"📤 [{page_title}] Notion → GitHub → {filename}")

# ====================== 5. 递归遍历子页 ======================
def traverse_pages(start_page_id, depth=0):
    if start_page_id in visited_page_ids:
        return
    visited_page_ids.add(start_page_id)
    try:
        page_info = notion.pages.retrieve(page_id=start_page_id)
        title = get_page_title(page_info)
        print(f"{'  '*depth}📄 {title} ({start_page_id[:8]})")
        sync_page_content(start_page_id, title)
        # 递归子页
        children = notion.blocks.children.list(block_id=start_page_id).get("results", [])
        for child in children:
            if child["type"] == "child_page":
                traverse_pages(child["id"], depth + 1)
    except Exception as e:
        print(f"{'  '*depth}❌ {start_page_id[:8]} 失败: {str(e)[:100]}")

# ====================== 6. 主入口 ======================
if __name__ == "__main__":
    print("🚀 开始多父页面递归同步（防重/安全文件名/双向）...")
    if not PARENT_PAGE_IDS:
        print("❌ 未配置有效的父页面 ID，请检查 GitHub Secrets")
        exit(1)
    for i, pid in enumerate(PARENT_PAGE_IDS):
        print(f"\n===== 同步父页面 {i+1}/{len(PARENT_PAGE_IDS)} (ID: {pid[:8]}) =====")
        traverse_pages(pid)
    print(f"\n✅ 完成！共处理 {len(visited_page_ids)} 个唯一页面")
