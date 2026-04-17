import os
from notion_client import Client

# ====================== 1. 初始化 Notion 客户端 ======================
token = os.getenv("NOTION_TOKEN")
if not token:
    print("❌ 请在 GitHub Secrets 中配置 NOTION_TOKEN！")
    exit(1)
notion = Client(auth=token)


# ====================== 2. 定义所有父页面 ID（从环境变量读取） ======================
# 你的密钥名称（需和 GitHub Secrets 一致）：
# - NCE_PAGE_ID → 我的新概念英语(NCE)学习库
# - WEEKLY_PAGE_ID → Weekly To-do List
# - DESKTOP_PAGE_ID → 从电脑桌面端开始吧！
# - MONTHLY_PAGE_ID → Monthly Budget（主预算页面）
# - INCOME_PAGE_ID → Income (Monthly)（收入子页面）
# - EXPENSES_PAGE_ID → Expenses (Monthly)（支出子页面）
PARENT_PAGE_IDS = [
    os.getenv("NCE_PAGE_ID"),       # 父页面：我的新概念英语(NCE)学习库
    os.getenv("WEEKLY_PAGE_ID"),    # 父页面：Weekly To-do List
    os.getenv("DESKTOP_PAGE_ID"),   # 父页面：从电脑桌面端开始吧！
    os.getenv("MONTHLY_PAGE_ID"),   # 父页面：Monthly Budget（主预算页面）
    os.getenv("INCOME_PAGE_ID"),    # 父页面：Income (Monthly)（收入子页面）
    os.getenv("EXPENSES_PAGE_ID"),  # 父页面：Expenses (Monthly)（支出子页面）
]

# 过滤掉未配置的空 ID（防止密钥没配置时出错）
PARENT_PAGE_IDS = [pid for pid in PARENT_PAGE_IDS if pid]


# ====================== 3. 递归遍历页面及其子页面/数据库 ======================
def traverse_and_sync(page_id, level=0):
    """
    递归遍历页面及其子页面/数据库，执行同步逻辑（读取 Notion 内容 → 写入 GitHub md）
    :param page_id: 当前页面的 ID
    :param level: 递归层级（用于打印调试信息）
    """
    indent = "  " * level  # 缩进，方便调试时区分层级
    print(f"{indent}🔍 正在同步页面：{page_id}")

    # ---------- 同步当前页面的内容 ----------
    try:
        # 读取 Notion 页面的完整内容
        page = notion.pages.retrieve(page_id=page_id)
        print(f"{indent}✅ 页面读取成功：{page['properties'].get('title', [{}])[0].get('text', {}).get('content', '无标题')}")
        
        # （可选）将 Notion 内容转换为 Markdown，写入 GitHub 仓库
        # 示例：提取标题和内容，写入 md 文件
        title = page["properties"].get("title", [{}])[0].get("text", {}).get("content", "untitled")
        content = ""  # 这里需要根据 Notion 块结构解析内容（示例简化，实际需处理 blocks）
        # ... 解析 content 并写入文件的代码 ...

        # 打印同步完成信息
        print(f"{indent}📝 页面 {title} 同步完成")

    except Exception as e:
        print(f"{indent}❌ 页面 {page_id} 同步失败：{str(e)}")


    # ---------- 递归处理子页面和数据库 ----------
    try:
        # 获取页面的所有子元素（子页面、数据库、块等）
        children = notion.blocks.children.list(block_id=page_id)
        for child in children["results"]:
            # 判断是否是“子页面”或“数据库”（其他块类型可忽略或扩展处理）
            if child["type"] == "child_page":
                child_page_id = child["id"]
                traverse_and_sync(child_page_id, level + 1)  # 递归处理子页面
            elif child["type"] == "child_database":
                child_db_id = child["id"]
                traverse_and_sync(child_db_id, level + 1)   # 递归处理数据库（如表格）
            else:
                # 其他块类型（如文本、列表、图片等）可按需处理
                print(f"{indent}⏩ 跳过非页面/数据库块：{child['type']}")

    except Exception as e:
        print(f"{indent}❌ 获取子元素失败（页面 {page_id}）：{str(e)}")


# ====================== 4. 启动同步（遍历所有父页面） ======================
for idx, page_id in enumerate(PARENT_PAGE_IDS, 1):
    print(f"\n===== 第 {idx} 个父页面同步：{page_id} =====")
    traverse_and_sync(page_id, level=0)

print("\n===== 所有父页面同步完成！ =====")
