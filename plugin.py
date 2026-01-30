import random
import re
import os
import json
import tomllib
from typing import List, Tuple, Type, Any, Optional, Dict
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    BaseTool,
    ComponentInfo,
    ConfigField,
    EventType,
    MaiMessages,
    ToolParamType,
)
from src.common.logger import get_logger

logger = get_logger("coc_dice_plugin")

# ===================== 角色数据持久化存储 =====================
CHAR_DATA_PATH = os.path.join(os.path.dirname(__file__), "character_data.json")

def load_character_data() -> Dict[str, Dict[str, Any]]:
    """加载用户角色数据（持久化，新增昵称字段）"""
    try:
        if os.path.exists(CHAR_DATA_PATH):
            with open(CHAR_DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"加载角色数据失败：{e}")
        return {}

def save_character_data(char_data: Dict[str, Dict[str, Any]]) -> bool:
    """保存用户角色数据（持久化，包含昵称）"""
    try:
        os.makedirs(os.path.dirname(__file__), exist_ok=True)
        with open(CHAR_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(char_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存角色数据失败：{e}")
        return False

USER_CHARACTER_DATA = load_character_data()

# ===================== 预设属性映射（新增核心属性分类） =====================
# 基础属性映射（含HP/MP/SAN + 伤害加值/闪避/移动力）
BASE_ATTR_MAP = {
    "生命": ("HP", "❤️生命(HP)"),
    "魔力": ("MP", "🧪魔力(MP)"),
    "理智": ("SAN", "🌀理智(SAN)"),
    "力量": ("STR", "💪力量(STR)"),
    "体质": ("CON", "🛡️体质(CON)"),
    "体型": ("SIZ", "📏体型(SIZ)"),
    "敏捷": ("DEX", "🏃敏捷(DEX)"),
    "外貌": ("APP", "✨外貌(APP)"),
    "智力": ("INT", "🧠智力(INT)"),
    "意志": ("POW", "🔮意志(POW)"),
    "教育": ("EDU", "📚教育(EDU)"),
    "幸运": ("LUCK", "🍀幸运(LUCK)"),
    "伤害加值": ("DB", "💥伤害加值(DB)"),
    "闪避": ("DODGE", "🤸闪避(DODGE)"),
    "移动力": ("MOV", "⚡移动力(MOV)")
}

# 属性/技能别名映射表
ATTR_ALIAS_MAP = {
    # 基础属性
    "str": "力量", "💪力量(str)": "力量",
    "con": "体质", "🛡️体质(con)": "体质",
    "siz": "体型", "📏体型(siz)": "体型",
    "dex": "敏捷", "🏃敏捷(dex)": "敏捷",
    "app": "外貌", "✨外貌(app)": "外貌",
    "int": "智力", "灵感": "智力", "🧠智力(int)": "智力",
    "pow": "意志", "🔮意志(pow)": "意志",
    "edu": "教育", "📚教育(edu)": "教育",
    "luck": "幸运", "运气": "幸运", "🍀幸运(luck)": "幸运",
    # 自动计算项
    "hp": "生命", "体力": "生命", "❤️生命(hp)": "生命",
    "mp": "魔力", "魔法": "魔力", "🧪魔力(mp)": "魔力",
    "san": "理智", "理智值": "理智", "san值": "理智", "🌀理智(san)": "理智",
    "db": "伤害加值", "💥伤害加值(db)": "伤害加值",
    "dodge": "闪避", "🤸闪避(dodge)": "闪避",
    "mov": "移动力", "⚡移动力(mov)": "移动力",
    # 常见技能别名
    "计算机使用": "计算机", "电脑": "计算机",
    "信誉": "信用", "信用评级": "信用",
    "克苏鲁神话": "克苏鲁", "cm": "克苏鲁",
    "汽车驾驶": "驾驶", "汽车": "驾驶",
    "图书馆使用": "图书馆",
    "撬锁": "开锁", "锁匠": "开锁",
    "自然学": "博物学",
    "重型机械": "重型操作", "操作重型机械": "重型操作", "重型": "重型操作",
}

# 新增：核心基础属性缩写（计入总属性）
CORE_BASE_ATTR_SHORTS = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU", "LUCK"]
# 新增：自动计算属性缩写（不计入总属性）
AUTO_CALC_ATTR_SHORTS = ["HP", "MP", "SAN", "DB", "DODGE", "MOV"]

DERIVED_ATTRS = {}
FORBIDDEN_ATTRS = set()

BASE_ATTR_NAMES = set(BASE_ATTR_MAP.keys())
BASE_ATTR_TO_SHORT = {name: short for name, (short, full) in BASE_ATTR_MAP.items()}
SHORT_TO_BASE_ATTR = {short: name for name, (short, full) in BASE_ATTR_MAP.items()}

# ===================== 快捷指令映射 =====================
SHORT_CMD_MAP = {
    "r": "掷骰",
    "rd": "检定",
    "st": "导入",
    "del": "删除",
    "del_all": "删除角色",
    "qs": "查询技能",
    "sc": "san检定",
    "nn": "改名"
}

# ===================== 配置文件相关 =====================
def get_plugin_config() -> Dict[str, Any]:
    """读取配置文件（热重载）"""
    config_path = os.path.join(os.path.dirname(__file__), "config.toml")
    default_config = {
        "plugin": {"config_version": "1.0.0", "enabled": True},
        "dice": {
            "show_detail": True,
            "success_threshold": 5,
            "fail_threshold": 96,
            "default_message": "🎲 骰子投掷完成！",
            "roll_template": """🎲 {nickname}投掷「{表达式}」结果：
{原因说明}
单次结果：{单次结果}
修正值：{修正值}
总计：{总计}
{判定结果}""",
            "check_template": """🎲 {nickname}的检定（阈值：{阈值}）
{reason_desc}
投掷结果：{投掷结果}
{判定结果}""",
            "san_check_template": """🎲 🌀 {nickname}的SAN值（理智）检定
{reason_desc}
{nickname}的当前SAN值：{current_san}（检定阈值）
D100投掷结果：{roll_result}
{judge_result}
➡️ 扣除SAN值：{deduct_value}（{deduct_type}）
🔹 扣除前SAN值：{before_san}
🔹 扣除后SAN值：{after_san}
"""
        },
        "character": {
            "output_template": """🎭 {nickname}的角色属性：
{属性列表}
📊 核心基础属性总值：{总属性}
""",
            "query_template": """🎭 {nickname}的绑定角色属性：
{基础属性列表}
📊 核心基础属性总数：{基础总属性}
""",
            "skill_query_template": """🎭 {nickname}的角色技能列表：
{技能列表}
📊 技能总数：{skill_count}
""",
            "single_skill_template": """🎭 {nickname}的角色技能/属性查询结果：
🔹 {skill_name}：{skill_value}
"""
        },
        "import_attr": {
            "success_template": """✅ {nickname}的角色属性修改/新增成功！
{自动创建提示}
修改/新增的属性：
{修改列表}
📊 当前核心基础属性总值：{基础总属性}
""",
            "auto_create_tip": "🔔 检测到你未创建角色，已自动生成预设属性并新增/覆盖指定值！",
            "update_tip": "🔔 已新增/覆盖你指定的属性值！",
            "error_template": """❌ 属性修改失败：
{错误原因}
💡 正确格式：/st 力量80敏捷75 或 /st 力量80 感知75（属性值范围0-200）
💡 基础属性：{基础属性列表}
"""
        },
        "delete_attr": {
            "success_template": """✅ {nickname}的角色属性操作成功！
{操作描述}
📊 当前核心基础属性总值：{基础总属性}
""",
            "delete_role_template": """✅ {nickname}的角色已删除成功！
你的所有角色数据已清空，可发送「/创建角色」重新生成。""",
            "error_template": """❌ 属性操作失败：
{错误原因}
💡 支持的操作：
1. /删除 [基础属性名] → 重置为默认值（如/删除 力量）
2. /删除 [自定义技能名] → 直接删除（如/删除 感知）
"""
        },
        "rename": {
            "success_template": """✅ {old_nickname}的角色已成功改名为「{new_nickname}」！
""",
            "error_template": """❌ 角色改名失败：
{错误原因}
💡 正确格式：/nn [新昵称]（如/nn 冒险者小明）"""
        }
    }

    try:
        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                user_config = tomllib.load(f)
                for section in default_config.keys():
                    if section in user_config:
                        default_config[section].update(user_config[section])
        return default_config
    except Exception as e:
        logger.error(f"读取配置文件失败：{e}")
        return default_config

# ===================== 工具函数 =====================
def render_template(template: str, data: Dict[str, Any]) -> str:
    """模板渲染（兼容未定义变量，支持昵称字段）"""
    try:
        return template.format(** data)
    except KeyError as e:
        logger.warning(f"模板变量缺失：{e}")
        rendered = template
        for key, value in data.items():
            rendered = rendered.replace(f"{{{key}}}", str(value))
        return rendered

def parse_dice_expression(expr: str) -> Tuple[int, int, int]:
    """解析骰子表达式（支持d100、2d6+3等）"""
    pattern = r"^(\d*)d(\d+)([+-]\d+)?$"
    match = re.match(pattern, expr.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"无效的骰子表达式：{expr}（格式示例：d100、2d6+3）")

    count = int(match.group(1)) if match.group(1) else 1
    face = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0

    if count <= 0 or count > 100:
        raise ValueError(f"骰子数量{count}超出范围（1-100）")
    if face <= 0 or face > 1000:
        raise ValueError(f"骰子面数{face}超出范围（1-1000）")
    return count, face, modifier

def roll_dice(count: int, face: int, modifier: int = 0) -> Tuple[List[int], int]:
    """执行骰子投掷"""
    rolls = [random.randint(1, face) for _ in range(count)]
    total = sum(rolls) + modifier
    return rolls, total

def split_check_params(params: str) -> Tuple[str, str]:
    """拆分检定参数（第一个参数+剩余原因）"""
    if not params.strip():
        return "", ""
    parts = params.strip().split(" ", 1)
    return parts[0], parts[1] if len(parts) > 1 else ""

def parse_import_attr_params(params: str) -> Dict[str, int]:
    """解析导入属性参数（支持伤害加值表达式）"""
    if not params.strip():
        raise ValueError("未输入任何属性参数")

    attr_dict = {}
    
    # 正则逻辑：
    # ([^\d\s+-]+) -> 匹配非数字、非空格、非正负号的字符作为“键”
    # ([\d+-]+(?:d\d+)?) -> 匹配数字或 1d6 这种骰子表达式作为“值”
    pattern = re.compile(r'([^\d\s+-]+)\s*([\d+-]+(?:d\d+)?)')
    matches = pattern.findall(params)
    
    if not matches:
        raise ValueError("无法识别属性格式。正确示例：/st 力量60str60 或 伤害加值1d4")

    for raw_name, value_str in matches:
        # 1. 统一名称转换 (别名过滤)
        attr_name = raw_name.strip().lower()
        standard_name = ATTR_ALIAS_MAP.get(attr_name, raw_name.strip())

        # 2. 解析数值
        try:
            if "d" in value_str.lower():
                # 处理骰子表达式 (如 1d4, 2d6+3)
                count, face, modifier = parse_dice_expression(value_str)
                _, total = roll_dice(count, face, modifier)
                attr_value = total
            else:
                # 纯数字解析
                attr_value = int(value_str)
        except Exception:
            # 如果解析失败（比如 1d6 格式写错），跳过该项或报错
            continue

        # 3. 校验范围并存入字典 (同属性会被后面的覆盖，例如 str60 会覆盖 力量60)
        attr_value = max(0, min(200, attr_value))
        attr_dict[standard_name] = attr_value
    
    return attr_dict

def parse_damage_bonus_value(damage_bonus_str: str) -> int:
    """解析伤害加值字符串并计算实际数值"""
    if damage_bonus_str.lstrip('-').isdigit():
        return int(damage_bonus_str)
    
    try:
        dice_pattern = r"^(\d+)d(\d+)$"
        match = re.match(dice_pattern, damage_bonus_str)
        if match:
            count = int(match.group(1))
            face = int(match.group(2))
            rolls, total = roll_dice(count, face)
            return total
    except Exception as e:
        logger.error(f"解析伤害加值失败：{damage_bonus_str}，错误：{e}")
    
    return 0

def parse_san_deduct_value(expr: str) -> int:
    """解析SAN值扣除值"""
    if expr.lstrip('-').isdigit():
        val = int(expr)
        return max(val, 1)
    
    try:
        count, face, modifier = parse_dice_expression(expr)
        rolls, total = roll_dice(count, face, modifier)
        return max(total, 1)
    except Exception as e:
        logger.error(f"解析SAN扣除值失败：{expr}，错误：{e}")
        return 1

def get_character_nickname(user_id: str, user_nickname: str = "") -> str:
    """获取角色昵称（优先角色绑定昵称，无则用用户昵称）"""
    if user_id in USER_CHARACTER_DATA and "昵称" in USER_CHARACTER_DATA[user_id]:
        return USER_CHARACTER_DATA[user_id]["昵称"]
    return user_nickname or "未知角色"

# ===================== 初始属性计算函数 =====================
def calculate_damage_bonus(str_value: int, siz_value: int) -> int:
    """计算伤害加值初始值"""
    total = str_value + siz_value
    damage_bonus_expr = ""
    if 2 <= total <= 64:
        damage_bonus_expr = "-2"
    elif 65 <= total <= 84:
        damage_bonus_expr = "-1"
    elif 85 <= total <= 124:
        damage_bonus_expr = "0"
    elif 125 <= total <= 164:
        damage_bonus_expr = "1d4"
    elif 165 <= total <= 204:
        damage_bonus_expr = "1d6"
    elif total >= 205:
        damage_bonus_expr = "2d6"
    else:
        damage_bonus_expr = "-2"
    
    return parse_damage_bonus_value(damage_bonus_expr)

def calculate_dodge(dex_value: int) -> int:
    """计算闪避初始值"""
    return dex_value // 2

def calculate_movement(dex_value: int, str_value: int, siz_value: int) -> int:
    """计算移动力初始值"""
    if dex_value < siz_value and str_value < siz_value:
        return 7
    elif dex_value > siz_value and str_value > siz_value:
        return 9
    else:
        return 8

# ===================== 角色属性生成/格式化（核心修改） =====================
def generate_character_attributes(nickname: str) -> Dict[str, Any]:
    """生成预设基础属性（包含昵称，仅核心属性计入总值）"""
    attr_results = {}
    
    # 角色昵称
    attr_results["昵称"] = nickname
    
    # HP/MP/SAN默认值（不计入总值）
    attr_results["HP"] = 12
    attr_results["MP"] = 10
    attr_results["SAN"] = 50
    
    # 常规公式：3d6×5（核心基础属性）
    normal_attrs = ["STR", "CON", "DEX", "APP", "POW", "LUCK"]
    for short in normal_attrs:
        rolls, sum_3d6 = roll_dice(3, 6)
        attr_results[short] = sum_3d6 * 5
    
    # SIZ/INT/EDU公式为(2D6+6)×5（核心基础属性）
    special_attrs = ["SIZ", "INT", "EDU"]
    for short in special_attrs:
        rolls, sum_2d6 = roll_dice(2, 6)
        attr_results[short] = (sum_2d6 + 6) * 5
    
    # 计算自动计算属性（不计入总值）
    str_val = attr_results["STR"]
    siz_val = attr_results["SIZ"]
    dex_val = attr_results["DEX"]
    
    attr_results["DB"] = calculate_damage_bonus(str_val, siz_val)
    attr_results["DODGE"] = calculate_dodge(dex_val)
    attr_results["MOV"] = calculate_movement(dex_val, str_val, siz_val)
    
    # 核心修改：仅计算核心基础属性的总和
    base_total = sum([attr_results[short] for short in CORE_BASE_ATTR_SHORTS])
    attr_results["基础总属性"] = base_total
    return attr_results

def generate_single_base_attr(attr_name: str) -> int:
    """生成单个基础属性的默认值"""
    if attr_name not in BASE_ATTR_TO_SHORT:
        raise ValueError(f"{attr_name}不是基础属性，无法生成默认值")
    short_name = BASE_ATTR_TO_SHORT[attr_name]
    
    if short_name in ["HP", "MP", "SAN"]:
        defaults = {"HP": 12, "MP": 10, "SAN": 50}
        return defaults[short_name]
    
    if short_name in ["STR", "CON", "DEX", "APP", "POW", "LUCK"]:
        rolls, sum_3d6 = roll_dice(3, 6)
        return sum_3d6 * 5
    
    if short_name in ["SIZ", "INT", "EDU"]:
        rolls, sum_2d6 = roll_dice(2, 6)
        return (sum_2d6 + 6) * 5
    
    if short_name == "DB":
        str_val = generate_single_base_attr("力量")
        siz_val = generate_single_base_attr("体型")
        return calculate_damage_bonus(str_val, siz_val)
    elif short_name == "DODGE":
        dex_val = generate_single_base_attr("敏捷")
        return calculate_dodge(dex_val)
    elif short_name == "MOV":
        dex_val = generate_single_base_attr("敏捷")
        str_val = generate_single_base_attr("力量")
        siz_val = generate_single_base_attr("体型")
        return calculate_movement(dex_val, str_val, siz_val)
    
    return 0

def format_character_attributes(char_data: Dict[str, Any]) -> Tuple[str, str, int, Dict[str, str]]:
    """格式化角色属性（核心修改：仅核心属性计入总值）"""
    base_attr_lines = []
    # 核心修改：初始化base_total为0，仅累加核心基础属性
    base_total = 0
    
    for attr_name, (short_name, full_name) in BASE_ATTR_MAP.items():
        value = char_data.get(short_name, 0)
        base_attr_lines.append(f"🔹 {full_name}：{value}")
        # 仅核心基础属性计入总值
        if short_name in CORE_BASE_ATTR_SHORTS:
            base_total += value
    
    derived_attr_str = ""
    derived_attr_values = {}
    
    base_attr_str = "\n".join(base_attr_lines) if base_attr_lines else "暂无基础属性"
    
    return base_attr_str, derived_attr_str, base_total, derived_attr_values

def get_character_skills(char_data: Dict[str, Any]) -> Tuple[List[str], int]:
    """提取角色技能"""
    exclude_keys = set(SHORT_TO_BASE_ATTR.keys()) | set(["基础总属性", "总属性", "昵称"])
    skill_lines = []
    for key, value in char_data.items():
        if key not in exclude_keys:
            skill_lines.append(f"🔹 {key}：{value}")
    
    return skill_lines, len(skill_lines)

# ===================== 获取单个技能/属性值 =====================
def get_single_skill_value(skill_name: str, char_data: Dict[str, Any]) -> Tuple[bool, str, Any]:
    """获取单个技能/属性的值"""
    if skill_name in BASE_ATTR_NAMES:
        short_name = BASE_ATTR_TO_SHORT[skill_name]
        value = char_data.get(short_name, 0)
        full_name = BASE_ATTR_MAP[skill_name][1]
        return True, full_name, value
    
    exclude_keys = set(SHORT_TO_BASE_ATTR.keys()) | set(["基础总属性", "总属性", "昵称"])
    if skill_name in char_data and skill_name not in exclude_keys:
        value = char_data[skill_name]
        return True, skill_name, value
    
    return False, skill_name, None

# ===================== 删除属性/角色核心函数（核心修改） =====================
def delete_character_attribute(user_id: str, attr_name: str) -> Tuple[bool, str, Dict[str, Any]]:
    """删除/重置角色属性/技能（核心修改：重新计算总属性时仅算核心属性）"""
    if user_id not in USER_CHARACTER_DATA:
        return False, "你还未创建角色，无属性/技能可删除！", {}

    user_char = USER_CHARACTER_DATA[user_id].copy()

    if attr_name in BASE_ATTR_NAMES:
        short_name = BASE_ATTR_TO_SHORT[attr_name]
        old_value = user_char.get(short_name, 0)
        new_value = generate_single_base_attr(attr_name)
        user_char[short_name] = new_value

        # 核心修改：仅计算核心基础属性的总和
        base_total = sum([user_char.get(short, 0) for short in CORE_BASE_ATTR_SHORTS])
        user_char["基础总属性"] = base_total

        return True, f"基础属性-{attr_name}已重置为默认值：{old_value} → {new_value}", user_char

    elif attr_name in user_char and attr_name not in SHORT_TO_BASE_ATTR.keys() and attr_name not in ["基础总属性", "总属性", "昵称"]:
        old_value = user_char[attr_name]
        del user_char[attr_name]

        # 核心修改：仅计算核心基础属性的总和
        base_total = sum([user_char.get(short, 0) for short in CORE_BASE_ATTR_SHORTS])
        user_char["基础总属性"] = base_total

        return True, f"技能-{attr_name}已删除（原值：{old_value}）", user_char

    else:
        return False, f"未找到属性/技能「{attr_name}」，无法删除！", user_char

def delete_character(user_id: str) -> bool:
    """删除整个角色数据"""
    if user_id in USER_CHARACTER_DATA:
        del USER_CHARACTER_DATA[user_id]
        save_character_data(USER_CHARACTER_DATA)
        return True
    return False

def rename_character(user_id: str, new_nickname: str) -> Tuple[bool, str]:
    """修改角色昵称"""
    if not new_nickname.strip():
        return False, "新昵称不能为空！"
    
    if user_id not in USER_CHARACTER_DATA:
        return False, "你还未创建角色，无法改名！请先发送/创建角色。"
    
    user_char = USER_CHARACTER_DATA[user_id].copy()
    old_nickname = user_char.get("昵称", "未知角色")
    user_char["昵称"] = new_nickname.strip()
    USER_CHARACTER_DATA[user_id] = user_char
    save_character_data(USER_CHARACTER_DATA)
    
    return True, f"{old_nickname}→{new_nickname}"

# ===================== LLM调用工具 =====================
class CoCDiceTool(BaseTool):
    """CoC骰子工具（LLM调用）"""
    name = "coc_dice_tool"
    description = "跑团骰子投掷工具，支持D100/2d6等格式，返回投掷结果"
    parameters = [
        ("dice_expr", ToolParamType.STRING, "骰子表达式（如d100、2d6+3）", True, None),
    ]
    available_for_llm = True

    async def execute(self, function_args: dict[str, Any]) -> dict[str, Any]:
        dice_expr = function_args.get("dice_expr", "")
        if not dice_expr:
            error_msg = "错误：未提供骰子表达式"
            await self.send_text(error_msg)
            return {"name": self.name, "content": error_msg}

        try:
            config = get_plugin_config()
            count, face, modifier = parse_dice_expression(dice_expr)
            rolls, total = roll_dice(count, face, modifier)

            roll_detail = " + ".join(map(str, rolls))
            modifier_str = f"{'+' if modifier > 0 else '-'}{abs(modifier)}" if modifier != 0 else "无"
            success_thresh = config["dice"]["success_threshold"]
            fail_thresh = config["dice"]["fail_threshold"]

            judge_result = ""
            if face == 100 and count == 1:
                if total <= success_thresh:
                    judge_result = "✨ 大成功！"
                elif total >= fail_thresh:
                    judge_result = "💥 大失败！"

            # 获取角色昵称
            user_id = None
            user_nickname = "未知角色"
            try:
                if (hasattr(self.message, 'message_info') and
                    hasattr(self.message.message_info, 'user_info')):
                    user_id = str(self.message.message_info.user_info.user_id)
                    user_nickname = self.message.message_info.user_info.user_nickname or "未知角色"
            except Exception as e:
                logger.error(f"获取用户信息失败：{e}")
            nickname = get_character_nickname(user_id, user_nickname)

            roll_data = {
                "nickname": nickname,
                "表达式": dice_expr,
                "原因说明": "",
                "单次结果": roll_detail,
                "修正值": modifier_str,
                "总计": total,
                "判定结果": judge_result.strip()
            }

            result_msg = render_template(config["dice"]["roll_template"], roll_data)
            await self.send_text(result_msg)
            return {"name": self.name, "content": result_msg}

        except ValueError as e:
            error_msg = f"骰子投掷失败：{str(e)}"
            await self.send_text(error_msg)
            return {"name": self.name, "content": error_msg}
        except Exception as e:
            error_msg = f"未知错误：{str(e)}"
            await self.send_text(error_msg)
            return {"name": self.name, "content": error_msg}

# ===================== 核心命令处理 =====================
class CoCDiceCommand(BaseCommand):
    """核心命令处理类"""
    command_name = "coc_dice_command"
    command_description = f"""骰子/角色管理插件
用法：
1. /r [表达式] [原因] → 投掷骰子（如/r d100 探索密室）
2. /rd [参数] [原因] → 检定（支持三种模式）
   - 模式1：/rd [阈值] [原因]（如/rd 70 躲避陷阱）
   - 模式2：/rd [属性/技能名] [原因]（如/rd 力量、/rd 伤害加值）
   - 模式3：/rd [属性+修正值] [原因]（如/rd 力量+10、/rd 伤害加值-5）
3. /sc [成功扣除/失败扣除] [原因] → SAN值（理智）检定（如/sc 1d5/1d6 目睹怪物、/sc 5/6 看到诡异场景）
   - 规则：以当前SAN值为阈值掷D100
     - 结果 < SAN值：检定成功，扣除「成功扣除」值（1d5/5）
     - 结果 > SAN值：检定失败，扣除「失败扣除」值（1d6/6）
     - SAN值最低为0，不会出现负数
4. /创建角色 [昵称] → 生成预设基础属性（含伤害加值/闪避/移动力初始值）
   - 示例：/创建角色 冒险者小明（自定义昵称）
   - 无昵称时自动使用你的平台昵称
5. /查询角色 → 查看所有属性（所有属性均可手动修改）
6. /查询技能 → 查看所有自定义技能（非属性项）
   /查询技能 [属性/技能名] → 单独查看指定技能/属性的值（如/查询技能 伤害加值、/查询技能 闪避）
7. /st/导入 [属性数值] → 新增/修改属性/技能（支持伤害加值表达式）
   示例：/st 力量80 伤害加值1d4 → 伤害加值自动掷骰为数值存储
   属性值范围：0-200
8. /删除/ del [属性/技能名] → 删除/重置属性/技能
   - 基础属性（含伤害加值/闪避/移动力）：重置为默认值
   - 自定义技能：直接删除
9. /删除角色/ del_all → 删除整个角色数据（所有属性+技能清空）
10. /nn [新昵称] → 修改角色昵称（如/nn 勇者小刚）
支持的基础属性：{', '.join(BASE_ATTR_NAMES)}
⚠️ 生命/魔力/理智/伤害加值/闪避/移动力为自动计算属性，不计入总属性值
"""

    command_pattern = r"^/(r|rd|st|导入|del|删除|del_all|删除角色|掷骰|检定|创建角色|查询角色|查询技能|qs|sc|san检定|nn|改名)(\s+.*)?$"

    async def execute(self) -> Tuple[bool, str, bool]:
        global USER_CHARACTER_DATA

        # 提取用户ID和昵称
        user_id = None
        user_nickname = "未知角色"
        try:
            if (hasattr(self.message, 'message_info') and
                hasattr(self.message.message_info, 'user_info')):
                user_id = str(self.message.message_info.user_info.user_id)
                user_nickname = self.message.message_info.user_info.user_nickname or "未知角色"
        except Exception as e:
            logger.error(f"提取用户信息失败：{e}")

        if not user_id:
            error_msg = "❌ 无法获取你的用户ID，无法执行指令！"
            await self.send_text(error_msg)
            return False, error_msg, True

        # 解析指令
        raw_msg = self.message.raw_message.strip()
        cmd_prefix = re.match(r"^/(\w+)", raw_msg).group(1) if re.match(r"^/(\w+)", raw_msg) else ""
        if cmd_prefix in SHORT_CMD_MAP:
            original_cmd = SHORT_CMD_MAP[cmd_prefix]
            raw_msg = raw_msg.replace(f"/{cmd_prefix}", f"/{original_cmd}", 1)
            cmd_prefix = original_cmd

        params = raw_msg[len(f"/{cmd_prefix}"):].strip()
        config = get_plugin_config()
        # 获取角色昵称（用于输出）
        nickname = get_character_nickname(user_id, user_nickname)

        # ========== 0. 处理/改名指令 ==========
        if cmd_prefix == "改名":
            new_nickname = params.strip()
            try:
                success, msg = rename_character(user_id, new_nickname)
                if success:
                    old_nickname, new_nick = msg.split("→")
                    rename_data = {
                        "old_nickname": old_nickname,
                        "new_nickname": new_nick
                    }
                    success_msg = render_template(config["rename"]["success_template"], rename_data)
                    await self.send_text(success_msg)
                    return True, success_msg, True
                else:
                    error_data = {"错误原因": msg}
                    error_msg = render_template(config["rename"]["error_template"], error_data)
                    await self.send_text(error_msg)
                    return False, error_msg, True
            except Exception as e:
                error_data = {"错误原因": str(e)}
                error_msg = render_template(config["rename"]["error_template"], error_data)
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 1. 处理/导入指令 ==========
        elif cmd_prefix == "导入":
            try:
                import_attr_dict = parse_import_attr_params(params)

                is_auto_create = False
                if user_id not in USER_CHARACTER_DATA:
                    # 自动创建角色时使用用户昵称
                    USER_CHARACTER_DATA[user_id] = generate_character_attributes(user_nickname)
                    is_auto_create = True
                    nickname = user_nickname  # 更新昵称

                user_char = USER_CHARACTER_DATA[user_id].copy()
                modified_attrs = []
                for attr_name, attr_value in import_attr_dict.items():
                    if attr_name in BASE_ATTR_TO_SHORT:
                        attr_short = BASE_ATTR_TO_SHORT[attr_name]
                        old_value = user_char.get(attr_short, 0)
                        user_char[attr_short] = attr_value
                        modified_attrs.append(f"🔹 基础属性-{attr_name}({attr_short})：{old_value} → {attr_value}")
                    else:
                        old_value = user_char.get(attr_name, "无")
                        user_char[attr_name] = attr_value
                        modified_attrs.append(f"🔹 技能-{attr_name}：{old_value} → {attr_value}")

                # 核心修改：仅计算核心基础属性的总和
                base_total = sum([user_char.get(short, 0) for short in CORE_BASE_ATTR_SHORTS])
                user_char["基础总属性"] = base_total

                USER_CHARACTER_DATA[user_id] = user_char
                save_character_data(USER_CHARACTER_DATA)

                auto_create_tip = config["import_attr"]["auto_create_tip"] if is_auto_create else config["import_attr"]["update_tip"]
                import_data = {
                    "nickname": nickname,
                    "自动创建提示": auto_create_tip,
                    "修改列表": "\n".join(modified_attrs),
                    "基础总属性": base_total
                }
                success_msg = render_template(config["import_attr"]["success_template"], import_data)
                await self.send_text(success_msg)
                return True, success_msg, True

            except ValueError as e:
                error_data = {"错误原因": str(e), "基础属性列表": ", ".join(BASE_ATTR_NAMES)}
                error_msg = render_template(config["import_attr"]["error_template"], error_data)
                await self.send_text(error_msg)
                return False, error_msg, True
            except Exception as e:
                error_msg = f"❌ {nickname}的属性导入出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 2. 处理/检定指令 ==========
        elif cmd_prefix == "检定":
            first_param, reason = split_check_params(params)
            if not first_param:
                error_msg = f"""❌ {nickname}的检定缺少参数！支持三种用法：
1. /rd [阈值] [原因]（如/rd 70 躲避陷阱）
2. /rd [属性/技能名] [原因]（如/rd 力量、/rd 伤害加值）
3. /rd [属性+修正值] [原因]（如/rd 力量+10、/rd 伤害加值-5）
"""
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                check_threshold = None
                attr_name = None
                attr_type = ""
                modifier = 0
                base_value = 0

                attr_mod_pattern = re.compile(r'^([^\+\-]+)([\+\-]\d+)$')
                mod_match = attr_mod_pattern.match(first_param)
                
                if mod_match:
                    attr_name = mod_match.group(1).strip()
                    modifier_str = mod_match.group(2).strip()
                    
                    try:
                        modifier = int(modifier_str)
                    except ValueError:
                        error_msg = f"❌ {nickname}的修正值格式错误：{modifier_str}（必须是整数，如+10、-5）"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                    
                    if user_id not in USER_CHARACTER_DATA:
                        error_msg = f"❌ {nickname}还未创建角色！无法获取「{attr_name}」值。"
                        await self.send_text(error_msg)
                        return False, error_msg, True

                    user_char = USER_CHARACTER_DATA[user_id]
                    exists, show_name, base_value = get_single_skill_value(attr_name, user_char)
                    if not exists:
                        error_msg = f"❌ {nickname}未找到属性/技能「{attr_name}」！"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                    
                    check_threshold = base_value + modifier
                    attr_type = "基础属性" if attr_name in BASE_ATTR_NAMES else "自定义技能"
                    
                    if check_threshold < 0 or check_threshold > 199:
                        error_msg = f"❌ {nickname}的「{attr_name}」基础值{base_value}{modifier_str}={check_threshold}，超出检定阈值范围（0-199）！"
                        await self.send_text(error_msg)
                        return False, error_msg, True

                elif first_param.isdigit():
                    check_threshold = int(first_param)
                    attr_type = "阈值"
                    if check_threshold < 0 or check_threshold > 199:
                        error_msg = f"❌ {nickname}的检定阈值范围必须是1-199！"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                else:
                    attr_name = first_param
                    if user_id not in USER_CHARACTER_DATA:
                        error_msg = f"❌ {nickname}还未创建角色！无法获取「{attr_name}」值。"
                        await self.send_text(error_msg)
                        return False, error_msg, True

                    user_char = USER_CHARACTER_DATA[user_id]
                    exists, show_name, base_value = get_single_skill_value(attr_name, user_char)
                    if not exists:
                        error_msg = f"❌ {nickname}未找到属性/技能「{attr_name}」！"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                    
                    check_threshold = base_value
                    attr_type = "基础属性" if attr_name in BASE_ATTR_NAMES else "自定义技能"

                    if not isinstance(check_threshold, int) or check_threshold < 0 or check_threshold > 200:
                        error_msg = f"❌ {nickname}的「{attr_name}」值异常（{check_threshold}），无法检定！"
                        await self.send_text(error_msg)
                        return False, error_msg, True

                rolls, total = roll_dice(1, 100)
                success_thresh = config["dice"]["success_threshold"]
                fail_thresh = config["dice"]["fail_threshold"]

                if total <= success_thresh:
                    judge_result = "✨ 大成功！"
                elif total <= check_threshold:
                    judge_result = "✅ 检定成功！"
                elif total >= fail_thresh:
                    judge_result = "💥 大失败！"
                else:
                    judge_result = "❌ 检定失败！"

                reason_desc = f"{nickname}因为{reason}所以进行" if reason else f"{nickname}进行"
                if attr_name:
                    if modifier != 0:
                        check_template = f"""🎲 {attr_type}-{attr_name}检定（修正后阈值：{check_threshold}）
{reason_desc}「{attr_name}」{attr_type}检定
🔹 {attr_name}基础值：{base_value}
🔹 修正值：{modifier}
🔹 最终检定阈值：{check_threshold}
投掷结果：{total}
{judge_result}
"""
                        msg = check_template
                    else:
                        check_template = f"""🎲 {attr_type}-{attr_name}检定（阈值：{check_threshold}）
{reason_desc}「{attr_name}」{attr_type}检定
{nickname}的{attr_name}{attr_type}值：{check_threshold}
投掷结果：{total}
{judge_result}
"""
                        msg = check_template
                else:
                    check_data = {
                        "nickname": nickname,
                        "阈值": check_threshold,
                        "reason_desc": f"{reason_desc}D100检定",
                        "投掷结果": total,
                        "判定结果": judge_result
                    }
                    msg = render_template(config["dice"]["check_template"], check_data)

                await self.send_text(msg)
                return True, msg, True

            except Exception as e:
                error_msg = f"❌ {nickname}的检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 3. 处理/san检定指令 ==========
        elif cmd_prefix == "san检定":
            if not params.strip():
                error_msg = f"""❌ {nickname}的SAN检定缺少参数！支持用法：
/sc [成功扣除/失败扣除] [原因]（如/sc 1d5/1d6 目睹怪物、/sc 5/6 看到诡异场景）
规则：
- 结果 < SAN值：检定成功，扣除「成功扣除」值
- 结果 > SAN值：检定失败，扣除「失败扣除」值
"""
                await self.send_text(error_msg)
                return False, error_msg, True

            rule_part, reason = split_check_params(params)
            if not rule_part or "/" not in rule_part:
                error_msg = f"""❌ {nickname}的SAN检定参数格式错误！
正确格式：/sc 成功扣除/失败扣除 [原因]（如/sc 1d5/1d6 目睹怪物、/sc 5/6 看到诡异场景）
- 成功扣除：检定成功时扣除的SAN值（支持骰子表达式/纯数字）
- 失败扣除：检定失败时扣除的SAN值（支持骰子表达式/纯数字）
"""
                await self.send_text(error_msg)
                return False, error_msg, True

            success_deduct_expr, fail_deduct_expr = rule_part.split("/", 1)
            success_deduct_expr = success_deduct_expr.strip()
            fail_deduct_expr = fail_deduct_expr.strip()

            try:
                if user_id not in USER_CHARACTER_DATA:
                    error_msg = f"❌ {nickname}还未创建角色！无法进行SAN值检定，请先发送/创建角色。"
                    await self.send_text(error_msg)
                    return False, error_msg, True

                user_char = USER_CHARACTER_DATA[user_id].copy()
                current_san = user_char.get("SAN", 0)
                if current_san <= 0:
                    error_msg = f"❌ {nickname}的当前SAN值为{current_san}，无法进行SAN检定！"
                    await self.send_text(error_msg)
                    return False, error_msg, True

                rolls, roll_result = roll_dice(1, 100)
                before_san = current_san
                deduct_value = 0
                deduct_type = ""
                judge_result = ""

                if roll_result < current_san:
                    judge_result = "✅ SAN检定成功！"
                    deduct_value = parse_san_deduct_value(success_deduct_expr)
                    deduct_type = f"成功扣除（{success_deduct_expr}）"
                else:
                    judge_result = "❌ SAN检定失败！"
                    deduct_value = parse_san_deduct_value(fail_deduct_expr)
                    deduct_type = f"失败扣除（{fail_deduct_expr}）"

                after_san = max(before_san - deduct_value, 0)
                user_char["SAN"] = after_san

                # 核心修改：仅计算核心基础属性的总和
                base_total = sum([user_char.get(short, 0) for short in CORE_BASE_ATTR_SHORTS])
                user_char["基础总属性"] = base_total

                USER_CHARACTER_DATA[user_id] = user_char
                save_character_data(USER_CHARACTER_DATA)

                reason_desc = f"{nickname}因为{reason}所以进行" if reason else f"{nickname}进行"
                san_data = {
                    "nickname": nickname,
                    "reason_desc": reason_desc,
                    "current_san": current_san,
                    "roll_result": roll_result,
                    "judge_result": judge_result,
                    "deduct_value": deduct_value,
                    "deduct_type": deduct_type,
                    "before_san": before_san,
                    "after_san": after_san
                }
                msg = render_template(config["dice"]["san_check_template"], san_data)

                await self.send_text(msg)
                return True, msg, True

            except Exception as e:
                error_msg = f"❌ {nickname}的SAN检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 4. 处理/删除指令 ==========
        elif cmd_prefix == "删除":
            attr_name = params.strip()
            if not attr_name:
                error_msg = f"""❌ {nickname}的属性删除缺少参数！
用法：/删除 [属性/技能名]（如/删除 力量、/删除 伤害加值）
- 基础属性（含伤害加值/闪避/移动力）：重置为默认值
- 自定义技能：直接删除
"""
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                success, op_desc, user_char = delete_character_attribute(user_id, attr_name)

                if success:
                    base_total = sum([user_char.get(short, 0) for short in CORE_BASE_ATTR_SHORTS])
                    USER_CHARACTER_DATA[user_id] = user_char
                    save_character_data(USER_CHARACTER_DATA)
                    delete_data = {
                        "nickname": nickname,
                        "操作描述": op_desc,
                        "基础总属性": base_total
                    }
                    success_msg = render_template(config["delete_attr"]["success_template"], delete_data)
                    await self.send_text(success_msg)
                    return True, success_msg, True
                else:
                    error_data = {"错误原因": op_desc}
                    error_msg = render_template(config["delete_attr"]["error_template"], error_data)
                    await self.send_text(error_msg)
                    return False, error_msg, True

            except Exception as e:
                error_msg = f"❌ {nickname}的属性删除出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 5. 处理/删除角色指令 ==========
        elif cmd_prefix == "删除角色":
            if params:
                error_msg = f"❌ {nickname}的/删除角色命令无需参数！直接发送即可删除整个角色数据。"
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                if delete_character(user_id):
                    delete_data = {"nickname": nickname}
                    success_msg = render_template(config["delete_attr"]["delete_role_template"], delete_data)
                    await self.send_text(success_msg)
                    return True, success_msg, True
                else:
                    error_msg = f"❌ {nickname}还未创建角色，无角色数据可删除！"
                    await self.send_text(error_msg)
                    return False, error_msg, True

            except Exception as e:
                error_msg = f"❌ {nickname}的角色删除出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 6. 处理/创建角色指令 ==========
        elif cmd_prefix == "创建角色":
            # 解析角色昵称参数（有则用，无则用用户昵称）
            role_nickname = params.strip() if params.strip() else user_nickname
            
            try:
                attr_data = generate_character_attributes(role_nickname)
                USER_CHARACTER_DATA[user_id] = attr_data
                save_character_data(USER_CHARACTER_DATA)
                nickname = role_nickname  # 更新昵称

                base_attr_lines = []
                for attr_name, (short_name, full_name) in BASE_ATTR_MAP.items():
                    base_attr_lines.append(f"🔹 {full_name}：{attr_data.get(short_name, 0)}")
                base_attr_str = "\n".join(base_attr_lines)

                role_data = {
                    "nickname": nickname,
                    "属性列表": base_attr_str,
                    "总属性": attr_data["基础总属性"]
                }
                role_msg = render_template(config["character"]["output_template"], role_data)
                role_msg += f"\n✅ {nickname}的角色创建成功！/st可新增/修改技能，/查询角色查看完整属性"

                await self.send_text(role_msg)
                return True, role_msg, True

            except Exception as e:
                error_msg = f"❌ {nickname}的角色创建出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 7. 处理/查询角色指令 ==========
        elif cmd_prefix == "查询角色":
            if params:
                error_msg = f"❌ {nickname}的/查询角色命令无需参数！"
                await self.send_text(error_msg)
                return False, error_msg, True

            if user_id not in USER_CHARACTER_DATA:
                error_msg = f"❌ {nickname}还未创建角色！可发送/创建角色或/st指令自动创建。"
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                char_data = USER_CHARACTER_DATA[user_id]
                base_attr_str, derived_attr_str, base_total, _ = format_character_attributes(char_data)

                query_data = {
                    "nickname": nickname,
                    "基础属性列表": base_attr_str,
                    "衍生属性列表": derived_attr_str,
                    "基础总属性": base_total
                }
                query_msg = render_template(config["character"]["query_template"], query_data)
                await self.send_text(query_msg)
                return True, query_msg, True

            except Exception as e:
                error_msg = f"❌ {nickname}的角色查询出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 8. 处理/查询技能指令 ==========
        elif cmd_prefix == "查询技能":
            skill_name = params.strip()
            
            if user_id not in USER_CHARACTER_DATA:
                error_msg = f"❌ {nickname}还未创建角色！可发送/创建角色或/st指令自动创建。"
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                char_data = USER_CHARACTER_DATA[user_id]
                
                if skill_name:
                    exists, show_name, value = get_single_skill_value(skill_name, char_data)
                    if exists:
                        single_skill_data = {
                            "nickname": nickname,
                            "skill_name": show_name,
                            "skill_value": value
                        }
                        single_msg = render_template(config["character"]["single_skill_template"], single_skill_data)
                        await self.send_text(single_msg)
                        return True, single_msg, True
                    else:
                        error_msg = f"❌ {nickname}未找到技能/属性「{skill_name}」！"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                else:
                    skill_lines, skill_count = get_character_skills(char_data)
                    
                    if not skill_lines:
                        skill_list = f"暂无自定义技能（可通过/st指令添加，如/st 力量80 伤害加值1d4）\n"
                    else:
                        skill_list = "\n".join(skill_lines)

                    skill_data = {
                        "nickname": nickname,
                        "技能列表": skill_list,
                        "skill_count": skill_count
                    }
                    skill_msg = render_template(config["character"]["skill_query_template"], skill_data)
                    await self.send_text(skill_msg)
                    return True, skill_msg, True

            except Exception as e:
                error_msg = f"❌ {nickname}的技能查询出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 9. 处理/掷骰指令 ==========
        elif cmd_prefix == "掷骰":
            dice_expr, reason = split_check_params(params)
            if not dice_expr:
                error_msg = f"❌ {nickname}的掷骰缺少骰子表达式！示例：/r d100 探索密室。"
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                count, face, modifier = parse_dice_expression(dice_expr)
                rolls, total = roll_dice(count, face, modifier)

                roll_detail = " + ".join(map(str, rolls))
                modifier_str = f"{'+' if modifier > 0 else '-'}{abs(modifier)}" if modifier != 0 else "无"
                success_thresh = config["dice"]["success_threshold"]
                fail_thresh = config["dice"]["fail_threshold"]

                judge_result = ""
                if face == 100 and count == 1:
                    if total <= success_thresh:
                        judge_result = "✨ 大成功！"
                    elif total >= fail_thresh:
                        judge_result = "💥 大失败！"

                roll_data = {
                    "nickname": nickname,
                    "表达式": dice_expr,
                    "原因说明": f"{nickname}因为{reason}所以进行" if reason else f"{nickname}进行",
                    "单次结果": roll_detail,
                    "修正值": modifier_str,
                    "总计": total,
                    "判定结果": judge_result.strip()
                }

                msg = render_template(config["dice"]["roll_template"], roll_data)
                await self.send_text(msg)
                return True, msg, True

            except ValueError as e:
                error_msg = f"❌ {nickname}的{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
            except Exception as e:
                error_msg = f"❌ {nickname}的掷骰出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 非本插件指令，交由其他插件处理 ==========
        else:
            return False, "", False

# ===================== 插件注册 =====================
@register_plugin
class CoCDicePlugin(BasePlugin):
    """插件注册类"""
    plugin_name: str = "coc_dice_plugin"
    enable_plugin: bool = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name: str = "config.toml"

    config_section_descriptions = {
        "plugin": "插件基础配置",
        "dice": "骰子/检定配置",
        "character": "角色配置",
        "import_attr": "属性导入配置",
        "delete_attr": "属性删除配置",
        "rename": "角色改名配置"
    }

    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.0.0", description="配置版本"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件")
        },
        "dice": {
            "show_detail": ConfigField(type=bool, default=True, description="显示投掷详情"),
            "success_threshold": ConfigField(type=int, default=5, description="D100大成功阈值"),
            "fail_threshold": ConfigField(type=int, default=96, description="D100大失败阈值"),
            "default_message": ConfigField(type=str, default="🎲 骰子投掷完成！", description="默认提示"),
            "roll_template": ConfigField(type=str, default=get_plugin_config()["dice"]["roll_template"], description="掷骰模板"),
            "check_template": ConfigField(type=str, default=get_plugin_config()["dice"]["check_template"], description="检定模板"),
            "san_check_template": ConfigField(type=str, default=get_plugin_config()["dice"]["san_check_template"], description="SAN值检定专用模板")
        },
        "character": {
            "output_template": ConfigField(type=str, default=get_plugin_config()["character"]["output_template"], description="创建角色模板"),
            "query_template": ConfigField(type=str, default=get_plugin_config()["character"]["query_template"], description="查询角色模板"),
            "skill_query_template": ConfigField(type=str, default=get_plugin_config()["character"]["skill_query_template"], description="查询技能模板"),
            "single_skill_template": ConfigField(type=str, default=get_plugin_config()["character"]["single_skill_template"], description="单个技能查询模板")
        },
        "import_attr": {
            "success_template": ConfigField(type=str, default=get_plugin_config()["import_attr"]["success_template"], description="导入成功模板"),
            "auto_create_tip": ConfigField(type=str, default=get_plugin_config()["import_attr"]["auto_create_tip"], description="自动创建提示"),
            "update_tip": ConfigField(type=str, default=get_plugin_config()["import_attr"]["update_tip"], description="更新提示"),
            "error_template": ConfigField(type=str, default=get_plugin_config()["import_attr"]["error_template"], description="导入错误模板")
        },
        "delete_attr": {
            "success_template": ConfigField(type=str, default=get_plugin_config()["delete_attr"]["success_template"], description="删除属性成功模板"),
            "delete_role_template": ConfigField(type=str, default=get_plugin_config()["delete_attr"]["delete_role_template"], description="删除角色成功模板"),
            "error_template": ConfigField(type=str, default=get_plugin_config()["delete_attr"]["error_template"], description="删除属性错误模板")
        },
        "rename": {
            "success_template": ConfigField(type=str, default=get_plugin_config()["rename"]["success_template"], description="改名成功模板"),
            "error_template": ConfigField(type=str, default=get_plugin_config()["rename"]["error_template"], description="改名错误模板")
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (CoCDiceTool.get_tool_info(), CoCDiceTool),
            (CoCDiceCommand.get_command_info(), CoCDiceCommand),
        ]

    def on_plugin_stop(self):
        """插件停止时保存数据"""
        global USER_CHARACTER_DATA
        save_character_data(USER_CHARACTER_DATA)
        logger.info("插件停止，角色数据已保存")
