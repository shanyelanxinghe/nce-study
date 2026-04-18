import os
import re
from notion_client import Client

# ====================== 1. 自动创建目录（仓库根目录下） ======================
os.makedirs("notion_pages", exist_ok=True)  # 你要的目录，自动创建

token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)

# ====================== 2. 5 个父页面 ID（对应你的 Secrets） ======================
PARENT_PAGE_IDS = [
    os.getenv("NOTION_PAGE_ID"),       # 原 NCE_PAGE_ID 替换为 NOTION_PAGE_ID
    os.getenv("WEEKLY_PAGE_ID"),
    os.getenv("DESKTOP_PAGE_ID"),
    os.getenv("MONTHLY_PAGE_ID"),
    # 注意：你截图中没有 INCOME_PAGE_ID / EXPENSES_PAGE_ID，所以删掉了
]
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid and len(pid) == 32]  # 过滤空值和无效长度

visited_page_ids = set()

# ====================== 3. 安全文件名 & 取标题 ======================
def safe_filename(title, max_len=60):
    safe = re.sub(r'[<>:"/\\|?*]', '_', title)
    safe = re.sub(r'\s+', '_', safe).strip('_')
    return safe[:max_len]

# ====================== 4. 递归同步页面（深度优先） ======================
def sync_page(page_id, parent_title=""):
    if page_id in visited_page_ids:
        print(f"⚠️ 跳过已同步页面: {page_id}")
        return
    visited_page_ids.add(page_id)

    try:
        page = notion.pages.retrieve(page_id)
    except Exception as e:
        print(f"❌ 获取页面失败 (ID: {page_id}): {e}")
        return

    # 提取页面标题
    title = "未命名页面"
    if "properties" in page and "title" in page["properties"] and page["properties"]["title"]["title"]:
        title = page["properties"]["title"]["title"][0]["text"]["content"]
    if parent_title:
        title = f"{parent_title}_{title}"  # 父子页面标题拼接

    filename = safe_filename(title)
    filepath = f"notion_pages/{filename}.md"

    # 提取页面内容（简化版，可根据 Notion API 文档完善）
    content = ""
    if "blocks" in page:
        for block in page["blocks"]:
            block_type = block["type"]
            if block_type == "paragraph":
                text = block["paragraph"]["rich_text"][0]["text"]["content"] if block["paragraph"]["rich_text"] else ""
                content += f"{text}\n\n"
            elif block_type == "heading_1":
                text = block["heading_1"]["rich_text"][0]["text"]["content"] if block["heading_1"]["rich_text"] else ""
                content += f"# {text}\n\n"
            elif block_type == "heading_2":
                text = block["heading_2"]["rich_text"][0]["text"]["content"] if block["heading_2"]["rich_text"] else ""
                content += f"## {text}\n\n"
            # 可扩展更多块类型（列表、代码块等）

    # 写入 MD 文件
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{content}")

    print(f"✅ 已同步: {title} -> {filepath}")

    # 递归同步子页面（如果有）
    if "children" in page:
        for child in page["children"]:
            child_id = child["id"]
            sync_page(child_id, title)

# ====================== 5. 开始同步所有父页面 ======================
print(f"开始多父页面递归同步（共 {len(PARENT_PAGE_IDS)} 个父页面）...")
for i, pid in enumerate(PARENT_PAGE_IDS, 1):
    print(f"\n====== 同步父页面 {i}/{len(PARENT_PAGE_IDS)} (ID: {pid}) ======")
    sync_page(pid)

print(f"\n完成！共处理 {len(visited_page_ids)} 个唯一页面")
