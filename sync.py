import os
import re
from notion_client import Client

# ====================== 1. 自动创建目录（仓库根目录下） ======================
os.makedirs("notion_pages", exist_ok=True)

token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)

# ====================== 2. 5 个父页面 ID（对应你的 Secrets） ======================
PARENT_PAGE_IDS = [
    os.getenv("NOTION_PAGE_ID"),
    os.getenv("WEEKLY_PAGE_ID"),
    os.getenv("DESKTOP_PAGE_ID"),
    os.getenv("MONTHLY_PAGE_ID"),
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid and len(pid) == 32]

visited_page_ids = set()

# ====================== 3. 安全文件名 & 取标题 ======================
def safe_filename(title, max_len=60):
    safe = re.sub(r'[<>:"/\\|?*]', '_', title)
    safe = re.sub(r'\s+', '_', safe).strip('_')
    return safe[:max_len]

def get_page_title(page_info):
    title_prop = page_info.get("properties", {}).get("title", {})
    if isinstance(title_prop, dict) and title_prop.get("title", []):
        return title_prop["title"][0].get("plain_text", "未命名")
    blocks = notion.blocks.children.list(block_id=page_info["id"]).get("results", [])
    for b in blocks:
        if b["type"] == "paragraph" and b["paragraph"].get("rich_text"):
            return b["paragraph"]["rich_text"][0]["text"]["content"]
    return "未命名"

# ====================== 4. 双向同步（文件写入 notion_pages/） ======================
def sync_page_content(page_id, page_title):
    if page_id in visited_page_ids:
        return
    visited_page_ids.add(page_id)

    # 读 Notion
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

    # 写 GitHub（固定到 notion_pages/）
    safe_title = safe_filename(page_title)
    filename = f"notion_pages/{safe_title}_{page_id[:8]}.md"
    github_md = ""
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            github_md = f.read()

    if len(github_md) > len(notion_text):
        for b in blocks:
            notion.blocks.delete(block_id=b["id"])
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
        print(f"📥 [{page_title}] GitHub → Notion")
    else:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(notion_text)
        print(f"📤 [{page_title}] Notion → GitHub → {filename}")

# ====================== 5. 递归遍历 ======================
def traverse_pages(start_page_id, depth=0):
    if start_page_id in visited_page_ids:
        return
    visited_page_ids.add(start_page_id)
    try:
        page_info = notion.pages.retrieve(page_id=start_page_id)
        title = get_page_title(page_info)
        print(f"{'  '*depth}📄 {title} ({start_page_id[:8]})")
        sync_page_content(start_page_id, title)
        children = notion.blocks.children.list(block_id=start_page_id).get("results", [])
        for child in children:
            if child["type"] == "child_page":
                traverse_pages(child["id"], depth + 1)
    except Exception as e:
        print(f"{'  '*depth}❌ {start_page_id[:8]} 失败: {str(e)[:100]}")

# ====================== 6. Git 自动提交（防冲突版） ======================
def git_commit_push():
    import subprocess
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        # 先拉取远程更新（解决 non-fast-forward）
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        subprocess.run(["git", "add", "notion_pages/"], check=True)
        # 尝试提交，若无变更则跳过
        commit_result = subprocess.run(["git", "commit", "-m", "🔄 Auto-Sync: Update notion_pages"], capture_output=True, text=True)
        if "nothing to commit" in commit_result.stdout:
            print("🟢 无变更，跳过提交")
        else:
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ 已推送 notion_pages/ 到仓库")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git 操作失败: {e.stderr}")

# ====================== 7. 主入口 ======================
if __name__ == "__main__":
    print("🚀 开始同步 → 文件生成到 notion_pages/")
    if not PARENT_PAGE_IDS:
        print("❌ 未配置有效页面ID")
        exit(1)
    for i, pid in enumerate(PARENT_PAGE_IDS):
        print(f"\n===== 父页面 {i+1}/{len(PARENT_PAGE_IDS)} =====")
        traverse_pages(pid)
    print(f"\n✅ 同步完成，共 {len(visited_page_ids)} 个页面")
    # 同步完后自动提交（防冲突）
    git_commit_push()
