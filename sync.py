import os
import re
import subprocess
from notion_client import Client

# ====================== 1. 自动创建目录 ======================
os.makedirs("notion_pages", exist_ok=True)

token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)

# ====================== 2. 父页面 ID（对应你的 Secrets） ======================
PARENT_PAGE_IDS = [
    os.getenv("NOTION_PAGE_ID"),
    os.getenv("WEEKLY_PAGE_ID"),
    os.getenv("DESKTOP_PAGE_ID"),
    os.getenv("MONTHLY_PAGE_ID"),
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid and len(pid) == 32]

visited_page_ids = set()

# ====================== 3. 工具函数 ======================
def safe_filename(title, max_len=60):
    safe = re.sub(r'[<>:"/\\|?*]', '_', title)
    safe = re.sub(r'\s+', '_', safe).strip('_')
    return safe[:max_len]

def get_page_title(page_info):
    title_prop = page_info.get("properties", {}).get("title", {})
    if isinstance(title_prop, dict) and title_prop.get("title", []):
        return title_prop["title"][0].get("plain_text", "未命名")
    return "未命名"

# ====================== 4. Notion → GitHub：递归同步（支持段落/标题/列表/子页） ======================
def parse_block_to_md(block):
    """把 Notion 块转成 Markdown 行"""
    type_map = {
        "paragraph": lambda b: "".join(t["text"]["content"] for t in b.get("rich_text", [])),
        "heading_1": lambda b: "# " + "".join(t["text"]["content"] for t in b.get("rich_text", [])),
        "heading_2": lambda b: "## " + "".join(t["text"]["content"] for t in b.get("rich_text", [])),
        "heading_3": lambda b: "### " + "".join(t["text"]["content"] for t in b.get("rich_text", [])),
        "bulleted_list_item": lambda b: "- " + "".join(t["text"]["content"] for t in b.get("rich_text", [])),
        "numbered_list_item": lambda b: "1. " + "".join(t["text"]["content"] for t in b.get("rich_text", [])),
        "to_do": lambda b: f"- {'✅' if b.get('checked') else '⬜'} " + "".join(t["text"]["content"] for t in b.get("rich_text", [])),
    }
    for block_type, parser in type_map.items():
        if block["type"] == block_type:
            return parser(block[block_type]) + "\n"
    return ""

def traverse_pages(start_page_id, depth=0):
    if start_page_id in visited_page_ids:
        return
    visited_page_ids.add(start_page_id)

    try:
        page_info = notion.pages.retrieve(page_id=start_page_id)
        title = get_page_title(page_info)
        print(f"{'  '*depth}📄 {title}")

        # 读取页面所有块
        blocks = notion.blocks.children.list(block_id=start_page_id).get("results", [])
        notion_text = f"# {title}\n\n"
        for b in blocks:
            line = parse_block_to_md(b)
            notion_text += line if line else ""
            # 递归子页面
            if b["type"] == "child_page":
                traverse_pages(b["id"], depth + 1)

        # 写入 MD
        safe_title = safe_filename(title)
        filename = f"notion_pages/{safe_title}_{start_page_id[:8]}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(notion_text)
        print(f"{'  '*depth}📤 [{title}] → {filename}")

    except Exception as e:
        print(f"{'  '*depth}❌ {start_page_id[:8]} 失败: {str(e)[:100]}")

# ====================== 5. GitHub → Notion：反向同步（支持标题/段落/列表回写） ======================
def update_notion_from_github():
    # 映射：MD文件名 → Notion页面ID（根据你的 Secrets 配置）
    md_to_page_id = {
        "notion_pages/我的新概念英语(NCE)学习库": os.getenv("NOTION_PAGE_ID"),
        "notion_pages/Weekly_To-do_List": os.getenv("WEEKLY_PAGE_ID"),
        "notion_pages/从电脑桌面端开始吧": os.getenv("DESKTOP_PAGE_ID"),
        "notion_pages/Monthly_Budget": os.getenv("MONTHLY_PAGE_ID"),
    }

    for md_base, page_id in md_to_page_id.items():
        filename = f"{md_base}_{page_id[:8]}.md"  # 匹配你生成的MD文件名格式
        if not os.path.exists(filename):
            continue

        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()

        # 解析MD为Notion块
        blocks = []
        lines = content.split("\n")
        for line in lines:
            line = line.strip()
            if not line: continue
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
            elif line.startswith("- ") or line.startswith("1. ") or "⬜" in line or "✅" in line:
                blocks.append({
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
                })
            else:
                blocks.append({
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
                })

        # 清空原页面并写入新块
        try:
            old_blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
            for b in old_blocks:
                notion.blocks.delete(block_id=b["id"])
            if blocks:
                notion.blocks.children.append(block_id=page_id, children=blocks)
            print(f"📥 {md_base} → Notion（已更新）")
        except Exception as e:
            print(f"❌ 反向同步失败 {md_base}: {e}")

# ====================== 6. Git防冲突提交 ======================
def git_commit_push():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        subprocess.run(["git", "add", "notion_pages/"], check=True)
        commit_result = subprocess.run(["git", "commit", "-m", "🔄 Auto-Sync: Update notion_pages"], capture_output=True, text=True)
        if "nothing to commit" in commit_result.stdout:
            print("🟢 无变更，跳过提交")
        else:
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ 已推送到仓库")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git错误: {e.stderr}")

# ====================== 7. 主入口 ======================
if __name__ == "__main__":
    print("🚀 开始双向同步（标题/段落/列表/子页全支持）...")
    # 1. Notion → GitHub
    for i, pid in enumerate(PARENT_PAGE_IDS):
        print(f"\n===== 父页面 {i+1}/{len(PARENT_PAGE_IDS)} =====")
        traverse_pages(pid)
    # 2. GitHub → Notion（反向）
    print("\n🔄 开始反向同步（GitHub → Notion）...")
    update_notion_from_github()
    # 3. Git提交
    git_commit_push()
    print(f"\n🎉 完成！共处理 {len(visited_page_ids)} 个页面")
