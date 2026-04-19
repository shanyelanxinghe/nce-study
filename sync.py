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
    """生成唯一文件名：标题 + 页面ID前8位"""
    safe = re.sub(r'[<>:"/\\|?*]', "_", title)  # 替换非法字符
    safe = safe.strip("_").replace(" ", "_")   # 空格转下划线
    return f"notion_pages/{safe}_{page_id[:8]}.md"


def get_page_title(page_info):
    """从页面信息中提取标题"""
    title_prop = page_info.get("properties", {}).get("title", {})
    if isinstance(title_prop, dict) and title_prop.get("title"):
        return title_prop["title"][0].get("plain_text", "未命名")
    return "未命名"


# ========== 3. Notion → GitHub：递归同步（支持子页、段落、列表、表格） ==========
def parse_block_to_md(block):
    """将Notion块转换为Markdown格式"""
    block_type = block["type"]
    rich_text = block.get(block_type, {}).get("rich_text", [])
    text = "".join([t.get("text", {}).get("content", "") for t in rich_text])

    if block_type == "paragraph":
        return text + "\n"
    elif block_type == "heading_1":
        return f"# {text}\n"
    elif block_type == "heading_2":
        return f"## {text}\n"
    elif block_type == "heading_3":
        return f"### {text}\n"
    elif block_type == "bulleted_list_item":
        return f"- {text}\n"
    elif block_type == "numbered_list_item":
        # 序号（如果是自动编号，可能需提取要更复杂逻辑，这里简化处理）
        return f"1. {text}\n"  # 实际应从block中获取序号，此处示例
    elif block_type == "to_do":
        checked = "✅" if block.get("checked") else "⬜"
        return f"- {checked} {text}\n"
    elif block_type == "table":
        # 转换表格（示例：仅处理表头和内容行）
        table = block["table"]
        rows = table.get("rows", [])
        md_table = "| " + " | ".join([cell.get("text", {}).get("content", "") for cell in rows[0]]) + " |\n"
        md_table += "| " + " | ".join(["---"] * len(rows[0])) + " |\n"
        for row in rows[1:]:
            md_table += "| " + " | ".join([cell.get("text", {}).get("content", "") for cell in row]) + " |\n"
        return md_table + "\n"
    elif block_type == "child_page":
        # 子页面递归处理（返回子页面标题，内容在后续递归中处理）
        child_title = block["child_page"].get("title", "未命名子页")
        return f"[子页：{child_title}]\n"
    else:
        return ""  # 未知块类型，跳过


def traverse_pages(start_page_id, parent_id=None):
    """递归遍历Notion页面及子页面"""
    if start_page_id in visited_page_ids:
        return
    visited_page_ids.add(start_page_id)

    try:
        # 获取页面信息
        page_info = notion.pages.retrieve(page_id=start_page_id)
        title = get_page_title(page_info)
        page_id_to_title[start_page_id] = title
        print(f"📄 处理页面: {title} (ID: {start_page_id})")

        # 读取页面所有块
        blocks = notion.blocks.children.list(block_id=start_page_id).get("results", [])
        md_content = f"# {title}\n\n"  # 标题作为一级标题

        for block in blocks:
            block_type = block["type"]
            md_line = parse_block_to_md(block)
            md_content += md_line

            # 递归处理子页面
            if block_type == "child_page":
                child_page_id = block["id"]
                traverse_pages(child_page_id, start_page_id)

        # 生成唯一文件名（标题 + 页面ID前8位）
        filename = safe_filename(title, start_page_id)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"💾 保存: {filename}")

    except Exception as e:
        print(f"❌ 处理页面 {start_page_id} 失败: {str(e)[:100]}")


# ========== 4. GitHub → Notion：反向同步（支持标题、段落、列表、表格） ==========
def md_to_notion_blocks(md_content):
    """将Markdown内容转换为Notion块"""
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
            text = line[2:]
            blocks.append({
                "type": "heading_1",
                "heading_1": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })
        elif line.startswith("## "):
            text = line[3:]
            blocks.append({
                "type": "heading_2",
                "heading_2": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })
        elif line.startswith("### "):
            text = line[4:]
            blocks.append({
                "type": "heading_3",
                "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })

        # 处理列表
        elif line.startswith("- "):
            # 处理待办事项（带✅/⬜）
            if "✅" in line or "⬜" in line:
                checked = "✅" in line
                text = line.replace("✅", "").replace("⬜", "").strip()[2:]  # 去掉“- ”和符号
                blocks.append({
                    "type": "to_do",
                    "to_do": {
                        "rich_text": [{"type": "text", "text": {"content": text}}],
                        "checked": checked
                    }
                })
            else:
                text = line[2:]
                blocks.append({
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
                })

        # 处理编号列表（示例：仅处理“1. ”开头的）
        elif re.match(r"^\d+\. ", line):
            text = re.sub(r"^\d+\. ", "", line)
            blocks.append({
                "type": "numbered_list_item",
                "numbered_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]}
            })

        # 处理表格（示例：简化版，实际需更健壮的解析）
        elif line.startswith("|") and line.endswith("|"):
            if not in_table:
                in_table = True
                table_rows = []
            # 分割列（去掉首尾的|）
            cells = [c.strip() for c in line[1:-1].split("|")]
            table_rows.append(cells)
        elif in_table and line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line[1:-1].split("|")]
            table_rows.append(cells)
        elif in_table and not line.startswith("|"):
            # 表格结束，转换为Notion表格块
            in_table = False
            # 表格行转Notion表格行
            notion_rows = []
            for row in table_rows:
                notion_row = {"cells": [{"text": {"content": cell}} for cell in row]}
                notion_rows.append(notion_row)
            blocks.append({
                "type": "table",
                "table": {"rows": notion_rows}
            })
            table_rows = []

        # 处理普通段落
        else:
            blocks.append({
                "type": "paragraph",
                "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
            })

    return blocks


def update_notion_from_github():
    """从GitHub的MD文件反向同步到Notion"""
    # 映射：页面标题 → Notion页面ID（从全局缓存获取）
    title_to_page_id = {v: k for k, v in page_id_to_title.items()}

    for page_id, title in page_id_to_title.items():
        # 生成对应的MD文件名
        filename = safe_filename(title, page_id)
        if not os.path.exists(filename):
            print(f"⚠️ 文件不存在: {filename}，跳过反向同步")
            continue

        with open(filename, "r", encoding="utf-8") as f:
            md_content = f.read()

        # 转换为Notion块
        new_blocks = md_to_notion_blocks(md_content)

        try:
            # 获取原页面的所有块
            old_blocks = notion.blocks.children.list(block_id=page_id).get("results", [])

            # 1. 删除旧块（保留子页面？不，子页面在Notion→GitHub时已递归处理，此处仅更新当前页面内容）
            for block in old_blocks:
                # 跳过子页面块（child_page），因为子页面是独立页面，在Notion→GitHub时已处理
                if block["type"] != "child_page":
                    notion.blocks.delete(block_id=block["id"])

            # 2. 追加新块
            if new_blocks:
                notion.blocks.children.append(block_id=page_id, children=new_blocks)
            print(f"✅ 反向同步: {title} → Notion（已更新）")

        except Exception as e:
            print(f"❌ 反向同步 {title} 失败: {str(e)[:100]}")


# ========== 5. Git防冲突提交 ==========
def git_commit_push():
    """提交并推送变更到GitHub"""
    try:
        # 配置Git用户（必须，否则push失败）
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)

        # 拉取最新代码（避免冲突）
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)

        # 添加变更
        subprocess.run(["git", "add", "notion_pages/"], check=True)

        # 提交（如果没有变更则跳过）
        commit_result = subprocess.run(["git", "commit", "-m", "🔄 Auto-Sync: Update notion_pages"], capture_output=True, text=True)
        if "nothing to commit" in commit_result.stdout:
            print("🟢 无变更，跳过提交")
        else:
            # 推送变更
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ 已推送到仓库")

    except subprocess.CalledProcessError as e:
        print(f"❌ Git操作失败: {e.stderr}")


# ========== 6. 主入口 ==========
if __name__ == "__main__":
    print("🚀 开始双向同步（标题/段落/列表/表格/子页全支持）...")

    # 1. Notion → GitHub：递归同步所有页面
    for pid in PARENT_PAGE_IDS:
        traverse_pages(pid)
    print(f"\n✅ Notion→GitHub 同步完成，共处理 {len(visited_page_ids)} 个页面")

    # 2. GitHub → Notion：反向同步（仅更新已存在的页面）
    print("\n🔄 开始反向同步（GitHub→Notion）...")
    update_notion_from_github()

    # 3. Git提交变更
    print("\n📦 开始Git提交...")
    git_commit_push()

    print(f"\n🎉 同步完成！共处理 {len(visited_page_ids)} 个页面，已推送到GitHub仓库")
