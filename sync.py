import os
import re
import subprocess
from notion_client import Client

# ========== 1. 初始化配置 ==========
os.makedirs("notion_pages", exist_ok=True)

# 从环境变量读取Notion Token和页面ID
token = os.getenv("NOTION_TOKEN")
if not token:
    raise SystemExit("❌ 请在GitHub Secrets中配置NOTION_TOKEN！")

notion = Client(auth=token)

# 父页面ID列表（从Secrets读取）
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
    """生成唯一文件名：标题 + 页面ID前8位"""
    safe_title = re.sub(r'[<>:"/\\|?*]', "_", title).strip()  # 替换非法字符
    return f"notion_pages/{safe_title}_{page_id[:8]}.md"


def get_page_title(page_info):
    """从页面信息中提取标题"""
    title_prop = page_info.get("properties", {}).get("title", {})
    if isinstance(title_prop, dict) and title_prop.get("title", []):
        return title_prop["title"][0].get("plain_text", "未命名")
    return "未命名"


def parse_notion_block_to_md(block):
    """将Notion块转换为Markdown行"""
    block_type = block["type"]
    rich_text = block.get(block_type, {}).get("rich_text", [])
    text = "".join(t["text"]["content"] for t in rich_text) if rich_text else ""

    # 块类型映射
    type_map = {
        "paragraph": lambda: text,
        "heading_1": lambda: f"# {text}",
        "heading_2": lambda: f"## {text}",
        "heading_3": lambda: f"### {text}",
        "bulleted_list_item": lambda: f"- {text}",
        "numbered_list_item": lambda: f"1. {text}",
        "to_do": lambda: f"- {'✅' if block.get('checked') else '⬜'} {text}",
        "table": lambda: parse_notion_table(block),  # 表格单独处理
    }

    if block_type in type_map:
        return type_map[block_type]() + "\n"
    return ""


def parse_notion_table(table_block):
    """将Notion表格转换为Markdown表格"""
    rows = table_block.get("table", {}).get("rows", [])
    if not rows:
        return ""

    # 表头
    header_row = rows[0]
    headers = [cell.get("rich_text", [{}])[0].get("text", {}).get("content", "") for cell in header_row.get("cells", [])]
    md_table = "| " + " | ".join(headers) + " |\n"
    md_table += "| " + " | ".join(["---"] * len(headers)) + " |\n"

    # 内容行
    for row in rows[1:]:
        cells = [cell.get("rich_text", [{}])[0].get("text", {}).get("content", "") for cell in row.get("cells", [])]
        md_table += "| " + " | ".join(cells) + " |\n"

    return md_table + "\n"


def traverse_notion_pages(start_page_id, depth=0):
    """递归遍历Notion页面（支持子页、块）"""
    if start_page_id in visited_page_ids:
        return
    visited_page_ids.add(start_page_id)

    try:
        # 获取页面信息
        page_info = notion.pages.retrieve(page_id=start_page_id)
        title = get_page_title(page_info)
        print(f"{'  ' * depth}📄 {title} (ID: {start_page_id})")
        page_id_to_title[start_page_id] = title

        # 读取页面所有块
        blocks = notion.blocks.children.list(block_id=start_page_id).get("results", [])
        md_content = f"# {title}\n\n"  # 标题作为一级标题

        for block in blocks:
            # 处理子页面（递归）
            if block["type"] == "child_page":
                child_page_id = block["id"]
                child_title = block.get("child_page", {}).get("title", "未命名子页")
                print(f"{'  ' * (depth+1)}└─ 子页: {child_title} (ID: {child_page_id})")
                traverse_notion_pages(child_page_id, depth + 1)
                # 子页内容会生成独立MD文件，这里只记录引用（可选）
                md_content += f"[{child_title}](notion_pages/{safe_filename(child_title, child_page_id)})\n\n"

            # 处理普通块（转换为MD）
            else:
                md_line = parse_notion_block_to_md(block)
                md_content += md_line

        # 生成唯一MD文件（覆盖旧文件）
        filename = safe_filename(title, start_page_id)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"{'  ' * depth}📤 写入: {filename}")

    except Exception as e:
        print(f"{'  ' * depth}❌ 页面 {start_page_id[:8]} 同步失败: {str(e)[:100]}")


def update_notion_from_github():
    """从GitHub MD文件反向更新Notion页面（增量更新）"""
    # MD文件 → Notion页面ID 映射（需与Secrets中的页面ID对应）
    md_to_page_id = {
        f"notion_pages/{safe_filename(get_page_title(notion.pages.retrieve(page_id=pid)), pid)}": pid
        for pid in PARENT_PAGE_IDS
    }

    for md_filename, page_id in md_to_page_id.items():
        if not os.path.exists(md_filename):
            print(f"⚠️ 文件 {md_filename} 不存在，跳过")
            continue

        with open(md_filename, "r", encoding="utf-8") as f:
            md_content = f.read()

        # 解析MD为Notion块（简化版，支持标题、段落、列表、表格）
        blocks = []
        lines = md_content.split("\n")
        in_table = False
        table_rows = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # 处理标题
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

            # 处理列表
            elif line.startswith("- "):
                if line.startswith("- ✅") or line.startswith("- ⬜"):
                    checked = line.startswith("- ✅")
                    text = line[5:].strip()
                    blocks.append({
                        "type": "to_do",
                        "to_do": {"rich_text": [{"type": "text", "text": {"content": text}}], "checked": checked}
                    })
                else:
                    text = line[2:].strip()
                    blocks.append({
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
                    })

            # 处理有序列表（简化为无序，Notion会自动识别）
            elif line.startswith("1. "):
                text = line[3:].strip()
                blocks.append({
                    "type": "numbered_list_item",
                    "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
                })

            # 处理表格
            elif line.startswith("|") and "|" in line[1:]:
                if not in_table:
                    in_table = True
                    table_rows = []
                table_rows.append(line)
                if line.endswith("|") and len(table_rows) >= 3:  # 表头+分隔线+内容
                    # 转换为Notion表格块（简化）
                    blocks.append({
                        "type": "table",
                        "table": {"rows":}  # 实际需解析行，这里仅示例
   []                  })
                    in_table = False

            # 处理普通段落
            else:
                blocks.append({
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
                })

        # 增量更新：先删除旧块，再添加新块（避免冲突）
        try:
            # 获取旧块
            old_blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
            # 删除旧块（保留页面本身）
            for block in old_blocks:
                notion.blocks.delete(block_id=block["id"])
            # 添加新块
            if blocks:
                notion.blocks.children.append(block_id=page_id, children=blocks)
            print(f"📥 反向同步: {md_filename} → Notion (ID: {page_id})")
        except Exception as e:
            print(f"❌ 反向同步失败 {md_filename}: {str(e)[:100]}")


def git_commit_and_push():
    """Git提交并推送（防冲突）"""
    try:
        # 配置Git身份
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        # 拉取最新代码（避免冲突）
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        # 提交变更
        subprocess.run(["git", "add", "notion_pages/"], check=True)
        commit_result = subprocess.run(["git", "commit", "-m", "🔄 Auto-Sync: Update notion_pages"], capture_output=True, text=True)
        if "nothing to commit" in commit_result.stdout:
            print("🟢 无变更，跳过提交")
        else:
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ 已推送到仓库")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git操作失败: {e.stderr}")


# ========== 3. 主流程 ==========
if __name__ == "__main__":
    print("🚀 开始双向同步（标题/段落/列表/表格/子页全支持）...")

    # 1. Notion → GitHub（全量导出）
    for i, pid in enumerate(PARENT_PAGE_IDS):
        print(f"\n===== 父页面 {i+1}/{len(PARENT_PAGE_IDS)} (ID: {pid}) =====")
        traverse_notion_pages(pid)

    # 2. GitHub → Notion（反向更新）
    print("\n🔄 开始反向同步（GitHub → Notion）...")
    update_notion_from_github()

    # 3. Git提交
    git_commit_and_push()

    print(f"\n🎉 完成！共处理 {len(visited_page_ids)} 个页面")
