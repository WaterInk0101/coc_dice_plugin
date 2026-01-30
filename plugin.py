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

def load_character_data() -> Dict[str, Dict[str, int]]:
    """加载用户角色数据（持久化）"""
    try:
        if os.path.exists(CHAR_DATA_PATH):
            with open(CHAR_DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"加载角色数据失败：{e}")
        return {}

def save_character_data(char_data: Dict[str, Dict[str, int]]) -> bool:
    """保存用户角色数据（持久化）"""
    try:
        os.makedirs(os.path.dirname(__file__), exist_ok=True)
        with open(CHAR_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(char_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存角色数据失败：{e}")
        return False

USER_CHARACTER_DATA = load_character_data()

# ===================== 预设属性映射（重构：伤害加值/闪避/移动力转为基础属性） =====================
# 基础属性（含HP/MP/SAN + 原衍生属性：伤害加值/闪避/移动力）
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
    "伤害加值": ("DB", "💥伤害加值(DB)"),  # 新增：转为基础属性，缩写DB
    "闪避": ("DODGE", "🤸闪避(DODGE)"),  # 新增：转为基础属性，缩写DODGE
    "移动力": ("MOV", "⚡移动力(MOV)")     # 新增：转为基础属性，缩写MOV
}
# 移除衍生属性定义（全部转为基础属性）
DERIVED_ATTRS = {}
# 移除禁止修改的属性列表（所有属性均可修改）
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
    "sc": "san检定"
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
            "roll_template": """🎲 投掷「{表达式}」结果：
{原因说明}
单次结果：{单次结果}
修正值：{修正值}
总计：{总计}
{判定结果}""",
            "check_template": """🎲 检定（阈值：{阈值}）
{原因说明}
投掷结果：{投掷结果}
{判定结果}""",
            "san_check_template": """🎲 🌀 SAN值（理智）检定
{reason_desc}
你的当前SAN值：{current_san}（检定阈值）
D100投掷结果：{roll_result}
{judge_result}
➡️ 扣除SAN值：{deduct_value}（{deduct_type}）
🔹 扣除前SAN值：{before_san}
🔹 扣除后SAN值：{after_san}"""
        },
        "character": {
            "output_template": """🎭 您的基础属性为：
{属性列表}
📊 预设属性总值：{总属性}
💡 支持导入自定义属性（如/导入 力量80 感知75）""",
            "query_template": """🎭 你的绑定角色属性：
{基础属性列表}
📊 基础属性总数：{基础总属性}
💡 发送「/查询技能」查看所有技能，/rd [属性/技能名] 可检定任意项""",
            "skill_query_template": """🎭 你的角色技能列表：
{技能列表}
📊 技能总数：{skill_count}
💡 发送「/查询角色」查看属性，/rd [技能名] 可检定该技能/属性""",
            "single_skill_template": """🎭 角色技能/属性查询结果：
🔹 {skill_name}：{skill_value}
💡 发送「/查询技能」查看所有技能，/rd {skill_name} 可检定该技能/属性"""
        },
        "import_attr": {
            "success_template": """✅ 角色属性修改/新增成功！
{自动创建提示}
修改/新增的属性：
{修改列表}
📊 当前基础属性总值：{基础总属性}
💡 发送「/查询角色」查看完整属性，/查询技能 查看技能""",
            "auto_create_tip": "🔔 检测到你未创建角色，已自动生成预设属性并新增/覆盖指定值！",
            "update_tip": "🔔 已新增/覆盖你指定的属性值！",
            "error_template": """❌ 属性修改失败：
{错误原因}
💡 正确格式：/st 力量80敏捷75 或 /st 力量80 感知75（属性值范围0-200）
💡 基础属性：{基础属性列表}"""
        },
        "delete_attr": {
            "success_template": """✅ 属性操作成功！
{操作描述}
📊 当前基础属性总值：{基础总属性}
💡 发送「/查询角色」查看最新属性，/查询技能 查看技能""",
            "delete_role_template": """✅ 角色删除成功！
你的所有角色数据已清空，可发送「/创建角色」重新生成。""",
            "error_template": """❌ 属性操作失败：
{错误原因}
💡 支持的操作：
1. /删除 [基础属性名] → 重置为默认值（如/删除 力量）
2. /删除 [自定义技能名] → 直接删除（如/删除 感知）"""
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
    """模板渲染（兼容未定义变量）"""
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
    """
    解析导入属性参数（支持无空格格式，如力量21敏捷43，值范围0-200）
    支持伤害加值的表达式解析（如伤害加值1d4 → 自动掷骰为数值）
    """
    if not params.strip():
        raise ValueError("未输入任何属性参数")

    attr_dict = {}
    # 先按空格拆分（兼容原有格式），再逐个解析无空格的属性值对
    param_parts = params.strip().split()
    
    # 匹配中文属性名+数字/表达式的正则
    attr_pattern = re.compile(r'([^\d]+)([\d+-d]+)')
    
    for part in param_parts:
        # 循环解析单个part中的所有属性值对（如"力量21敏捷43"）
        remaining = part
        while remaining:
            match = attr_pattern.match(remaining)
            if not match:
                raise ValueError(f"属性格式错误：{part}（正确示例：力量80敏捷75 或 伤害加值1d4）")
            
            attr_name = match.group(1).strip()
            value_str = match.group(2).strip()
            remaining = remaining[match.end():]  # 截取剩余部分继续解析
            
            # 处理伤害加值的表达式（如1d4、2d6等）
            attr_value = 0
            if attr_name == "伤害加值":
                try:
                    # 先尝试解析为骰子表达式
                    count, face, modifier = parse_dice_expression(value_str)
                    rolls, total = roll_dice(count, face, modifier)
                    attr_value = total
                    logger.info(f"伤害加值表达式{value_str}解析为数值：{attr_value}")
                except ValueError:
                    # 解析失败则尝试作为纯数字处理
                    if not value_str.lstrip('-').isdigit():
                        raise ValueError(f"伤害加值格式错误：{value_str}（支持纯数字或骰子表达式，如5、1d4）")
                    attr_value = int(value_str)
            else:
                # 其他属性仅支持纯数字
                if not value_str.lstrip('-').isdigit():
                    raise ValueError(f"属性值非法：{attr_name}{value_str}（必须是0-200的整数）")
                attr_value = int(value_str)
            
            # 校验数值范围（0-200）
            if attr_value < 0 or attr_value > 200:
                raise ValueError(f"属性值超出范围：{attr_name}{attr_value}（0-200）")
            
            attr_dict[attr_name] = attr_value
    
    if not attr_dict:
        raise ValueError("未解析到有效的属性参数（正确示例：力量80敏捷75 或 伤害加值1d4）")
    
    return attr_dict

def parse_damage_bonus_value(damage_bonus_str: str) -> int:
    """
    解析伤害加值字符串并计算实际数值（仅用于角色创建时的初始计算）
    支持格式：-2、-1、0、1d4、1d6、2d6
    """
    # 处理固定数值
    if damage_bonus_str.lstrip('-').isdigit():
        return int(damage_bonus_str)
    
    # 处理骰子表达式
    try:
        # 匹配骰子表达式（如1d4、2d6）
        dice_pattern = r"^(\d+)d(\d+)$"
        match = re.match(dice_pattern, damage_bonus_str)
        if match:
            count = int(match.group(1))
            face = int(match.group(2))
            rolls, total = roll_dice(count, face)
            return total
    except Exception as e:
        logger.error(f"解析伤害加值失败：{damage_bonus_str}，错误：{e}")
    
    # 解析失败默认返回0
    return 0

def parse_san_deduct_value(expr: str) -> int:
    """
    解析SAN值扣除值（支持骰子表达式如1d5或纯数字如5）
    :param expr: 扣除值表达式（1d5/5/1d6/6等）
    :return: 实际扣除的数值
    """
    # 处理纯数字
    if expr.lstrip('-').isdigit():
        val = int(expr)
        return max(val, 1)  # 确保至少扣除1点
    
    # 处理骰子表达式
    try:
        count, face, modifier = parse_dice_expression(expr)
        rolls, total = roll_dice(count, face, modifier)
        return max(total, 1)  # 确保至少扣除1点
    except Exception as e:
        logger.error(f"解析SAN扣除值失败：{expr}，错误：{e}")
        return 1  # 解析失败默认扣除1点

# ===================== 初始属性计算函数（仅用于角色创建时生成初始值） =====================
def calculate_damage_bonus(str_value: int, siz_value: int) -> int:
    """计算伤害加值初始值（STR+SIZ总和判断，表达式自动掷骰为数值）"""
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
    
    # 解析表达式为数值
    return parse_damage_bonus_value(damage_bonus_expr)

def calculate_dodge(dex_value: int) -> int:
    """计算闪避初始值（DEX÷2，向下取整）"""
    return dex_value // 2

def calculate_movement(dex_value: int, str_value: int, siz_value: int) -> int:
    """计算移动力初始值"""
    if dex_value < siz_value and str_value < siz_value:
        return 7
    elif dex_value > siz_value and str_value > siz_value:
        return 9
    else:
        return 8

# ===================== 角色属性生成/格式化 =====================
def generate_character_attributes() -> Dict[str, int]:
    """生成预设基础属性（包含伤害加值/闪避/移动力的初始值）"""
    attr_results = {}
    
    # HP/MP/SAN默认值
    attr_results["HP"] = 12
    attr_results["MP"] = 10
    attr_results["SAN"] = 50
    
    # 常规公式：3d6×5
    normal_attrs = ["STR", "CON", "DEX", "APP", "POW", "LUCK"]
    for short in normal_attrs:
        rolls, sum_3d6 = roll_dice(3, 6)
        attr_results[short] = sum_3d6 * 5
    
    # SIZ/INT/EDU公式为(2D6+6)×5
    special_attrs = ["SIZ", "INT", "EDU"]
    for short in special_attrs:
        rolls, sum_2d6 = roll_dice(2, 6)
        attr_results[short] = (sum_2d6 + 6) * 5
    
    # 计算新增基础属性的初始值
    str_val = attr_results["STR"]
    siz_val = attr_results["SIZ"]
    dex_val = attr_results["DEX"]
    
    attr_results["DB"] = calculate_damage_bonus(str_val, siz_val)    # 伤害加值初始值
    attr_results["DODGE"] = calculate_dodge(dex_val)                # 闪避初始值
    attr_results["MOV"] = calculate_movement(dex_val, str_val, siz_val)  # 移动力初始值
    
    # 计算基础属性总值（包含所有基础属性）
    base_total = sum([attr_results[short] for short in SHORT_TO_BASE_ATTR.keys()])
    attr_results["基础总属性"] = base_total
    return attr_results

def generate_single_base_attr(attr_name: str) -> int:
    """生成单个基础属性的默认值（支持伤害加值/闪避/移动力）"""
    if attr_name not in BASE_ATTR_TO_SHORT:
        raise ValueError(f"{attr_name}不是基础属性，无法生成默认值")
    short_name = BASE_ATTR_TO_SHORT[attr_name]
    
    # 基础属性默认值
    if short_name in ["HP", "MP", "SAN"]:
        defaults = {"HP": 12, "MP": 10, "SAN": 50}
        return defaults[short_name]
    
    # 常规属性（3d6×5）
    if short_name in ["STR", "CON", "DEX", "APP", "POW", "LUCK"]:
        rolls, sum_3d6 = roll_dice(3, 6)
        return sum_3d6 * 5
    
    # 特殊属性（(2D6+6)×5）
    if short_name in ["SIZ", "INT", "EDU"]:
        rolls, sum_2d6 = roll_dice(2, 6)
        return (sum_2d6 + 6) * 5
    
    # 新增基础属性的默认值（基于随机生成的STR/SIZ/DEX）
    if short_name == "DB":  # 伤害加值
        str_val = generate_single_base_attr("力量")
        siz_val = generate_single_base_attr("体型")
        return calculate_damage_bonus(str_val, siz_val)
    elif short_name == "DODGE":  # 闪避
        dex_val = generate_single_base_attr("敏捷")
        return calculate_dodge(dex_val)
    elif short_name == "MOV":  # 移动力
        dex_val = generate_single_base_attr("敏捷")
        str_val = generate_single_base_attr("力量")
        siz_val = generate_single_base_attr("体型")
        return calculate_movement(dex_val, str_val, siz_val)
    
    return 0

def format_character_attributes(char_data: Dict[str, int]) -> Tuple[str, str, int, Dict[str, str]]:
    """格式化角色属性（所有属性均为基础属性）"""
    # 处理基础属性（包含伤害加值/闪避/移动力）
    base_attr_lines = []
    base_total = 0
    for attr_name, (short_name, full_name) in BASE_ATTR_MAP.items():
        value = char_data.get(short_name, 0)
        base_attr_lines.append(f"🔹 {full_name}：{value}")
        base_total += value
    
    # 衍生属性已移除，返回空字符串
    derived_attr_str = ""
    derived_attr_values = {}
    
    base_attr_str = "\n".join(base_attr_lines) if base_attr_lines else "暂无基础属性"
    
    return base_attr_str, derived_attr_str, base_total, derived_attr_values

def get_character_skills(char_data: Dict[str, int]) -> Tuple[List[str], int]:
    """提取角色技能（非基础属性/统计项）"""
    exclude_keys = set(SHORT_TO_BASE_ATTR.keys()) | set(["基础总属性", "总属性"])
    skill_lines = []
    for key, value in char_data.items():
        if key not in exclude_keys:
            skill_lines.append(f"🔹 {key}：{value}")
    
    return skill_lines, len(skill_lines)

# ===================== 获取单个技能/属性值 =====================
def get_single_skill_value(skill_name: str, char_data: Dict[str, int]) -> Tuple[bool, str, Any]:
    """
    获取单个技能/属性的值（伤害加值/闪避/移动力作为基础属性处理）
    :param skill_name: 技能/属性名
    :param char_data: 角色数据
    :return: (是否存在, 显示名称, 值)
    """
    # 1. 检查基础属性（包含伤害加值/闪避/移动力）
    if skill_name in BASE_ATTR_NAMES:
        short_name = BASE_ATTR_TO_SHORT[skill_name]
        value = char_data.get(short_name, 0)
        full_name = BASE_ATTR_MAP[skill_name][1]
        return True, full_name, value
    
    # 2. 检查自定义技能
    exclude_keys = set(SHORT_TO_BASE_ATTR.keys()) | set(["基础总属性", "总属性"])
    if skill_name in char_data and skill_name not in exclude_keys:
        value = char_data[skill_name]
        return True, skill_name, value
    
    # 3. 未找到
    return False, skill_name, None

# ===================== 删除属性/角色核心函数 =====================
def delete_character_attribute(user_id: str, attr_name: str) -> Tuple[bool, str, Dict[str, int]]:
    """删除/重置角色属性/技能（所有基础属性均可重置）"""
    if user_id not in USER_CHARACTER_DATA:
        return False, "你还未创建角色，无属性/技能可删除！", {}

    user_char = USER_CHARACTER_DATA[user_id].copy()

    # 1. 基础属性（包括伤害加值/闪避/移动力，重置为默认值）
    if attr_name in BASE_ATTR_NAMES:
        short_name = BASE_ATTR_TO_SHORT[attr_name]
        old_value = user_char.get(short_name, 0)
        new_value = generate_single_base_attr(attr_name)
        user_char[short_name] = new_value

        # 重新计算基础总值
        base_total = sum([user_char.get(short, 0) for short in SHORT_TO_BASE_ATTR.keys()])
        user_char["基础总属性"] = base_total

        return True, f"基础属性-{attr_name}已重置为默认值：{old_value} → {new_value}", user_char

    # 2. 自定义技能（直接删除）
    elif attr_name in user_char and attr_name not in SHORT_TO_BASE_ATTR.keys() and attr_name not in ["基础总属性", "总属性"]:
        old_value = user_char[attr_name]
        del user_char[attr_name]

        # 重新计算基础总值
        base_total = sum([user_char.get(short, 0) for short in SHORT_TO_BASE_ATTR.keys()])
        user_char["基础总属性"] = base_total

        return True, f"技能-{attr_name}已删除（原值：{old_value}）", user_char

    # 3. 属性/技能不存在
    else:
        return False, f"未找到属性/技能「{attr_name}」，无法删除！", user_char

def delete_character(user_id: str) -> bool:
    """删除整个角色数据"""
    if user_id in USER_CHARACTER_DATA:
        del USER_CHARACTER_DATA[user_id]
        save_character_data(USER_CHARACTER_DATA)
        return True
    return False

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

            roll_data = {
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
    command_description = f"""克苏鲁骰子/角色管理插件
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
4. /创建角色 → 生成预设基础属性（含伤害加值/闪避/移动力初始值）
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
支持的基础属性：{', '.join(BASE_ATTR_NAMES)}
所有基础属性均可手动修改（包括伤害加值/闪避/移动力）"""

    command_pattern = r"^/(r|rd|st|导入|del|删除|del_all|删除角色|掷骰|检定|创建角色|查询角色|查询技能|qs|sc|san检定)(\s+.*)?$"

    async def execute(self) -> Tuple[bool, str, bool]:
        global USER_CHARACTER_DATA

        # 提取用户ID
        user_id = None
        try:
            if (hasattr(self.message, 'message_info') and
                hasattr(self.message.message_info, 'user_info') and
                hasattr(self.message.message_info.user_info, 'user_id')):
                user_id = str(self.message.message_info.user_info.user_id)
            else:
                logger.error("无法提取用户ID：属性层级缺失")
        except Exception as e:
            logger.error(f"提取用户ID失败：{e}")

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

        # ========== 1. 处理/导入指令 ==========
        if cmd_prefix == "导入":
            try:
                import_attr_dict = parse_import_attr_params(params)

                is_auto_create = False
                if user_id not in USER_CHARACTER_DATA:
                    USER_CHARACTER_DATA[user_id] = generate_character_attributes()
                    is_auto_create = True

                user_char = USER_CHARACTER_DATA[user_id].copy()
                modified_attrs = []
                for attr_name, attr_value in import_attr_dict.items():
                    if attr_name in BASE_ATTR_TO_SHORT:
                        # 基础属性（用缩写存储）
                        attr_short = BASE_ATTR_TO_SHORT[attr_name]
                        old_value = user_char.get(attr_short, 0)
                        user_char[attr_short] = attr_value
                        modified_attrs.append(f"🔹 基础属性-{attr_name}({attr_short})：{old_value} → {attr_value}")
                    else:
                        # 自定义技能
                        old_value = user_char.get(attr_name, "无")
                        user_char[attr_name] = attr_value
                        modified_attrs.append(f"🔹 技能-{attr_name}：{old_value} → {attr_value}")

                # 重新计算基础总值
                base_total = sum([user_char.get(short, 0) for short in SHORT_TO_BASE_ATTR.keys()])
                user_char["基础总属性"] = base_total

                # 保存并返回结果
                USER_CHARACTER_DATA[user_id] = user_char
                save_character_data(USER_CHARACTER_DATA)

                auto_create_tip = config["import_attr"]["auto_create_tip"] if is_auto_create else config["import_attr"]["update_tip"]
                import_data = {
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
                error_msg = f"❌ 属性导入出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 2. 处理/检定指令 ==========
        elif cmd_prefix == "检定":
            first_param, reason = split_check_params(params)
            if not first_param:
                error_msg = """❌ 缺少检定参数！支持三种用法：
1. /rd [阈值] [原因]（如/rd 70 躲避陷阱）
2. /rd [属性/技能名] [原因]（如/rd 力量、/rd 伤害加值）
3. /rd [属性+修正值] [原因]（如/rd 力量+10、/rd 伤害加值-5）
"""
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                check_threshold = None
                attr_name = None
                attr_type = ""  # 基础属性/自定义技能/阈值
                modifier = 0    # 新增：修正值
                base_value = 0  # 新增：属性基础值

                # 新增：解析属性+修正值格式（如力量+10、伤害加值-5）
                # 匹配包含+/-的属性修正格式（注意+需要转义）
                attr_mod_pattern = re.compile(r'^([^\+\-]+)([\+\-]\d+)$')
                mod_match = attr_mod_pattern.match(first_param)
                
                if mod_match:
                    # 模式3：属性+修正值检定（如力量+10、伤害加值-5）
                    attr_name = mod_match.group(1).strip()
                    modifier_str = mod_match.group(2).strip()
                    
                    # 解析修正值
                    try:
                        modifier = int(modifier_str)
                    except ValueError:
                        error_msg = f"❌ 修正值格式错误：{modifier_str}（必须是整数，如+10、-5）"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                    
                    # 检查角色是否存在
                    if user_id not in USER_CHARACTER_DATA:
                        error_msg = f"❌ 你还未创建角色！无法获取「{attr_name}」值。"
                        await self.send_text(error_msg)
                        return False, error_msg, True

                    user_char = USER_CHARACTER_DATA[user_id]
                    # 获取属性基础值
                    exists, show_name, base_value = get_single_skill_value(attr_name, user_char)
                    if not exists:
                        error_msg = f"❌ 未找到属性/技能「{attr_name}」！"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                    
                    # 计算最终阈值（基础值+修正值）
                    check_threshold = base_value + modifier
                    attr_type = "基础属性" if attr_name in BASE_ATTR_NAMES else "自定义技能"
                    
                    # 校验最终阈值有效性
                    if check_threshold < 1 or check_threshold > 199:
                        error_msg = f"❌ 「{attr_name}」基础值{base_value}{modifier_str}={check_threshold}，超出检定阈值范围（1-199）！"
                        await self.send_text(error_msg)
                        return False, error_msg, True

                elif first_param.isdigit():
                    # 模式1：直接阈值检定（原有逻辑）
                    check_threshold = int(first_param)
                    attr_type = "阈值"
                    if check_threshold < 1 or check_threshold > 199:
                        error_msg = "❌ 检定阈值范围必须是1-199！"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                else:
                    # 模式2：纯属性/技能名检定（原有逻辑）
                    attr_name = first_param
                    if user_id not in USER_CHARACTER_DATA:
                        error_msg = f"❌ 你还未创建角色！无法获取「{attr_name}」值。"
                        await self.send_text(error_msg)
                        return False, error_msg, True

                    user_char = USER_CHARACTER_DATA[user_id]
                    
                    # 获取属性/技能值
                    exists, show_name, base_value = get_single_skill_value(attr_name, user_char)
                    if not exists:
                        error_msg = f"❌ 未找到属性/技能「{attr_name}」！"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                    
                    check_threshold = base_value  # 无修正值，基础值=最终阈值
                    if attr_name in BASE_ATTR_NAMES:
                        attr_type = "基础属性"
                    else:
                        attr_type = "自定义技能"

                    # 验证值有效性
                    if not isinstance(check_threshold, int) or check_threshold < 1 or check_threshold > 200:
                        error_msg = f"❌ 「{attr_name}」值异常（{check_threshold}），无法检定！"
                        await self.send_text(error_msg)
                        return False, error_msg, True

                # 执行D100检定
                rolls, total = roll_dice(1, 100)
                success_thresh = config["dice"]["success_threshold"]
                fail_thresh = config["dice"]["fail_threshold"]

                # 判定结果
                if total <= success_thresh:
                    judge_result = "✨ 大成功！"
                elif total <= check_threshold:
                    judge_result = "✅ 检定成功！"
                elif total >= fail_thresh:
                    judge_result = "💥 大失败！"
                else:
                    judge_result = "❌ 检定失败！"

                # 构建提示信息
                reason_desc = f"因为{reason}所以进行" if reason else "进行"
                if attr_name:
                    # 属性/技能检定提示（含修正值展示）
                    if modifier != 0:
                        # 有修正值的情况，显示基础值+修正值=最终阈值
                        check_template = f"""🎲 {attr_type}-{attr_name}检定
{reason_desc}「{attr_name}」{attr_type}检定
🔹 {attr_name}基础值：{base_value}
🔹 修正值：{modifier}
🔹 最终检定阈值：{check_threshold}
投掷结果：{total}
{judge_result}
"""
                        msg = check_template
                    else:
                        # 无修正值的情况（原有逻辑）
                        check_template = f"""🎲 {attr_type}-{attr_name}检定（阈值：{check_threshold}）
{reason_desc}「{attr_name}」{attr_type}检定
你的{attr_name}{attr_type}值：{check_threshold}
投掷结果：{total}
{judge_result}
"""
                        msg = check_template
                else:
                    # 阈值检定提示（原有逻辑）
                    check_template = f"""🎲 克苏鲁检定（阈值：{check_threshold}）
{reason_desc}D100检定
投掷结果：{total}
{judge_result}"""
                    msg = check_template

                await self.send_text(msg)
                return True, msg, True

            except Exception as e:
                error_msg = f"❌ 检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 3. 处理/san检定指令 ==========
        elif cmd_prefix == "san检定":
            # 拆分参数：扣除规则 + 原因
            if not params.strip():
                error_msg = """❌ 缺少SAN检定参数！支持用法：
/sc [成功扣除/失败扣除] [原因]（如/sc 1d5/1d6 目睹怪物、/sc 5/6 看到诡异场景）
规则：
- 结果 < SAN值：检定成功，扣除「成功扣除」值
- 结果 > SAN值：检定失败，扣除「失败扣除」值
- SAN值最低为0，不会出现负数"""
                await self.send_text(error_msg)
                return False, error_msg, True

            # 拆分扣除规则和原因（第一个参数是扣除规则，剩余是原因）
            rule_part, reason = split_check_params(params)
            if not rule_part or "/" not in rule_part:
                error_msg = """❌ SAN检定参数格式错误！
正确格式：/sc 成功扣除/失败扣除 [原因]（如/sc 1d5/1d6 目睹怪物、/sc 5/6 看到诡异场景）
- 成功扣除：检定成功时扣除的SAN值（支持骰子表达式/纯数字）
- 失败扣除：检定失败时扣除的SAN值（支持骰子表达式/纯数字）"""
                await self.send_text(error_msg)
                return False, error_msg, True

            # 解析成功/失败扣除值
            success_deduct_expr, fail_deduct_expr = rule_part.split("/", 1)
            success_deduct_expr = success_deduct_expr.strip()
            fail_deduct_expr = fail_deduct_expr.strip()

            try:
                # 检查角色是否存在
                if user_id not in USER_CHARACTER_DATA:
                    error_msg = "❌ 你还未创建角色！无法进行SAN值检定，请先发送/创建角色。"
                    await self.send_text(error_msg)
                    return False, error_msg, True

                user_char = USER_CHARACTER_DATA[user_id].copy()
                current_san = user_char.get("SAN", 0)
                if current_san <= 0:
                    error_msg = f"❌ 你的当前SAN值为{current_san}，无法进行SAN检定！"
                    await self.send_text(error_msg)
                    return False, error_msg, True

                # 执行D100检定
                rolls, roll_result = roll_dice(1, 100)
                before_san = current_san
                deduct_value = 0
                deduct_type = ""
                judge_result = ""

                # 判断检定结果
                if roll_result < current_san:
                    # 检定成功
                    judge_result = "✅ SAN检定成功！"
                    deduct_value = parse_san_deduct_value(success_deduct_expr)
                    deduct_type = f"成功扣除（{success_deduct_expr}）"
                else:
                    # 检定失败
                    judge_result = "❌ SAN检定失败！"
                    deduct_value = parse_san_deduct_value(fail_deduct_expr)
                    deduct_type = f"失败扣除（{fail_deduct_expr}）"

                # 计算扣除后的SAN值（最低为0）
                after_san = max(before_san - deduct_value, 0)
                user_char["SAN"] = after_san

                # 重新计算基础总值
                base_total = sum([user_char.get(short, 0) for short in SHORT_TO_BASE_ATTR.keys()])
                user_char["基础总属性"] = base_total

                # 保存修改后的角色数据
                USER_CHARACTER_DATA[user_id] = user_char
                save_character_data(USER_CHARACTER_DATA)

                # 构建提示信息
                reason_desc = f"因为{reason}所以进行" if reason else "进行"
                san_data = {
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
                error_msg = f"❌ SAN检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 4. 处理/删除指令 ==========
        elif cmd_prefix == "删除":
            attr_name = params.strip()
            if not attr_name:
                error_msg = """❌ 缺少属性/技能名参数！
用法：/删除 [属性/技能名]（如/删除 力量、/删除 伤害加值）
- 基础属性（含伤害加值/闪避/移动力）：重置为默认值
- 自定义技能：直接删除"""
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                success, op_desc, user_char = delete_character_attribute(user_id, attr_name)

                if success:
                    base_total = sum([user_char.get(short, 0) for short in SHORT_TO_BASE_ATTR.keys()])
                    USER_CHARACTER_DATA[user_id] = user_char
                    save_character_data(USER_CHARACTER_DATA)
                    delete_data = {
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
                error_msg = f"❌ 删除属性/技能出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 5. 处理/删除角色指令 ==========
        elif cmd_prefix == "删除角色":
            if params:
                error_msg = "❌ /删除角色命令无需参数！直接发送即可删除整个角色数据。"
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                if delete_character(user_id):
                    success_msg = render_template(config["delete_attr"]["delete_role_template"], {})
                    await self.send_text(success_msg)
                    return True, success_msg, True
                else:
                    error_msg = "❌ 你还未创建角色，无角色数据可删除！"
                    await self.send_text(error_msg)
                    return False, error_msg, True

            except Exception as e:
                error_msg = f"❌ 删除角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 6. 处理/创建角色指令 ==========
        elif cmd_prefix == "创建角色":
            if params:
                error_msg = "❌ /创建角色命令无需参数！"
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                attr_data = generate_character_attributes()
                USER_CHARACTER_DATA[user_id] = attr_data
                save_character_data(USER_CHARACTER_DATA)

                base_attr_lines = []
                for attr_name, (short_name, full_name) in BASE_ATTR_MAP.items():
                    base_attr_lines.append(f"🔹 {full_name}：{attr_data.get(short_name, 0)}")
                base_attr_str = "\n".join(base_attr_lines)

                role_data = {"属性列表": base_attr_str, "总属性": attr_data["基础总属性"]}
                role_msg = render_template(config["character"]["output_template"], role_data)
                role_msg += "\n\n✅ 角色创建成功！/st可新增/修改技能，/查询角色查看完整属性，。"

                await self.send_text(role_msg)
                return True, role_msg, True

            except Exception as e:
                error_msg = f"❌ 创建角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 7. 处理/查询角色指令 ==========
        elif cmd_prefix == "查询角色":
            if params:
                error_msg = "❌ /查询角色命令无需参数！"
                await self.send_text(error_msg)
                return False, error_msg, True

            if user_id not in USER_CHARACTER_DATA:
                error_msg = "❌ 你还未创建角色！可发送/创建角色或/st指令自动创建。"
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                char_data = USER_CHARACTER_DATA[user_id]
                base_attr_str, derived_attr_str, base_total, _ = format_character_attributes(char_data)

                query_data = {
                    "基础属性列表": base_attr_str,
                    "衍生属性列表": derived_attr_str,
                    "基础总属性": base_total
                }
                query_msg = render_template(config["character"]["query_template"], query_data)
                await self.send_text(query_msg)
                return True, query_msg, True

            except Exception as e:
                error_msg = f"❌ 查询角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 8. 处理/查询技能指令 ==========
        elif cmd_prefix == "查询技能":
            skill_name = params.strip()
            
            # 检查是否创建角色
            if user_id not in USER_CHARACTER_DATA:
                error_msg = "❌ 你还未创建角色！可发送/创建角色或/st指令自动创建。"
                await self.send_text(error_msg)
                return False, error_msg, True

            try:
                char_data = USER_CHARACTER_DATA[user_id]
                
                # 有参数：查询单个技能/属性
                if skill_name:
                    exists, show_name, value = get_single_skill_value(skill_name, char_data)
                    if exists:
                        single_skill_data = {
                            "skill_name": show_name,
                            "skill_value": value
                        }
                        single_msg = render_template(config["character"]["single_skill_template"], single_skill_data)
                        await self.send_text(single_msg)
                        return True, single_msg, True
                    else:
                        error_msg = f"❌ 未找到技能/属性「{skill_name}」！\n💡 发送「/查询技能」查看所有技能，/查询角色查看所有属性。\n"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                # 无参数：查询所有技能
                else:
                    skill_lines, skill_count = get_character_skills(char_data)
                    
                    if not skill_lines:
                        skill_list = "暂无自定义技能（可通过/st指令添加，如/st 力量80 伤害加值1d4）\n"
                    else:
                        skill_list = "\n".join(skill_lines)

                    skill_data = {
                        "技能列表": skill_list,
                        "skill_count": skill_count
                    }
                    skill_msg = render_template(config["character"]["skill_query_template"], skill_data)
                    await self.send_text(skill_msg)
                    return True, skill_msg, True

            except Exception as e:
                error_msg = f"❌ 查询技能出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 9. 处理/掷骰指令 ==========
        elif cmd_prefix == "掷骰":
            dice_expr, reason = split_check_params(params)
            if not dice_expr:
                error_msg = "❌ 缺少骰子表达式！示例：/r d100 探索密室。"
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
                    "表达式": dice_expr,
                    "原因说明": f"因为{reason}所以进行" if reason else "进行",
                    "单次结果": roll_detail,
                    "修正值": modifier_str,
                    "总计": total,
                    "判定结果": judge_result.strip()
                }

                msg = render_template(config["dice"]["roll_template"], roll_data)
                await self.send_text(msg)
                return True, msg, True

            except ValueError as e:
                error_msg = f"❌ {str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
            except Exception as e:
                error_msg = f"❌ 掷骰出错：{str(e)}"
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
        "delete_attr": "属性删除配置"
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
