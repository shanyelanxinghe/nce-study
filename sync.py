import os
from notion_client import Client

# ✅ 强制创建目录，防止报错
os.makedirs("notion_pages", exist_ok=True)

token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)

PARENT_PAGE_IDS = [
    os.getenv("NCE_PAGE_ID"),
    os.getenv("WEEKLY_PAGE_ID"),
    os.getenv("DESKTOP_PAGE_ID"),
    os.getenv("MONTHLY_PAGE_ID"),
    os.getenv("INCOME_PAGE_ID"),
    os.getenv("EXPENSES_PAGE_ID"),
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid]

visited_page_ids = set()

def sync_page_content(page_id, page_title):
    if page_id in visited_page_ids:
        return
    visited_page_ids.add(page_id)

    # 读 Notion
    blocks = notion.blocks.children.list(block_id=page_id).get("results", [])
    notion_text = ""
    for b in blocks:
        if b["type"] == "paragraph" and b["paragraph"]["rich_text"]:
            t = b["paragraph"]["rich_text"][0]["text"]["content"]
            notion_text += t + "\n\n"

    # 写 GitHub md
    safe_title = "".join(c if c.isalnum() or c in (" ", "_") else "_" for c in page_title)
    filename = f"notion_pages/{safe_title}_{page_id[:8]}.md"
    github_md = ""
    if os.path.exists(filename):
        with open(filename, "r", encoding="utf-8") as f:
            github_md = f.read()

    if len(github_md) > len(notion_text):
        for b in blocks:
            notion.blocks.delete(block_id=b["id"])
        notion.blocks.children.append(
            block_id=page_id,
            children=[{"type":"paragraph","paragraph":{"rich_text":[{"type":"text","text":{"content":github_md}}]}}]
        )
        print(f"📥 [{page_title}] GitHub → Notion")
    else:
        with open(filename, "w", encoding="utf-8") as f:
            f.write(f"# {page_title}\n\n{notion_text}")
        print(f"📤 [{page_title}] Notion → GitHub  [文件: {filename}]")  # ✅ 明确打印文件名

def traverse_pages(start_page_id, depth=0):
    if start_page_id in visited_page_ids:
        return
    visited_page_ids.add(start_page_id)
    try:
        page_info = notion.pages.retrieve(page_id=start_page_id)
        title = page_info.get("properties",{}).get("title",{}).get("title",[{}])[0].get("plain_text","未命名")
        print(f"{'  '*depth}📄 {title}")
        sync_page_content(start_page_id, title)
        children = notion.blocks.children.list(block_id=start_page_id).get("results", [])
        for child in children:
            if child["type"] == "child_page":
                traverse_pages(child["id"], depth + 1)
    except Exception as e:
        print(f"{'  '*depth}❌ {start_page_id} 失败: {e}")

for i, pid in enumerate(PARENT_PAGE_IDS):
    print(f"\n===== 同步父页面 {i+1}/{len(PARENT_PAGE_IDS)} =====")
    traverse_pages(pid)

print(f"\n✅ 完成，共处理 {len(visited_page_ids)} 个页面")
