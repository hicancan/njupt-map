"""What a building or place is, as the authored layers say it: one closed list of categories, each in a group and with
the prominence a map shows it at. Clients read category, group and tier from the entities; nothing else classifies."""
from __future__ import annotations

# category -> (group, tier). Tier 1 shows from afar (the buildings a campus is found by), 2 as one comes closer, 3 only
# close up (shops, stops, small facilities). Every authored building and place carries exactly one of these.
CATEGORIES: dict[str, tuple[str, int]] = {
    '教学楼': ('教学科研', 1), '学院': ('教学科研', 1), '图书馆': ('教学科研', 1), '场馆': ('教学科研', 1),
    '实验室': ('教学科研', 3), '研究机构': ('教学科研', 3), '报告厅': ('教学科研', 3), '展馆': ('教学科研', 2), '学校': ('教学科研', 2),
    '行政': ('办公', 1), '机构': ('办公', 3),
    '食堂': ('生活', 1), '宿舍': ('生活', 2), '住宅': ('生活', 3), '设施': ('生活', 3),
    '餐厅': ('餐饮', 3), '快餐小吃': ('餐饮', 3), '咖啡茶饮': ('餐饮', 3), '烘焙甜品': ('餐饮', 3),
    '超市便利': ('购物', 2), '商场市场': ('购物', 2), '服饰': ('购物', 3), '数码电器': ('购物', 3), '书店文具': ('购物', 3), '商店': ('购物', 3),
    '快递': ('服务', 2), '打印': ('服务', 2), '医疗': ('服务', 2), '营业厅': ('服务', 3), '银行': ('服务', 3), '邮局': ('服务', 3),
    '理发美容': ('服务', 3), '洗衣维修': ('服务', 3), '住宿': ('服务', 3), '培训': ('服务', 3), '生活服务': ('服务', 3),
    '体育': ('文体', 2), '娱乐': ('文体', 3), '景观': ('文体', 2),
    '校门': ('交通', 1), '地铁站': ('交通', 2), '公交站': ('交通', 3), '停车场': ('交通', 3), '加油充电': ('交通', 3),
}

def group(category: str) -> str: return CATEGORIES[category][0]
def tier(category: str) -> int: return CATEGORIES[category][1]

# The look a building of a category takes unless it says otherwise (its style_hint).
STYLE_DEFAULTS: dict[str, str] = {'宿舍': 'dormitory', '食堂': 'dining', '图书馆': 'library', '教学楼': 'academic', '学院': 'academic', '设施': 'service'}
