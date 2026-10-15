"use strict";
// UI strings (zh / en). Placeholders: {name}.
const I18N = {
  zh: {
    "page.title": "行程规划 · 多 Agent", "header.title": "行程规划 · 多 Agent", "header.sub": "商务出行 / 家庭游 / 入境游",
    "plan.h": "规划行程", "plan.query_label": "描述你的出行需求（支持中文、English、日本語、한국어）",
    "plan.query_ph": "例如：10月24日带5岁孩子（花生过敏）和70岁奶奶从上海去杭州玩3天",
    "plan.profile_label": "家庭档案 ID（可选：保存成员偏好，下次自动带入）", "plan.profile_ph": "例如 zhang-family",
    "btn.view": "查看", "btn.delete": "删除", "btn.plan": "开始规划", "btn.planning": "规划中…", "chips.aria": "示例需求",
    "chip.biz.tag": "商务", "chip.biz": "上海→新加坡拜访客户",
    "chip.fam1.tag": "家庭", "chip.fam1": "老人 + 孩子 + 过敏",
    "chip.fam2.tag": "家庭", "chip.fam2": "带婴儿车",
    "chip.multi.tag": "多家庭", "chip.multi": "两家拆账",
    "chip.mem.tag": "记忆", "chip.mem": "第二次规划（用档案）",
    "chip.in1.tag": "入境", "chip.in1": "美国夫妇 → 北京",
    "chip.in2.tag": "入境", "chip.in2": "日本家庭 → 上海",
    "steps.h": "Agent 执行过程", "step.running": "运行中…", "step.failed": "失败：{msg}", "step.done": "完成",
    "ask.h": "入境游助手（签证 / 支付 / 网络）", "ask.q_label": "问题", "ask.lang_label": "回答语言", "ask.btn": "提问",
    "ask.note": "只根据知识库回答并附来源；不要输入银行卡号、CVV、密码或验证码。", "ask.loading": "查询知识库中…",
    "ask.no_kb": "知识库中没有可靠信息，未生成回答。", "ask.failed": "提问失败：{msg}",
    "rc.h": "小票识别与记账", "rc.file_label": "拍照或选择中文小票（JPG / PNG / WebP，≤ 5 MB）", "rc.lang_label": "翻译成",
    "rc.cur_label": "本币", "rc.list_h": "消费清单", "rc.empty": "还没有记录。", "rc.csv": "导出 CSV",
    "rc.note": "图片只用于本次识别，不会保存在服务器上。", "rc.too_big": "图片不能超过 5 MB。", "rc.loading": "识别中…",
    "rc.failed": "识别失败：{msg}", "rc.no_date": "日期未识别",
    "result.empty": "输入出行需求后，这里会显示目的地天气、同行人约束、热门景点与优惠券、交通、酒店、按天气安排的逐日行程、合规检查、费用分摊、出行提醒（网络变化、人民币零钱）、入境准备和分享文案。",
    "result.loading": "多个 Agent 正在协作规划，通常需要 30–90 秒…",
    "plan.done": "规划完成，总用时 {s} 秒", "plan.failed": "规划失败：{msg}", "plan.disconnected": "与服务的连接中断，请确认 server.py 仍在运行。",
    "err.profile_id": "档案 ID 只能包含字母、数字、汉字、下划线和短横线，最长 32 个字符。",
    "err.no_token": "服务端未设置 ADA_TOKEN，规划会失败。请在启动 server.py 的终端里先 export ADA_TOKEN。", "err.no_backend": "无法连接后端服务。",
    "profile.enter": "请输入档案 ID。", "profile.info": "档案「{id}」：{members}（更新于 {updated}）", "profile.allergy": "·{a}过敏",
    "profile.missing_quiet": "档案「{id}」还不存在，规划成功后会自动保存。", "profile.missing": "未找到档案：{msg}",
    "profile.confirm_delete": "确定删除档案「{id}」吗？", "profile.deleted": "已删除档案「{id}」。", "profile.not_exist": "档案「{id}」不存在。",
    "profile.delete_failed": "删除失败：{msg}",
    "lang.switch": "切换语言",
    // shared
    "sep": "、", "colon": "：", "source": "来源：", "updated": "更新", "reason": "Agent 理由：", "total": "合计", "per_adult": " / 成人",
    "age": "（{n} 岁）", "hours": "{n} 小时", "minutes": "约 {n} 分钟", "km": "{n} 公里", "nights": "{n} 晚", "rooms": "{n} 间", "people": "{n} 人",
    // overview
    "ov.inbound": "入境游", "ov.approval": "需要审批", "ov.no_approval": "无需审批", "ov.saved": "已保存到档案 {id}",
    "ov.fallback": "模型行程失败，已用规则生成", "ov.route": "路线", "ov.route_v": "{o} → {d}（约 {km} 公里，{scope}）",
    "ov.domestic": "国内", "ov.cross": "跨境", "ov.dates": "日期", "ov.dates_v": "{a} 至 {b}（{n} 晚）", "ov.members": "出行人",
    "ov.purpose": "目的", "ov.prefs": "偏好", "ov.nat": "国籍 / 语言", "ov.weather": "天气", "ov.total": "预计总费用",
    "ov.total_home": "（约 {v}）", "ov.coupon_off": "，已扣优惠券 {v}",
    // members
    "mem.h": "同行人与约束", "mem.cols": ["称呼", "年龄", "行动", "过敏", "饮食", "家庭"], "mem.walk": "，≤{n} km/天",
    "mem.rules_h": "规划约束（由规则生成，先过滤候选，再复核模型结果）", "mem.excluded": "已排除 {p} 个景点、{r} 家餐厅",
    // transport / hotel / ground
    "tr.h": "城际交通", "tr.out": "去程", "tr.back": "返程", "tr.rail": "高铁", "tr.flight": "航班", "tr.pref_air": "协议航司",
    "tr.stops": " · 经停 {n} 次", "tr.party": " · 全员 {v}", "tr.filtered": "已按同行人约束排除 {n} 个过早、过晚或红眼班次",
    "ho.h": "酒店", "ho.stars": "{n} 星", "ho.pref": "协议酒店", "ho.kids": "儿童设施", "ho.access": "无障碍", "ho.english": "英文服务",
    "ho.dist": "距市中心 {n} 公里", "ho.bf": "含早", "ho.no_bf": "不含早", "ho.price": "{room} {p} / 晚 × {r} 间 × {n} 晚 = {t}",
    "ho.cap": "住宿标准：标准间 {v} / 晚", "ho.relaxed": "没有找到满足全部设施要求的酒店，已放宽条件。", "ho.none": "当天往返，无需住宿",
    "gr.h": "接送", "gr.arr": "抵达", "gr.dep": "离开", "gr.pref": "协议", "gr.seat": "儿童座椅", "gr.prepay": "可在携程预付",
    // cost
    "co.h": "费用估算", "co.caption": "演示价格；酒店和接送按房间、车辆计", "co.coupons": "合作景点优惠券", "co.after": "优惠后",
    "co.home": "折合本币", "co.budget": "预算", "co.in_budget": "预算内", "co.over_budget": "超预算", "co.by_person": "按人查看",
    "co.per_caption": "按人拆分（儿童、长者按年龄计价）", "co.per_cols": ["出行人", "交通", "门票", "餐饮"],
    "co.split_h": "多家庭分摊", "co.split_caption": "个人费用按实际计，酒店和接送按人数分摊", "co.split_cols": ["家庭", "人数", "个人费用", "分摊", "合计"],
    "co.item.transport": "城际交通（往返 × {n} 人）", "co.item.hotel": "酒店 {n} 晚 × {r} 间（{room}）", "co.item.hotel_none": "酒店（无需住宿）",
    "co.item.transfer": "接送（抵达 + 离开）", "co.item.tickets": "景点门票（{n} 个景点）", "co.item.meals": "餐饮估算（{n} 餐）",
    // itinerary
    "it.h": "逐日行程（已结合天气）", "it.day_stats": "景点 {n} 个 · 景点步行约 {km} 公里", "it.indoor": "室内", "it.outdoor": "户外",
    "it.poi_line": "{cat} · {io} · 约 {h} 小时 · 步行约 {km} 公里", "it.pp": "人均 {v}", "it.kid_menu": "儿童餐", "it.en_menu": "英文菜单",
    "it.card": "可刷境外卡", "it.cash": "仅扫码/现金", "it.swapped": "因天气调整", "it.rain_backup": "雨天备选（室内）",
    "it.rain_line": "{name}（{cat}，约 {h} 小时）", "it.wx_fixes": "天气复核：调整 {n} 处", "it.wx_alert": "天气提醒：",
    "it.fixes": "约束复核：自动修正 {n} 处", "it.rain": " · 雨 {p}%",
    // weather
    "wx.h": "目的地天气 · {city}（{src}）", "wx.day_meta": "降雨概率最高 {p}% · 紫外线 {uv}", "wx.clothing": "穿衣：",
    "wx.block_meta": "雨 {p}% · 体感 {a}–{b}°C", "wx.alerts": "天气预警",
    // trending & coupons
    "hot.h": "热门景点推荐（相似游客行程）", "hot.basis.web": "相似游客攻略（网页检索）", "hot.basis.builtin": "内置热度（未获得检索结果）",
    "hot.prov_ok": "{n} 条", "hot.prov_none": "无结果", "hot.prov_unconfigured": "未配置", "hot.no_catalog": "该城市暂无景点目录数据。",
    "hot.insights": "相似游客的行程规律", "hot.planned": "已安排进行程", "hot.optional": "可选", "hot.excluded": "不适合本次同行人",
    "hot.mentions": "{n} 篇攻略提到", "hot.meta": "{cat} · {io} · 约 {h} 小时 · 成人 {p}", "hot.why_excluded": "原因：",
    "hot.others": "攻略中提到的其他地点（暂未合作，未纳入行程）", "hot.queries": "检索词与全部结果", "hot.no_results": "没有检索结果。",
    "hot.analysis_failed": "模型分析失败，已按提及次数排序：",
    "cp.h": "合作景点优惠券", "cp.in_plan": "行程内可用（合计可省 {v}）", "cp.more": "其他热门合作景点", "cp.note": "优惠券为演示数据，实际以携程活动页面为准。",
    "cp.save": "本次可省 {v}", "cp.unavailable": "不可用", "cp.demo": "演示", "cp.code": "券码 ", "cp.valid": " · {partner} · 有效期至 {d}",
    "cp.use": "；在携程预付门票时使用", "cp.why": "；不可用原因：{r}", "cp.pct": "门票 {n} 折", "cp.amt": "立减 ¥{n}", "cp.per": "/人", "cp.order": "/单",
    // reminders
    "rm.h": "出行提醒", "rm.weather": "🌦️ 天气", "rm.network": "📶 网络变化与应对", "rm.impact": "影响：", "rm.action": "建议：",
    "rm.guides": "携程官方指南：", "rm.all_guides": "全部携程官方入境指南", "rm.checked": "链接于 {d} 核实可访问。",
    "rm.cash": "💴 人民币零钱", "rm.cash_line": "建议 {n} 人共准备 ", "rm.cash_after": " 现金{home}，面额：",
    "rm.cash_detail": "按天和地点查看（估算 {a}，取整后 {b}）", "rm.cash_cols": ["日期", "地点", "金额", "理由"], "rm.tips": "📝 行程提醒",
    // checks / inbound / share
    "ck.h": "合规与约束检查", "ck.caption": "规则引擎检查，结果可复现", "ck.cols": ["检查项", "结果", "说明"],
    "ib.h": "入境准备清单", "ib.visa": "签证", "ib.kb": "知识库更新：{d}。政策会变化，请以官方公告为准。",
    "pp.h": "支付计划", "pp.prepay": "建议提前在携程用境外银行卡预付", "pp.prepay_cols": ["项目", "金额"], "pp.prepay_total": "携程预付合计",
    "pp.onsite": "现场支付", "pp.onsite_cols": ["项目", "方式", "金额"], "pp.onsite_total": "现场支付合计",
    "pp.cash": "建议准备现金：", "pp.cash_see": "（明细见“出行提醒 · 人民币零钱”）",
    "pp.method.qr": "扫码支付", "pp.method.qr_card": "扫码 / 境外卡", "pp.method.qr_cash": "仅扫码或现金",
    "ph.pay": "付款沟通卡（出示给收银员）", "ph.emergency": "紧急求助", "ph.diet": "饮食提示卡（出示给餐厅）",
    "sh.h": "智能分享", "sh.lang": "语言", "sh.btn": "生成分享文案", "sh.loading": "生成中…", "sh.copy": "复制", "sh.copied": "已复制",
    "sh.copy_failed": "复制失败，请手动选择", "sh.system": "系统分享", "sh.caption": "照片配文：", "sh.failed": "生成失败：{msg}",
    "sh.note": "文案不包含酒店、班次、时间和同行人信息。通过系统分享面板，用你自己的网络发布到常用的社交平台。",
  },
  en: {
    "page.title": "Trip Planner · Multi-Agent", "header.title": "Trip Planner · Multi-Agent", "header.sub": "Business / Family / Inbound travel",
    "plan.h": "Plan a trip", "plan.query_label": "Describe your trip (中文, English, 日本語 or 한국어)",
    "plan.query_ph": "e.g. Oct 24, Shanghai to Hangzhou for 3 days with my 5-year-old (peanut allergy) and 70-year-old grandma",
    "plan.profile_label": "Family profile ID (optional: saves traveller details for next time)", "plan.profile_ph": "e.g. zhang-family",
    "btn.view": "View", "btn.delete": "Delete", "btn.plan": "Plan my trip", "btn.planning": "Planning…", "chips.aria": "Example requests",
    "chip.biz.tag": "Business", "chip.biz": "Shanghai → Singapore client visit",
    "chip.fam1.tag": "Family", "chip.fam1": "Grandma + kid + allergy",
    "chip.fam2.tag": "Family", "chip.fam2": "With a stroller",
    "chip.multi.tag": "Two families", "chip.multi": "Split the bill",
    "chip.mem.tag": "Memory", "chip.mem": "Second trip (uses profile)",
    "chip.in1.tag": "Inbound", "chip.in1": "American couple → Beijing",
    "chip.in2.tag": "Inbound", "chip.in2": "Japanese family → Shanghai",
    "steps.h": "Agent progress", "step.running": "Running…", "step.failed": "Failed: {msg}", "step.done": "Done",
    "ask.h": "Inbound assistant (visa / payment / internet)", "ask.q_label": "Question", "ask.lang_label": "Answer language", "ask.btn": "Ask",
    "ask.note": "Answers come only from the knowledge base, with sources. Never enter card numbers, CVV, passwords or codes.",
    "ask.loading": "Searching the knowledge base…", "ask.no_kb": "No verified information in the knowledge base; no answer generated.",
    "ask.failed": "Question failed: {msg}",
    "rc.h": "Receipt scanner & expenses", "rc.file_label": "Take or choose a photo of a Chinese receipt (JPG / PNG / WebP, ≤ 5 MB)",
    "rc.lang_label": "Translate to", "rc.cur_label": "Home currency", "rc.list_h": "Expenses", "rc.empty": "No records yet.", "rc.csv": "Export CSV",
    "rc.note": "Images are used only for this recognition and are not stored on the server.", "rc.too_big": "Images must be 5 MB or smaller.",
    "rc.loading": "Recognising…", "rc.failed": "Recognition failed: {msg}", "rc.no_date": "date not recognised",
    "result.empty": "Describe your trip to see destination weather, traveller constraints, trending attractions and coupons, transport, hotel, a weather-aware day-by-day itinerary, compliance checks, cost split, travel reminders (internet changes, RMB cash), entry preparation and share text.",
    "result.loading": "The agents are working on your plan; this usually takes 30–90 seconds…",
    "plan.done": "Plan ready in {s} s", "plan.failed": "Planning failed: {msg}", "plan.disconnected": "Lost connection to the server. Make sure server.py is still running.",
    "err.profile_id": "Profile IDs may contain letters, digits, Chinese characters, underscores and hyphens (max 32).",
    "err.no_token": "ADA_TOKEN is not set on the server, so planning will fail. Export ADA_TOKEN in the terminal before starting server.py.",
    "err.no_backend": "Cannot reach the backend.",
    "profile.enter": "Enter a profile ID.", "profile.info": "Profile “{id}”: {members} (updated {updated})", "profile.allergy": " · allergic to {a}",
    "profile.missing_quiet": "Profile “{id}” doesn't exist yet; it will be saved after a successful plan.", "profile.missing": "Profile not found: {msg}",
    "profile.confirm_delete": "Delete profile “{id}”?", "profile.deleted": "Profile “{id}” deleted.", "profile.not_exist": "Profile “{id}” doesn't exist.",
    "profile.delete_failed": "Delete failed: {msg}",
    "lang.switch": "Switch language",
    "sep": ", ", "colon": ": ", "source": "Source: ", "updated": "updated", "reason": "Agent's reasoning: ", "total": "Total", "per_adult": " / adult",
    "age": " ({n})", "hours": "{n} h", "minutes": "about {n} min", "km": "{n} km", "nights": "{n} nights", "rooms": "{n} room(s)", "people": "{n} people",
    "ov.inbound": "Inbound", "ov.approval": "Approval required", "ov.no_approval": "No approval needed", "ov.saved": "Saved to profile {id}",
    "ov.fallback": "Model itinerary failed; rule-based plan shown", "ov.route": "Route", "ov.route_v": "{o} → {d} (about {km} km, {scope})",
    "ov.domestic": "domestic", "ov.cross": "cross-border", "ov.dates": "Dates", "ov.dates_v": "{a} to {b} ({n} nights)", "ov.members": "Travellers",
    "ov.purpose": "Purpose", "ov.prefs": "Preferences", "ov.nat": "Nationality / language", "ov.weather": "Weather", "ov.total": "Estimated total",
    "ov.total_home": " (≈ {v})", "ov.coupon_off": ", after {v} in coupons",
    "mem.h": "Travellers & constraints", "mem.cols": ["Who", "Age", "Mobility", "Allergies", "Diet", "Family"], "mem.walk": ", ≤{n} km/day",
    "mem.rules_h": "Planning constraints (rule-based: candidates are filtered first, the model's plan is re-checked)",
    "mem.excluded": "Excluded {p} attractions and {r} restaurants",
    "tr.h": "Intercity transport", "tr.out": "Outbound", "tr.back": "Return", "tr.rail": "Rail", "tr.flight": "Flight", "tr.pref_air": "Preferred airline",
    "tr.stops": " · {n} stop(s)", "tr.party": " · group {v}", "tr.filtered": "{n} early, late or red-eye options excluded for your group",
    "ho.h": "Hotel", "ho.stars": "{n}-star", "ho.pref": "Preferred hotel", "ho.kids": "Kids' facilities", "ho.access": "Accessible", "ho.english": "English service",
    "ho.dist": "{n} km from centre", "ho.bf": "breakfast included", "ho.no_bf": "no breakfast", "ho.price": "{room} {p} / night × {r} room(s) × {n} nights = {t}",
    "ho.cap": "Policy cap: standard room {v} / night", "ho.relaxed": "No hotel met every facility requirement, so the criteria were relaxed.", "ho.none": "Same-day trip, no hotel needed",
    "gr.h": "Transfers", "gr.arr": "Arrival", "gr.dep": "Departure", "gr.pref": "Preferred", "gr.seat": "Child seat", "gr.prepay": "Prepay on Trip.com",
    "co.h": "Cost estimate", "co.caption": "Demo prices; hotel and transfers are per room / vehicle", "co.coupons": "Partner coupons", "co.after": "After coupons",
    "co.home": "In home currency", "co.budget": "Budget", "co.in_budget": "Within budget", "co.over_budget": "Over budget", "co.by_person": "Per person",
    "co.per_caption": "Per person (children and seniors priced by age)", "co.per_cols": ["Traveller", "Transport", "Tickets", "Meals"],
    "co.split_h": "Split between families", "co.split_caption": "Personal costs as incurred; hotel and transfers shared per head",
    "co.split_cols": ["Family", "People", "Personal", "Shared", "Total"],
    "co.item.transport": "Intercity transport (return × {n})", "co.item.hotel": "Hotel {n} nights × {r} room(s) ({room})", "co.item.hotel_none": "Hotel (none)",
    "co.item.transfer": "Transfers (arrival + departure)", "co.item.tickets": "Tickets ({n} attractions)", "co.item.meals": "Meals estimate ({n} meals)",
    "it.h": "Day-by-day itinerary (weather-aware)", "it.day_stats": "{n} attraction(s) · about {km} km walking", "it.indoor": "indoor", "it.outdoor": "outdoor",
    "it.poi_line": "{cat} · {io} · about {h} h · about {km} km walking", "it.pp": "{v} per person", "it.kid_menu": "kids' menu", "it.en_menu": "English menu",
    "it.card": "foreign cards OK", "it.cash": "QR / cash only", "it.swapped": "Changed for weather", "it.rain_backup": "Rainy-day backups (indoor)",
    "it.rain_line": "{name} ({cat}, about {h} h)", "it.wx_fixes": "Weather check: {n} change(s)", "it.wx_alert": "Weather warning: ",
    "it.fixes": "Constraint check: {n} automatic fix(es)", "it.rain": " · rain {p}%",
    "wx.h": "Destination weather · {city} ({src})", "wx.day_meta": "max rain chance {p}% · UV {uv}", "wx.clothing": "What to wear: ",
    "wx.block_meta": "rain {p}% · feels {a}–{b}°C", "wx.alerts": "Weather alerts",
    "hot.h": "Trending attractions (similar travellers)", "hot.basis.web": "Similar travellers' guides (web search)", "hot.basis.builtin": "Built-in popularity (no search results)",
    "hot.prov_ok": "{n} results", "hot.prov_none": "no results", "hot.prov_unconfigured": "not configured", "hot.no_catalog": "No attraction catalogue for this city yet.",
    "hot.insights": "Patterns from similar trips", "hot.planned": "In your itinerary", "hot.optional": "Optional", "hot.excluded": "Not suitable for this group",
    "hot.mentions": "mentioned in {n} guide(s)", "hot.meta": "{cat} · {io} · about {h} h · adult {p}", "hot.why_excluded": "Reason: ",
    "hot.others": "Other places mentioned in guides (not partners, not in the itinerary)", "hot.queries": "Search queries and all results",
    "hot.no_results": "No search results.", "hot.analysis_failed": "Model analysis failed; sorted by mentions: ",
    "cp.h": "Partner attraction coupons", "cp.in_plan": "Usable on this trip (save {v} in total)", "cp.more": "Other trending partner attractions",
    "cp.note": "Coupons are demo data; the Trip.com promotion page is authoritative.", "cp.save": "Save {v} on this trip", "cp.unavailable": "Not available",
    "cp.demo": "Demo", "cp.code": "Code ", "cp.valid": " · {partner} · valid until {d}", "cp.use": "; apply when prepaying tickets on Trip.com",
    "cp.why": "; not available: {r}", "cp.pct": "{n}% off tickets", "cp.amt": "¥{n} off", "cp.per": " per person", "cp.order": " per order",
    "rm.h": "Travel reminders", "rm.weather": "🌦️ Weather", "rm.network": "📶 Internet changes & what to do", "rm.impact": "Impact: ", "rm.action": "What to do: ",
    "rm.guides": "Trip.com guides: ", "rm.all_guides": "All Trip.com guides for visitors to China", "rm.checked": "Links checked on {d}.",
    "rm.cash": "💴 RMB cash", "rm.cash_line": "For {n} people, bring ", "rm.cash_after": " in cash{home}. Notes: ",
    "rm.cash_detail": "By day and place (estimate {a}, rounded to {b})", "rm.cash_cols": ["Date", "Place", "Amount", "Why"], "rm.tips": "📝 Itinerary tips",
    "ck.h": "Compliance & constraint checks", "ck.caption": "Rule-engine checks, reproducible", "ck.cols": ["Check", "Result", "Details"],
    "ib.h": "Entry preparation checklist", "ib.visa": "Visa", "ib.kb": "Knowledge base updated {d}. Policies change; official notices are authoritative.",
    "pp.h": "Payment plan", "pp.prepay": "Prepay on Trip.com with your foreign card", "pp.prepay_cols": ["Item", "Amount"], "pp.prepay_total": "Prepaid total",
    "pp.onsite": "Pay on site", "pp.onsite_cols": ["Item", "Method", "Amount"], "pp.onsite_total": "On-site total",
    "pp.cash": "Suggested cash: ", "pp.cash_see": " (see “Travel reminders · RMB cash”)",
    "pp.method.qr": "QR payment", "pp.method.qr_card": "QR / foreign card", "pp.method.qr_cash": "QR or cash only",
    "ph.pay": "Payment phrase cards (show the cashier)", "ph.emergency": "Emergency help", "ph.diet": "Diet cards (show the restaurant)",
    "sh.h": "Share your trip", "sh.lang": "Language", "sh.btn": "Generate share text", "sh.loading": "Generating…", "sh.copy": "Copy", "sh.copied": "Copied",
    "sh.copy_failed": "Copy failed; please select manually", "sh.system": "Share", "sh.caption": "Photo caption: ", "sh.failed": "Generation failed: {msg}",
    "sh.note": "The text leaves out hotels, flight / train numbers, times and traveller details. Post it through your phone's share sheet over your own network.",
  },
};

// Enumerations: shared keys → labels.
const ENUMS = {
  zh: {
    status: { pass: "通过", warn: "提醒", fail: "违规" },
    trip: { business: "商务出行", family: "家庭游", leisure: "休闲游" },
    mobility: { normal: "正常", limited: "行动较慢", wheelchair: "轮椅" },
    diet: { none: "", halal: "清真", vegetarian: "素食" },
    phase: { before: "入境前", arrival: "抵达当天", during: "行程中" },
    item: { transport: "交通", hotel: "酒店", poi: "景点", meal: "用餐", rest: "休息", work: "工作", free: "自由活动" },
  },
  en: {
    status: { pass: "Pass", warn: "Warning", fail: "Fail" },
    trip: { business: "Business", family: "Family trip", leisure: "Leisure" },
    mobility: { normal: "Normal", limited: "Slower walker", wheelchair: "Wheelchair" },
    diet: { none: "", halal: "Halal", vegetarian: "Vegetarian" },
    phase: { before: "Before arrival", arrival: "Arrival day", during: "During the trip" },
    item: { transport: "Transport", hotel: "Hotel", poi: "Attraction", meal: "Meal", rest: "Rest", work: "Work", free: "Free time" },
  },
};

// English for Chinese values that come from the backend's demo data.
const ZH_EN = {
  上海: "Shanghai", 北京: "Beijing", 深圳: "Shenzhen", 成都: "Chengdu", 杭州: "Hangzhou", 西安: "Xi'an", 香港: "Hong Kong",
  新加坡: "Singapore", 东京: "Tokyo", 首尔: "Seoul", 伦敦: "London", 纽约: "New York",
  经济舱: "Economy", 公务舱: "Business", 二等座: "2nd class", 一等座: "1st class", 中国铁路: "China Railway",
  "地铁/机场快线": "Metro / airport express", 出租车: "Taxi", 企业协议专车: "Corporate car service", "7座商务车（可预约儿童座椅）": "7-seat van (child seat available)",
  家庭房: "Family room", 标准间: "Standard room",
  市中心: "City centre", 中央商务区: "CBD", 景区附近: "Near attractions", 会展中心: "Convention centre", "机场/车站附近": "Near airport / station",
  主题乐园: "Theme park", 城市漫步: "City walk", 博物馆: "Museum", 古典园林: "Classical garden", 观光: "Sightseeing", 历史古迹: "Historic site",
  皇家园林: "Imperial garden", 自然风光: "Scenery", 寺庙: "Temple", 动物园: "Zoo", 主题演出: "Show", 艺术展: "Art exhibition",
  中式家常菜: "Chinese home cooking", 海鲜: "Seafood", 西式简餐: "Western casual", 素食: "Vegetarian", 清真菜: "Halal", 面食小吃: "Noodles & snacks",
  餐饮: "Dining", 交通: "Transport", 购物: "Shopping", 门票: "Tickets", 住宿: "Lodging", 其他: "Other",
  博查: "Bocha",
  中国东方航空: "China Eastern", 中国国际航空: "Air China", 中国南方航空: "China Southern", 海南航空: "Hainan Airlines", 春秋航空: "Spring Airlines",
  新加坡航空: "Singapore Airlines", 国泰航空: "Cathay Pacific", 全日空: "ANA", 英国航空: "British Airways",
  去程舱位: "Outbound cabin", 返程舱位: "Return cabin", 去程最低价: "Outbound lowest fare", 返程最低价: "Return lowest fare", 提前预订: "Advance booking",
  住宿标准: "Hotel cap", 协议供应商: "Preferred suppliers", 去程时间: "Outbound timing", 返程时间: "Return timing",
  景点与餐厅约束: "Attraction & restaurant constraints", 每日景点数: "Attractions per day", 每日步行: "Daily walking", 午休时段: "Nap window",
  天气适配: "Weather fit", 过敏与饮食: "Allergies & diet", 过敏信息确认: "Allergy confirmation", 酒店设施: "Hotel facilities", 儿童座椅: "Child seat", 预算: "Budget",
};

const LANGS = ["zh", "en"];
let LANG = (() => {
  const saved = localStorage.getItem("uiLang");
  if (LANGS.includes(saved)) return saved;
  return (navigator.language || "zh").toLowerCase().startsWith("zh") ? "zh" : "en";
})();

function t(key, vars) {
  let s = I18N[LANG][key];
  if (s === undefined) s = I18N.zh[key];
  if (s === undefined) return key;
  if (Array.isArray(s) || !vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (vars[k] !== undefined && vars[k] !== null ? String(vars[k]) : m));
}
const en = () => LANG === "en";
const E = (group, key) => (ENUMS[LANG][group] || {})[key] ?? key;
// Translate a backend Chinese value when the UI is English (unknown values pass through unchanged).
const tz = (value) => (en() && value && ZH_EN[value] ? ZH_EN[value] : value);
// Pick `field_en` over `field` when the UI is English and an English version exists.
const pick = (obj, field) => (obj && en() && obj[field + "_en"] ? obj[field + "_en"] : obj ? obj[field] : "");

function applyStatic() {
  document.documentElement.lang = en() ? "en" : "zh-CN";
  document.title = t("page.title");
  for (const node of document.querySelectorAll("[data-i18n]")) node.textContent = t(node.dataset.i18n);
  for (const node of document.querySelectorAll("[data-i18n-ph]")) node.setAttribute("placeholder", t(node.dataset.i18nPh));
  for (const node of document.querySelectorAll("[data-i18n-aria]")) node.setAttribute("aria-label", t(node.dataset.i18nAria));
  for (const btn of document.querySelectorAll(".lang-btn")) btn.setAttribute("aria-pressed", String(btn.dataset.lang === LANG));
}
