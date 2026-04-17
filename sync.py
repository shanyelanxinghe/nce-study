import os
from notion_client import Client

token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)

# 你配置的 6 个父页面 ID（从环境变量读，和 GitHub Secrets 一一对应）
PARENT_PAGE_IDS = [
    os.getenv("NCE_PAGE_ID"),       # 我的新概念英语(NCE)学习库
    os.getenv("WEEKLY_PAGE_ID"),    # Weekly To-do List
    os.getenv("DESKTOP_PAGE_ID"),   # 从电脑桌面端开始吧！
    os.getenv("MONTHLY_PAGE_ID"),   # Monthly Budget
    os.getenv("INCOME_PAGE_ID"),    # Income (Monthly)
    os.getenv("EXPENSES_PAGE_ID"),  # Expenses (Monthly)
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid]  # 去掉空值

# 用一个集合记住“已经处理过的页面 ID”，避免重复同步
visited_page_ids = set()

def sync_page_content(page_id, page_title):
    """对单个页面做双向同步（Notion ↔ GitHub）"""
    global visited_page_ids
    if page_id in visited_page_ids:
        print(f"⏭️  跳过已处理页面：{page_title}")
        return
    visited_page_ids.add(page_id)

    # 1. 读 Notion 内容（只取 paragraph 文本）
    blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
    notion_text = ""
    for b in blocks:
        if b["type"] == "paragraph" and b["paragraph"]["rich_text"]:
            t = b["paragraph"]["rich_text"][0]["text"]["content"]
            notion_text += t + "\n\n"

    # 2. 读 GitHub 本地 md（按页面标题+短ID命名，避免重名）
    safe_title = "".join(c if c.isalnum() or c in (" ", "_") else "_" for c in page_title)
    filename = f"notion_pages/{safe_title}_{page_id[:8]}.md"
    github_md = ""
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            github_md = f.read()

    # 3. 双向同步：GitHub 新 → 写回 Notion；Notion 新 → 写 GitHub
    if len(github_md) > len(notion_text):
        for b in blocks:
            notion.blocks.delete(block_id=b["id"])
        notion.blocks.children.append(
            block_id=page_id,
            children=[{"type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":github_md}}]}}]
        )
        print(f"📥 [{page_title}] GitHub → Notion")
    else:
        os.makedirs("notion_pages", exist_ok=True)
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {page_title}\n\n{notion_text}")
        print(f"📤 [{page_title}] Notion → GitHub")

def traverse_pages(start_page_id, depth=0):
    """递归遍历页面树，同步当前页 + 子页（带防重）"""
    if start_page_id in visited_page_ids:
        return
    visited_page_ids.add(start_page_id)

    try:
        page_info = notion.pages.retrieve(page_id=start_page_id)
        title = page_info.get("properties",{}).get("title",{}).get("title",[{}])[0].get("plain_text","未命名")
        print(f"{'  '*depth}📄 {title}")

        # 先同步当前页面内容
        sync_page_content(start_page_id, title)

        # 再递归子页面（child_page）
        children = notion.blocks.children.list(block_id=start_page_id).get("results", [])
        for child in children:
            if child["type"] == "child_page":
                traverse_pages(child["id"], depth + 1)
    except Exception as e:
        print(f"{'  '*depth}❌ {start_page_id} 处理失败：{e}")

# 主流程：遍历你配置的 6 个父页面
for i, pid in enumerate(PARENT_PAGE_IDS):
    print(f"\n===== 同步第 {i+1} 个父页面（ID: {pid[:8]}...）=====")
    traverse_pages(pid)

print(f"\n✅ 完成，共处理 {len(visited_page_ids)} 个唯一页面（已自动去重）")
