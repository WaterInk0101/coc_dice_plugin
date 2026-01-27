import random
import re
import os
import json
import tomllib  # Python 3.11+ 内置，若版本低可替换为 toml 库
from typing import List, Tuple, Type, Any, Optional, Dict
from src.plugin_system import (
    BasePlugin,
    register_plugin,
    BaseCommand,
    BaseTool,
    ComponentInfo,
    ConfigField,
    BaseEventHandler,
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

# ===================== 预设属性映射（兼容原有功能） =====================
PRESET_ATTR_MAP = {
    "力量": ("STR", "力量(STR)"),
    "体质": ("CON", "体质(CON)"),
    "体型": ("SIZ", "体型(SIZ)"),
    "敏捷": ("DEX", "敏捷(DEX)"),
    "外貌": ("APP", "外貌(APP)"),
    "智力": ("INT", "智力(INT)"),
    "意志": ("POW", "意志(POW)"),
    "教育": ("EDU", "教育(EDU)"),
    "幸运": ("LUCK", "幸运(LUCK)")
}
PRESET_ATTR_NAMES = set(PRESET_ATTR_MAP.keys())
PRESET_ATTR_TO_SHORT = {name: short for name, (short, full) in PRESET_ATTR_MAP.items()}
SHORT_TO_PRESET_ATTR = {short: name for name, (short, full) in PRESET_ATTR_MAP.items()}

# ===================== 快捷指令映射 =====================
SHORT_CMD_MAP = {
    "r": "掷骰",
    "rd": "检定",
    "st": "导入",
    "del": "删除",       
    "del_all": "删除角色"
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
            "default_message": "🎲 克苏鲁骰子投掷完成！",
            "roll_template": """🎲 投掷「{表达式}」结果：
{原因说明}
单次结果：{单次结果}
修正值：{修正值}
总计：{总计}
{判定结果}""",
            "check_template": """🎲 克苏鲁检定（阈值：{阈值}）
{原因说明}
投掷结果：{投掷结果}
{判定结果}"""
        },
        "character": {
            "output_template": """🎭 随机生成跑团基础属性：
{属性列表}
📊 预设属性总值：{总属性}
💡 支持导入自定义属性（如/导入 感知80 魅力75）""",
            "query_template": """🎭 你的绑定角色属性：
{预设属性列表}
{自定义属性列表}
📊 预设属性总值：{预设总属性}
📊 所有属性总数：{属性总数}
💡 提示：/rd [属性名] 可检定任意属性（如/rd 力量、/rd 感知）"""
        },
        "import_attr": {
            "success_template": """✅ 角色属性修改/新增成功！
{自动创建提示}
修改/新增的属性：
{修改列表}
📊 当前预设属性总值：{预设总属性}
📊 所有属性总数：{属性总数}
💡 发送「/查询角色」查看完整属性，/rd [属性名] 检定属性""",
            "auto_create_tip": "🔔 检测到你未创建角色，已自动生成预设属性并新增/覆盖指定值！",
            "update_tip": "🔔 已新增/覆盖你指定的属性值！",
            "error_template": """❌ 属性修改失败：
{错误原因}
💡 正确格式：/st 力量80 感知75（属性值范围1-100，支持自定义属性）
💡 预设属性：{预设属性列表}"""
        },
        "delete_attr": {
            "success_template": """✅ 属性操作成功！
{操作描述}
📊 当前预设属性总值：{预设总属性}
📊 所有属性总数：{属性总数}
💡 发送「/查询角色」查看最新属性""",
            "delete_role_template": """✅ 角色删除成功！
你的所有角色数据（预设属性+自定义属性）已清空，可发送「/创建角色」重新生成。""",
            "error_template": """❌ 属性操作失败：
{错误原因}
💡 支持的操作：
1. /删除 [属性名] → 删除/重置属性（如/删除 感知、/删除 力量）
2. /删除角色 → 删除整个角色数据"""
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
    """解析导入属性参数（无=格式，支持自定义属性）"""
    if not params.strip():
        raise ValueError("未输入任何属性参数")
    
    attr_dict = {}
    attr_pairs = params.strip().split()
    attr_pattern = re.compile(r"([^0-9]+)(\d+)")
    
    for pair in attr_pairs:
        match = attr_pattern.match(pair)
        if not match:
            raise ValueError(f"属性格式错误：{pair}（正确示例：力量80、感知75）")
        
        attr_name = match.group(1).strip()
        value_str = match.group(2).strip()
        
        if not value_str.isdigit():
            raise ValueError(f"属性值非法：{attr_name}{value_str}（必须是1-100的整数）")
        
        attr_value = int(value_str)
        if attr_value < 1 or attr_value > 100:
            raise ValueError(f"属性值超出范围：{attr_name}{attr_value}（1-100）")
        
        attr_dict[attr_name] = attr_value
    return attr_dict

def generate_character_attributes() -> Dict[str, int]:
    """生成预设基础属性（3d6*5）"""
    attr_results = {}
    for _, (short_name, _) in PRESET_ATTR_MAP.items():
        rolls, sum_3d6 = roll_dice(3, 6)
        attr_results[short_name] = sum_3d6 * 5
    attr_results["总属性"] = sum([attr_results[short] for short in PRESET_ATTR_TO_SHORT.values()])
    return attr_results

def generate_single_preset_attr(attr_name: str) -> int:
    """生成单个预设属性的默认值（3d6*5）"""
    if attr_name not in PRESET_ATTR_TO_SHORT:
        raise ValueError(f"{attr_name}不是预设属性，无法生成默认值")
    short_name = PRESET_ATTR_TO_SHORT[attr_name]
    rolls, sum_3d6 = roll_dice(3, 6)
    return sum_3d6 * 5

def format_character_attributes(char_data: Dict[str, int]) -> Tuple[str, str, int, int]:
    """格式化角色属性（区分预设/自定义）- 修改点1：移除自定义属性前缀"""
    # 处理预设属性
    preset_attr_lines = []
    preset_total = 0
    for attr_name, (short_name, full_name) in PRESET_ATTR_MAP.items():
        value = char_data.get(short_name, 0)
        preset_attr_lines.append(f"🔹 {full_name}：{value}")
        preset_total += value
    
    # 处理自定义属性 - 移除「自定义属性-」前缀
    custom_attr_lines = []
    custom_count = 0
    for key, value in char_data.items():
        if key not in SHORT_TO_PRESET_ATTR and key != "总属性":
            custom_attr_lines.append(f"🔹 {key}：{value}")  # 修改：直接显示属性名
            custom_count += 1
    
    preset_attr_str = "\n".join(preset_attr_lines) if preset_attr_lines else "暂无预设属性"
    custom_attr_str = "\n".join(custom_attr_lines) if custom_attr_lines else "暂无自定义属性"
    total_attr_count = 9 + custom_count
    
    return preset_attr_str, custom_attr_str, preset_total, total_attr_count

# ===================== 删除属性/角色核心函数 =====================
def delete_character_attribute(user_id: str, attr_name: str) -> Tuple[bool, str, Dict[str, int]]:
    """
    删除/重置角色属性 - 修改点2：移除自定义属性前缀
    Args:
        user_id: 用户ID
        attr_name: 要删除的属性名
    
    Returns:
        (操作是否成功, 操作描述, 更新后的角色数据)
    """
    if user_id not in USER_CHARACTER_DATA:
        return False, "你还未创建角色，无属性可删除！", {}
    
    user_char = USER_CHARACTER_DATA[user_id].copy()
    
    # 1. 处理预设属性（重置为3d6*5）
    if attr_name in PRESET_ATTR_NAMES:
        short_name = PRESET_ATTR_TO_SHORT[attr_name]
        old_value = user_char.get(short_name, 0)
        new_value = generate_single_preset_attr(attr_name)
        user_char[short_name] = new_value
        
        # 重新计算预设总值
        preset_total = sum([user_char.get(short, 0) for short in PRESET_ATTR_TO_SHORT.values()])
        user_char["总属性"] = preset_total
        
        return True, f"预设属性-{attr_name}已重置为默认值（3d6×5）：{old_value} → {new_value}", user_char
    
    # 2. 处理自定义属性（直接删除）- 移除「自定义属性-」前缀
    elif attr_name in user_char:
        old_value = user_char[attr_name]
        del user_char[attr_name]
        
        # 重新计算预设总值（自定义属性不影响）
        preset_total = sum([user_char.get(short, 0) for short in PRESET_ATTR_TO_SHORT.values()])
        user_char["总属性"] = preset_total
        
        return True, f"{attr_name}已删除（原值：{old_value}）", user_char  # 修改：直接显示属性名
    
    # 3. 属性不存在
    else:
        return False, f"未找到属性「{attr_name}」，无法删除！", user_char

def delete_character(user_id: str) -> bool:
    """
    删除整个角色数据
    Args:
        user_id: 用户ID
    
    Returns:
        是否删除成功
    """
    if user_id in USER_CHARACTER_DATA:
        del USER_CHARACTER_DATA[user_id]
        save_character_data(USER_CHARACTER_DATA)
        return True
    return False

# ===================== LLM调用工具 =====================
class CoCDiceTool(BaseTool):
    """CoC骰子工具（LLM调用）"""
    name = "coc_dice_tool"
    description = "克苏鲁跑团骰子投掷工具，支持D100/2d6等格式，返回投掷结果"
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
    command_description = f"""克苏鲁骰子/角色管理插件（支持自定义属性+删除操作）
用法：
1. /r [表达式] [原因] → 投掷骰子（如/r d100 探索密室）
2. /rd [参数] [原因] → 检定（支持两种模式）
   - 模式1：/rd [阈值] [原因]（如/rd 70 躲避陷阱）
   - 模式2：/rd [属性名] [原因]（如/rd 力量、/rd 感知）
3. /创建角色 → 生成预设基础属性（3d6*5）
4. /查询角色 → 查看所有属性（预设+自定义）
5. /st/导入 [属性数值] → 新增/修改属性（无=格式，如/st 力量80 感知75）
6. /删除/ del [属性名] → 删除/重置属性
   - 预设属性：重置为3d6*5（如/删除 力量）
   - 自定义属性：直接删除（如/删除 感知）
7. /删除角色/ del_all → 删除整个角色数据（所有属性清空）
支持的预设属性：{', '.join(PRESET_ATTR_NAMES)}
自定义属性：任意名称（如感知、魅力、幸运值）"""
    
    command_pattern = r"^/(r|rd|st|导入|del|删除|del_all|删除角色|掷骰|检定|创建角色|查询角色|\w+)(\s+.*)?$"

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
                
                # 自动创建角色（无角色时）
                is_auto_create = False
                if user_id not in USER_CHARACTER_DATA:
                    USER_CHARACTER_DATA[user_id] = generate_character_attributes()
                    is_auto_create = True
                
                # 新增/覆盖属性 - 修改点3：移除自定义属性前缀
                user_char = USER_CHARACTER_DATA[user_id].copy()
                modified_attrs = []
                for attr_name, attr_value in import_attr_dict.items():
                    if attr_name in PRESET_ATTR_TO_SHORT:
                        # 预设属性（用缩写存储）
                        attr_short = PRESET_ATTR_TO_SHORT[attr_name]
                        old_value = user_char.get(attr_short, 0)
                        user_char[attr_short] = attr_value
                        modified_attrs.append(f"🔹 预设属性-{attr_name}({attr_short})：{old_value} → {attr_value}")
                    else:
                        # 自定义属性（直接存储）- 移除「自定义属性-」前缀
                        old_value = user_char.get(attr_name, "无")
                        user_char[attr_name] = attr_value
                        modified_attrs.append(f"🔹 {attr_name}：{old_value} → {attr_value}")  # 修改：直接显示属性名
                
                # 重新计算预设总值
                preset_total = sum([user_char.get(short, 0) for short in PRESET_ATTR_TO_SHORT.values()])
                user_char["总属性"] = preset_total
                custom_count = len([k for k in user_char.keys() if k not in SHORT_TO_PRESET_ATTR and k != "总属性"])
                total_attr_count = 9 + custom_count
                
                # 保存并返回结果
                USER_CHARACTER_DATA[user_id] = user_char
                save_character_data(USER_CHARACTER_DATA)
                
                auto_create_tip = config["import_attr"]["auto_create_tip"] if is_auto_create else config["import_attr"]["update_tip"]
                import_data = {
                    "自动创建提示": auto_create_tip,
                    "修改列表": "\n".join(modified_attrs),
                    "预设总属性": preset_total,
                    "属性总数": total_attr_count
                }
                success_msg = render_template(config["import_attr"]["success_template"], import_data)
                await self.send_text(success_msg)
                return True, success_msg, True
            
            except ValueError as e:
                error_data = {"错误原因": str(e), "预设属性列表": ", ".join(PRESET_ATTR_NAMES)}
                error_msg = render_template(config["import_attr"]["error_template"], error_data)
                await self.send_text(error_msg)
                return False, error_msg, True
            except Exception as e:
                error_msg = f"❌ 属性导入出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 2. 处理/检定指令 - 修改点4：移除自定义属性前缀 ==========
        elif cmd_prefix == "检定":
            first_param, reason = split_check_params(params)
            if not first_param:
                error_msg = """❌ 缺少检定参数！支持两种用法：
1. /rd [阈值] [原因]（如/rd 70 躲避陷阱）
2. /rd [属性名] [原因]（如/rd 力量、/rd 感知）"""
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                check_threshold = None
                attr_name = None
                is_custom_attr = False
                
                # 判断参数类型：数字阈值 / 属性名
                if first_param.isdigit():
                    # 模式1：直接阈值检定
                    check_threshold = int(first_param)
                    if check_threshold < 1 or check_threshold > 99:
                        error_msg = "❌ 检定阈值范围必须是1-99！"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                else:
                    # 模式2：属性名检定（预设/自定义）
                    attr_name = first_param
                    if user_id not in USER_CHARACTER_DATA:
                        error_msg = f"❌ 你还未创建角色！无法获取「{attr_name}」属性值。"
                        await self.send_text(error_msg)
                        return False, error_msg, True
                    
                    user_char = USER_CHARACTER_DATA[user_id]
                    # 优先查预设属性
                    if attr_name in PRESET_ATTR_TO_SHORT:
                        attr_short = PRESET_ATTR_TO_SHORT[attr_name]
                        check_threshold = user_char.get(attr_short, 0)
                    else:
                        # 查自定义属性
                        check_threshold = user_char.get(attr_name, 0)
                        is_custom_attr = True
                    
                    # 验证属性值有效性
                    if not isinstance(check_threshold, int) or check_threshold < 1 or check_threshold > 100:
                        error_msg = f"❌ 「{attr_name}」属性值异常（{check_threshold}），无法检定！"
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
                
                # 构建提示信息 - 移除自定义属性前缀
                reason_desc = f"因为{reason}所以进行" if reason else "进行"
                if attr_name:
                    # 属性检定提示 - 简化属性类型描述
                    attr_type = "" if is_custom_attr else "预设属性-"  # 修改：自定义属性不显示前缀
                    check_template = f"""🎲 {attr_type}{attr_name}检定（阈值：{{阈值}}）
{reason_desc}「{attr_name}」属性检定
你的{attr_name}属性值：{{阈值}}
投掷结果：{{投掷结果}}
{{判定结果}}"""
                    check_data = {
                        "阈值": check_threshold,
                        "原因说明": reason_desc,
                        "投掷结果": total,
                        "判定结果": judge_result
                    }
                    msg = render_template(check_template, check_data)
                else:
                    # 阈值检定提示（原有逻辑）
                    check_data = {
                        "阈值": check_threshold,
                        "原因说明": f"{reason_desc}D100检定",
                        "投掷结果": total,
                        "判定结果": judge_result
                    }
                    msg = render_template(config["dice"]["check_template"], check_data)
                
                await self.send_text(msg)
                return True, msg, True
            
            except Exception as e:
                error_msg = f"❌ 检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 3. 处理/删除指令 ==========
        elif cmd_prefix == "删除":
            attr_name = params.strip()
            if not attr_name:
                error_msg = """❌ 缺少属性名参数！
用法：/删除 [属性名]（如/删除 力量、/删除 感知）
- 预设属性：重置为3d6×5
- 自定义属性：直接删除"""
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                # 执行删除/重置操作
                success, op_desc, user_char = delete_character_attribute(user_id, attr_name)
                
                if success:
                    # 计算最新属性统计
                    _, _, preset_total, total_count = format_character_attributes(user_char)
                    # 更新全局数据并保存
                    USER_CHARACTER_DATA[user_id] = user_char
                    save_character_data(USER_CHARACTER_DATA)
                    # 渲染成功提示
                    delete_data = {
                        "操作描述": op_desc,
                        "预设总属性": preset_total,
                        "属性总数": total_count
                    }
                    success_msg = render_template(config["delete_attr"]["success_template"], delete_data)
                    await self.send_text(success_msg)
                    return True, success_msg, True
                else:
                    # 渲染错误提示
                    error_data = {"错误原因": op_desc}
                    error_msg = render_template(config["delete_attr"]["error_template"], error_data)
                    await self.send_text(error_msg)
                    return False, error_msg, True
            
            except Exception as e:
                error_msg = f"❌ 删除属性出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 4. 处理/删除角色指令 ==========
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

        # ========== 5. 处理/创建角色指令 ==========
        elif cmd_prefix == "创建角色":
            if params:
                error_msg = "❌ /创建角色命令无需参数！"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                attr_data = generate_character_attributes()
                USER_CHARACTER_DATA[user_id] = attr_data
                save_character_data(USER_CHARACTER_DATA)
                
                preset_attr_lines = []
                for attr_name, (short_name, full_name) in PRESET_ATTR_MAP.items():
                    preset_attr_lines.append(f"🔹 {full_name}：{attr_data[short_name]}")
                preset_attr_str = "\n".join(preset_attr_lines)
                
                role_data = {"属性列表": preset_attr_str, "总属性": attr_data["总属性"]}
                role_msg = render_template(config["character"]["output_template"], role_data)
                role_msg += "\n\n✅ 角色创建成功！/st可新增自定义属性，/rd [属性名] 可检定属性，/删除 [属性名] 可重置/删除属性。"
                
                await self.send_text(role_msg)
                return True, role_msg, True
            
            except Exception as e:
                error_msg = f"❌ 创建角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 6. 处理/查询角色指令 ==========
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
                preset_attr_str, custom_attr_str, preset_total, total_count = format_character_attributes(char_data)
                
                query_data = {
                    "预设属性列表": preset_attr_str,
                    "自定义属性列表": custom_attr_str,
                    "预设总属性": preset_total,
                    "属性总数": total_count
                }
                query_msg = render_template(config["character"]["query_template"], query_data)
                await self.send_text(query_msg)
                return True, query_msg, True
            
            except Exception as e:
                error_msg = f"❌ 查询角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

        # ========== 7. 处理/掷骰指令 ==========
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

        # ========== 8. 未知指令 ==========
        else:
            error_msg = f"❌ 未知指令：/{cmd_prefix}！支持的指令：/r/rd/st/导入/del/删除/del_all/删除角色/掷骰/检定/创建角色/查询角色。"
            await self.send_text(error_msg)
            return False, error_msg, True

# ===================== 消息事件处理器 =====================
class CoCDiceEventHandler(BaseEventHandler):
    """监听「掷骰」关键词自动响应"""
    event_type = EventType.ON_MESSAGE
    handler_name = "coc_dice_handler"
    handler_description = "监听消息中的「掷骰」关键词，自动投掷骰子"

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, str | None, None, None]:
        if not message or not message.plain_text:
            return True, True, None, None, None
        
        msg_text = message.plain_text.strip()
        if "掷骰" in msg_text:
            match = re.search(r"掷骰\s+(\d*d\d+[+-]?\d*)", msg_text)
            if match:
                dice_expr = match.group(1)
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
                    
                    auto_msg = render_template(config["dice"]["roll_template"], roll_data)
                    await self.send_text(auto_msg)
                except ValueError as e:
                    error_msg = f"❌ 自动投掷失败：{str(e)}"
                    await self.send_text(error_msg)
        
        return True, True, None, None, None

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
            "check_template": ConfigField(type=str, default=get_plugin_config()["dice"]["check_template"], description="检定模板")
        },
        "character": {
            "output_template": ConfigField(type=str, default=get_plugin_config()["character"]["output_template"], description="创建角色模板"),
            "query_template": ConfigField(type=str, default=get_plugin_config()["character"]["query_template"], description="查询角色模板")
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
            (CoCDiceEventHandler.get_handler_info(), CoCDiceEventHandler),
        ]
    
    def on_plugin_stop(self):
        """插件停止时保存数据"""
        global USER_CHARACTER_DATA
        save_character_data(USER_CHARACTER_DATA)
        logger.info("插件停止，角色数据已保存")
