import os
import re
import subprocess
from notion_client import Client

# ================= 1. 初始化 =================
os.makedirs("notion_pages", exist_ok=True)

token = os.getenv("NOTION_TOKEN")
if not token:
    raise SystemExit("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")

notion = Client(auth=token)

PARENT_PAGE_IDS = [
    os.getenv("NOTION_PAGE_ID"),
    os.getenv("WEEKLY_PAGE_ID"),
    os.getenv("DESKTOP_PAGE_ID"),
    os.getenv("MONTHLY_PAGE_ID"),
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid]  # 过滤空值

visited_page_ids = set()

# ================= 2. 工具函数 =================
def safe_filename(title):
    """生成固定文件名：只留字母数字和下划线"""
    return re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', title).strip('_')

def get_page_title(page_info):
    """从页面属性提取标题"""
    title_prop = page_info.get("properties", {}).get("title", {})
    if title_prop.get("title", []):
        return title_prop["title"][0].get("plain_text", "未命名")
    return "未命名"

# ================= 3. Notion → GitHub（递归读块，单文件覆盖） =================
def parse_block_to_md(block):
    """把Notion块转成Markdown一行"""
    block_type = block["type"]
    content = block[block_type].get("rich_text", [])
    text = "".join(t.get("text", {}).get("content", "") for t in content)

    if block_type == "paragraph":
        return text + "\n\n"
    elif block_type == "heading_1":
        return f"# {text}\n\n"
    elif block_type == "heading_2":
        return f"## {text}\n\n"
    elif block_type == "heading_3":
        return f"### {text}\n\n"
    elif block_type == "bulleted_list_item":
        return f"- {text}\n"
    elif block_type == "numbered_list_item":
        return f"1. {text}\n"
    elif block_type == "to_do":
        checked = "✅" if block[block_type].get("checked") else "⬜"
        return f"- {checked} {text}\n"
    else:
        return ""

def save_page_to_md(page_id, parent_title=""):
    """把整个页面（含子页引用）存到一个MD里"""
    if page_id in visited_page_ids:
        return ""
    visited_page_ids.add(page_id)

    try:
        page = notion.pages.retrieve(page_id)
        title = get_page_title(page)
        full_title = f"{parent_title}_{title}" if parent_title else title

        # 读所有块
        blocks = notion.blocks.children.list(page_id).get("results", [])
        md_content = f"# {full_title}\n\n"

        for block in blocks:
            # 子页面：只记链接，不递归内容（避免无限嵌套）
            if block["type"] == "child_page":
                child_title = block["child_page"].get("title", "子页")
                child_id = block["id"]
                md_content += f"> 🔗 子页面：[{child_title}](notion_pages/{safe_filename(child_title)}_{child_id[:8]}.md)\n\n"
            else:
                md_content += parse_block_to_md(block)

        # ✅ 固定文件名：标题 + 页面ID前8位（不会重复）
        filename = f"notion_pages/{safe_filename(full_title)}_{page_id[:8]}.md"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"📤 [{title}] → {filename}")

        # 递归存子页（每个子页也是独立MD）
        for block in blocks:
            if block["type"] == "child_page":
                save_page_to_md(block["id"], full_title)

        return md_content
    except Exception as e:
        print(f"❌ 保存页面失败 {page_id[:8]}: {str(e)[:80]}")
        return ""

# ================= 4. GitHub → Notion（反向追加） =================
def update_notion_from_md():
    """把MD里新增的内容追加到Notion页面尾部（不清空原内容）"""
    for root, _, files in os.walk("notion_pages"):
        for f in files:
            if not f.endswith(".md"):
                continue
            path = os.path.join(root, f)
            with open(path, "r", encoding="utf-8") as fp:
                content = fp.read()

            # 从文件名里取出页面ID（倒数第11~3位）
            parts = f.rsplit('_', 1)
            if len(parts) < 2:
                continue
            page_id_candidate = parts[-1].replace('.md', '')
            if not page_id_candidate or len(page_id_candidate) != 8:
                continue

            # 在所有父页面里找匹配的ID
            target_page_id = None
            for pid in PARENT_PAGE_IDS:
                if pid.startswith(page_id_candidate):
                    target_page_id = pid
                    break
            if not target_page_id:
                continue

            # 只取MD里新增的非标题行
            lines = content.split('\n')
            new_lines = []
            for line in lines:
                line = line.strip()
                if line and not line.startswith('#') and line not in new_lines:
                    new_lines.append(line)

            if not new_lines:
                continue

            # 追加到Notion尾部
            blocks = []
            for line in new_lines:
                blocks.append({
                    "type": "paragraph",
                    "paragraph": {"rich_text": [{"type": "text", "text": {"content": line}}]}
                })

            try:
                notion.blocks.children.append(block_id=target_page_id, children=blocks)
                print(f"📥 已追加到 Notion：{f} → {target_page_id[:8]}")
            except Exception as e:
                print(f"⚠️ 反向写入跳过（无权限/页面不存在）：{f}")

# ================= 5. Git提交（防冲突） =================
def git_commit_push():
    try:
        subprocess.run(["git", "config", "--global", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "--global", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "pull", "origin", "main", "--rebase"], check=True)
        subprocess.run(["git", "add", "notion_pages/"], check=True)
        commit_res = subprocess.run(["git", "commit", "-m", "🔄 Sync: Notion↔GitHub"], capture_output=True, text=True)
        if "nothing to commit" in commit_res.stdout:
            print("🟢 无变更，跳过提交")
        else:
            subprocess.run(["git", "push", "origin", "main"], check=True)
            print("✅ 已推送到仓库")
    except subprocess.CalledProcessError as e:
        print(f"❌ Git错误: {e.stderr}")

# ================= 6. 主流程 =================
if __name__ == "__main__":
    print("🚀 开始双向同步（单文件覆盖+全内容）...")
    
    # 1. Notion → GitHub
    for pid in PARENT_PAGE_IDS:
        save_page_to_md(pid)
    
    # 2. GitHub → Notion
    update_notion_from_md()
    
    # 3. Git提交
    git_commit_push()
    
    print(f"\n🎉 完成！共处理 {len(visited_page_ids)} 个页面")
