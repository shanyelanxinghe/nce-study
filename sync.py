import os
from notion_client import Client

# ✅ 新增：确保目录存在（防止报错 "No such file or directory"）
os.makedirs("notion_pages", exist_ok=True)

# ====================== 初始化 ======================
token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)

# ====================== 6 个父页面 ID ======================
PARENT_PAGE_IDS = [
    os.getenv("NCE_PAGE_ID"),       # 我的新概念英语(NCE)学习库
    os.getenv("WEEKLY_PAGE_ID"),    # Weekly To-do List
    os.getenv("DESKTOP_PAGE_ID"),   # 从电脑桌面端开始吧！
    os.getenv("MONTHLY_PAGE_ID"),   # Monthly Budget
    os.getenv("INCOME_PAGE_ID"),    # Income (Monthly)
    os.getenv("EXPENSES_PAGE_ID"),  # Expenses (Monthly)
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid]  # 过滤空值

# ====================== 防重集合 ======================
visited_page_ids = set()

# ====================== 单个页面双向同步 ======================
def sync_page_content(page_id, page_title):
    if page_id in visited_page_ids:
        print(f"⏭️  跳过已处理页面：{page_title}")
        return
    visited_page_ids.add(page_id)

    # 1. 读 Notion 内容
    blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
    notion_text = ""
    for b in blocks:
        if b["type"] == "paragraph" and b["paragraph"]["rich_text"]:
            t = b["paragraph"]["rich_text"][0]["text"]["content"]
            notion_text += t + "\n\n"

    # 2. 读 GitHub 本地 md
    safe_title = "".join(c if c.isalnum() or c in (" ", "_") else "_" for c in page_title)
    filename = f"notion_pages/{safe_title}_{page_id[:8]}.md"  # 文件名带 ID 防冲突
    github_md = ""
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            github_md = f.read()

    # 3. 双向判断
    if len(github_md) > len(notion_text):
        # GitHub 更新 → 写回 Notion
        for b in blocks:
            notion.blocks.delete(block_id=b["id"])
        notion.blocks.children.append(
            block_id=page_id,
            children=[{"type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":github_md}}]}}]
        )
        print(f"📥 [{page_title}] GitHub → Notion")
    else:
        # Notion 更新 → 写 GitHub（目录已提前创建，不会报错）
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {page_title}\n\n{notion_text}")
        print(f"📤 [{page_title}] Notion → GitHub")

# ====================== 递归遍历子页 ======================
def traverse_pages(start_page_id, depth=0):
    if start_page_id in visited_page_ids:
        return
    visited_page_ids.add(start_page_id)

    try:
        page_info = notion.pages.retrieve(page_id=start_page_id)
        title = page_info.get("properties",{}).get("title",{}).get("title",[{}])[0].get("plain_text","未命名")
        print(f"{'  '*depth}📄 {title}")

        # 同步当前页
        sync_page_content(start_page_id, title)

        # 递归子页面
        children = notion.blocks.children.list(block_id=start_page_id).get("results", [])
        for child in children:
            if child["type"] == "child_page":
                traverse_pages(child["id"], depth + 1)
    except Exception as e:
        print(f"{'  '*depth}❌ {start_page_id} 处理失败：{e}")

# ====================== 主流程 ======================
if __name__ == "__main__":
    print("🚀 开始多父页面递归同步（防重版）...")
    for i, pid in enumerate(PARENT_PAGE_IDS):
        print(f"\n===== 同步第 {i+1} 个父页面（ID: {pid[:8]}...）=====")
        traverse_pages(pid)
    print(f"\n✅ 完成，共处理 {len(visited_page_ids)} 个唯一页面（已去重）")
