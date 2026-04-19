import os
import re
import subprocess
from notion_client import Client

# ========== 1. 初始化配置 ==========
os.makedirs("notion_pages", exist_ok=True)

token = os.getenv("NOTION_TOKEN")
if not token:
    raise SystemExit("❌ 请在GitHub Secrets中配置NOTION_TOKEN！")

notion = Client(auth=token)

# 父页面ID（从Secrets读取）
PARENT_PAGE_IDS = [
    os.getenv("NOTION_PAGE_ID"),
    os.getenv("WEEKLY_PAGE_ID"),
    os.getenv("DESKTOP_PAGE_ID"),
    os.getenv("MONTHLY_PAGE_ID"),
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid]  # 过滤空值

visited_page_ids = set()  # 防止循环引用
page_id_to_title = {}    # 缓存页面ID→标题映射


# ========== 2. 工具函数 ==========
def safe_filename(title, page_id):
    """生成唯一文件名：标题 + 页面ID前8位，避免冲突"""
    safe = re.sub(r'[<>:"/\\|?*]', '_', title).strip()
    return f"notion_pages/{safe}_{page_id[:8]}.md"

def get_page_title(page_info):
    """提取Notion页面的标题"""
    title_prop = page_info.get("properties", {}).get("title", {})
    if isinstance(title_prop, dict) and title_prop.get("title", []):
        return title_prop["title"][0].get("plain_text", "未命名")
    return "未命名"

def parse_block_to_md(block):
    """将Notion块转换为Markdown格式（支持段落、标题、列表、表格）"""
    block_type = block["type"]
    rich_text = block[block_type].get("rich_text", [])
    content = "".join(t["text"]["content"] for t in rich_text)

    # 标题
    if block_type == "heading_1":
        return f"# {content}\n\n"
    elif block_type == "heading_2":
        return f"## {content}\n\n"
    elif block_type == "heading_3":
        return f"### {content}\n\n"
    # 列表
    elif block_type == "bulleted_list_item":
        return f"- {content}\n"
    elif block_type == "numbered_list_item":
        return f"1. {content}\n"
    # 待办事项
    elif block_type == "to_do":
        checked = "✅" if block[block_type].get("checked", False) else "⬜"
        return f"- {checked} {content}\n"
    # 表格
    elif block_type == "table":
        table_md = "|"
        header = True
        for row in block[block_type]["rows"]:
            cells = []
            for cell in row["cells"]:
                cell_text = "".join(t["text"]["content"] for t in cell)
                cells.append(cell_text)
            table_md += " | ".join(cells) + "|\n"
            if header:  # 第一行作为表头
                table_md += "|" + "|".join(["---"] * len(cells)) + "|\n"
                header = False
        return table_md + "\n"
    # 子页面（递归处理）
    elif block_type == "child_page":
        child_page_id = block["id"]
        if child_page_id in visited_page_ids:
            return ""
        visited_page_ids.add(child_page_id)
        child_content = traverse_page(child_page_id, depth=1)
        return f"\n## 🔗 子页面：{get_page_title(notion.pages.retrieve(page_id=child_page_id))}\n{child_content}\n"
    # 普通段落
    else:
        return f"{content}\n\n"

def traverse_page(page_id, depth=0):
    """递归遍历页面，生成Markdown内容"""
    if page_id in visited_page_ids:
        return ""
    visited_page_ids.add(page_id)

    try:
        page_info = notion.pages.retrieve(page_id=page_id)
        title = get_page_title(page_info)
        page_id_to_title[page_id] =tle ti
        print(f"{'  ' * depth}📄 {title} (ID: {page_id[:8]})")

        # 读取页面所有块
        blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
        md_content = f"# {title}\n\n"  # 标题

        for block in blocks:
            md_line = parse_block_to_md(block)
            md_content += md_line

        return md_content

    except Exception as e:
        print(f"{'  ' * depth}❌ 读取页面 {page_id[:8]} 失败: {str(e)[:100]}")
        return ""

def update_notion_from_md(md_path, page_id):
    """将MD文件内容同步回Notion页面（增量更新，不删除原有块）"""
    if not os.path.exists(md_path):
        print(f"❌ MD文件不存在: {md_path}")
        return

    with open(md_path, "r", encoding="utf-8") as f:
        md_content = f.read()

    # 解析MD为Notion块（简化版，支持标题、段落、列表、表格）
    blocks = []
    lines = md_content.split("\n")
    current_table = None
    table_rows = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # 标题
        if line.startswith("# "):
            blocks.append({
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": line[2:]}}]}
            })
        elif line.startswith("## "):
            blocks.append({
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": line[3:]}}]}
            })
        elif line.startswith("### "):
            blocks.append({
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": line[4:]}}]}
            })
        # 列表
        elif line.startswith("- "):
            is_todo = "✅" in line or "⬜" in line
            text = line.replace("- ✅ ", "").replace("- ⬜ ", "").replace("- ", "")
            if is_todo:
                checked = "✅" in line
                blocks.append({
                    "type": "to_do",
                    "to_do": {"rich_text": [{"type": "text", "text": {"content": text}}], "checked": checked}
                })
            else:
                blocks.append({
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text [{"type": "text":", "text": {"content": text}}]}
                })
        elif line.startswith("1. "):
            text = line[3:]
            blocks.append({
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })
        # 表格
        elif line.startswith("|") and "|" in line[1:]:
            if current_table is None:
                current_table = []
            cells = [c.strip() for c in line.split("|")[1:-1]]
            current_table.append(cells)
        elif line.startswith("|") and all(c == "-" for c in line[1:].replace("|", "")):
            continue  # 表格分隔线，跳过
        elif current_table is not None:
            # 表格结束，生成表格块
            table_md = "|" + "|".join(current_table[0]) + "|\n"
            table_md += "|" + "|".join(["---"] * len(current_table[0])) + "|\n"
            for row in current_table[1:]:
                table_md += "|" + "|".join(row) + "|\n"
            blocks.append({
                "type": "table",
                "table": {"rows": [{"cells": [[{"type": "text", "text": {"content": cell}}] for cell in row]} for row in current_table]}
            })
            current_table = None
        # 普通段落
        else:
            blocks.append({
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
            })

    # 增量更新：先删除旧块（保留子页面？不，子页面单独处理）
    try:
        old_blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
        for block in old_blocks:
            # 跳过子页面（child_page），避免误删
            if blocktype"] != "["child_page":
                notion.blocks.delete(block_id=block["id"])
        # 写入新块
        if blocks:
            notion.blocks.children.append(block_id=page_id, children=blocks)
        print(f"✅ 已将 {md_path} 同步到 Notion 页面 {page_id[:8]}")
    except Exception as e:
        print(f"❌ 反向同步失败 {md_path}: {str(e)[:100]}")


# ========== 3. 主流程 ==========
if __name__ == "__main__":
    print("🚀 开始双向同步（单文件覆盖 + 全内容支持）...")

    # 1. Notion → GitHub：递归同步所有页面到单文件
    for parent_id in PARENT_PAGE_IDS:
        traverse_page(parent_id)

    # 2. GitHub → Notion：反向同步（读取MD文件，更新Notion）
    for page_id in page_id_to_title:
        title = page_id_to_title[page_id]
        md_path = safe_filename(title, page_id)
        if os.path.exists(md_path):
            update_notion_from_md(md_path, page_id)

    # 3. Git提交（防冲突）
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        subprocess.run(["git", "add", "notion_pages/"], check=True)
        commit_result = subprocess.run(["git", "commit", "-m", "🔄 Auto-Sync: 覆盖更新内容"], capture_output=True, text=True)
        if "nothing to commit" in commit_result.stdout:
            print("🟢 无变更，跳过提交")
        else:
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ 已推送到仓库")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git错误: {e.stderr}")

    print(f"\n🎉 完成！共处理 {len(visited_page_ids)} 个页面")
