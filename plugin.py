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
# 角色数据存储文件路径（插件目录下的character_data.json）
CHAR_DATA_PATH = os.path.join(os.path.dirname(__file__), "character_data.json")

def load_character_data() -> Dict[str, Dict[str, int]]:
    """
    加载用户角色数据（持久化存储）
    Returns:
        {用户ID: {角色属性字典}}
    """
    try:
        if os.path.exists(CHAR_DATA_PATH):
            with open(CHAR_DATA_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}
    except Exception as e:
        logger.error(f"加载角色数据失败，使用空数据：{e}")
        return {}

def save_character_data(char_data: Dict[str, Dict[str, int]]) -> bool:
    """
    保存用户角色数据到文件（持久化）
    Args:
        char_data: 用户角色数据字典
    Returns:
        是否保存成功
    """
    try:
        # 确保目录存在
        os.makedirs(os.path.dirname(__file__), exist_ok=True)
        with open(CHAR_DATA_PATH, "w", encoding="utf-8") as f:
            json.dump(char_data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        logger.error(f"保存角色数据失败：{e}")
        return False

# 全局角色数据（运行时缓存，启动时加载，修改时保存）
USER_CHARACTER_DATA = load_character_data()

# ===================== 属性指令映射字典 =====================
# 指令名 -> (属性缩写, 属性全称)
ATTR_COMMAND_MAP = {
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
# 生成属性指令列表（用于匹配和提示）
VALID_ATTR_COMMANDS = list(ATTR_COMMAND_MAP.keys())
# 属性名称反向映射（用于解析/st指令）：属性名 -> 缩写
ATTR_NAME_TO_SHORT = {name: short for name, (short, full) in ATTR_COMMAND_MAP.items()}
# 合法属性名称集合
VALID_ATTR_NAMES = set(ATTR_NAME_TO_SHORT.keys())

# ===================== 快捷指令映射 =====================
SHORT_CMD_MAP = {
    "r": "掷骰",
    "rd": "检定",
    "st": "导入"  # /st 等同于 /导入
}

# ===================== 配置文件相关（热重载） =====================
def get_plugin_config() -> Dict[str, Any]:
    """
    读取配置文件（每次调用都重新读取，实现热重载）
    Returns:
        配置字典，包含所有模板配置项
    """
    # 配置文件路径（与插件同目录的config.toml）
    config_path = os.path.join(os.path.dirname(__file__), "config.toml")
    # 完整默认配置（包含角色、掷骰、检定模板）
    default_config = {
        "plugin": {
            "config_version": "1.0.0",
            "enabled": True
        },
        "dice": {
            "show_detail": True,
            "success_threshold": 5,
            "fail_threshold": 96,
            "default_message": "🎲 克苏鲁骰子投掷完成！",
            # 掷骰命令默认模板（新增原因字段）
            "roll_template": """🎲 投掷「{表达式}」结果：
{原因说明}
单次结果：{单次结果}
修正值：{修正值}
总计：{总计}
{判定结果}""",
            # 检定命令默认模板（新增原因字段）
            "check_template": """🎲 克苏鲁检定（阈值：{阈值}）
{原因说明}
投掷结果：{投掷结果}
{判定结果}""",
            # 属性检定专用模板
            "attr_check_template": """🎲 {属性全称}检定（阈值：{阈值}）
你的{属性全称}属性值：{阈值}
投掷结果：{投掷结果}
{判定结果}"""
        },
        "character": {
            # 角色创建默认模板
            "output_template": """🎭 随机生成跑团基础属性：

🔹 力量(STR)：{STR}
🔹 体质(CON)：{CON}
🔹 体型(SIZ)：{SIZ}
🔹 敏捷(DEX)：{DEX}
🔹 外貌(APP)：{APP}
🔹 智力(INT)：{INT}
🔹 意志(POW)：{POW}
🔹 教育(EDU)：{EDU}
🔹 幸运(LUCK)：{LUCK}

📊 属性总值：{总属性}""",
            # 角色查询默认模板
            "query_template": """🎭 你的绑定角色属性：

🔹 力量(STR)：{STR}
🔹 体质(CON)：{CON}
🔹 体型(SIZ)：{SIZ}
🔹 敏捷(DEX)：{DEX}
🔹 外貌(APP)：{APP}
🔹 智力(INT)：{INT}
🔹 意志(POW)：{POW}
🔹 教育(EDU)：{EDU}
🔹 幸运(LUCK)：{LUCK}

📊 属性总值：{总属性}
💡 提示：发送「/创建角色」可重新生成并覆盖当前角色
💡 支持指令：/{力量}/{体质}/{体型}/{敏捷}/{外貌}/{智力}/{意志}/{教育}/{幸运}（自动检定对应属性）
💡 快捷指令：/r [表达式] [原因] = /掷骰、/rd [阈值] [原因] = /检定
💡 属性修改：/st [属性值] 或 /导入 [属性值]（支持多属性，如：/st 力量80 体质75）"""
        },
        # 新增：属性导入模板
        "import_attr": {
            "success_template": """✅ 角色属性修改成功！
{自动创建提示}
修改的属性：
{修改列表}
当前角色属性总值：{总属性}
💡 发送「/查询角色」查看完整属性""",
            "auto_create_tip": "🔔 检测到你未创建角色，已自动生成基础属性并覆盖指定值！",
            "update_tip": "🔔 已覆盖你指定的属性值，未指定属性保留原有值！",
            "error_template": """❌ 属性修改失败：
{错误原因}
💡 正确格式：/st 力量80 体质75（属性值范围1-100）
💡 支持属性：{支持属性}"""
        }
    }

    # 读取配置文件，不存在则返回默认配置
    try:
        if os.path.exists(config_path):
            with open(config_path, "rb") as f:
                user_config = tomllib.load(f)
                # 深度合并用户配置和默认配置（用户配置覆盖默认）
                for section in default_config.keys():
                    if section in user_config:
                        default_config[section].update(user_config[section])
        return default_config
    except Exception as e:
        logger.error(f"读取配置文件失败：{e}")
        return default_config

# ===================== 模板渲染工具函数 =====================
def render_template(template: str, data: Dict[str, Any]) -> str:
    """
    通用模板渲染函数（安全替换，兼容未定义变量）
    Args:
        template: 模板字符串
        data: 渲染数据字典
    Returns:
        渲染后的字符串
    """
    try:
        return template.format(** data)
    except KeyError as e:
        logger.warning(f"模板变量缺失：{e}")
        # 降级替换：只替换存在的变量
        rendered = template
        for key, value in data.items():
            rendered = rendered.replace(f"{{{key}}}", str(value))
        return rendered

# ===================== 核心骰子逻辑（优化：支持默认1个骰子） =====================
def parse_dice_expression(expr: str) -> Tuple[int, int, int]:
    """
    解析骰子表达式，支持格式：
    - 完整格式：数量d面数[±修正值]（如1d100、2d6+3）
    - 简化格式：d面数[±修正值]（如d100 → 自动补全1d100）
    
    Args:
        expr: 骰子表达式字符串
        
    Returns:
        (数量, 面数, 修正值)
        
    Raises:
        ValueError: 无效表达式
    """
    # 优化正则：数量部分可选（\d*），匹配d开头的简化格式
    pattern = r"^(\d*)d(\d+)([+-]\d+)?$"
    match = re.match(pattern, expr.strip(), re.IGNORECASE)
    
    if not match:
        raise ValueError(f"无效的骰子表达式：{expr}，请使用「[数量]d面数[±修正值]」格式（如d100、2d6+3）")
    
    # 处理数量：为空则默认1
    count_str = match.group(1)
    count = int(count_str) if count_str else 1
    face = int(match.group(2))
    modifier_str = match.group(3)
    modifier = int(modifier_str) if modifier_str else 0
    
    # 合法性校验
    if count <= 0 or count > 100:
        raise ValueError(f"骰子数量{count}超出范围（仅支持1-100个骰子）")
    if face <= 0 or face > 1000:
        raise ValueError(f"骰子面数{face}超出范围（仅支持1-1000面骰子）")
    
    return count, face, modifier

def roll_dice(count: int, face: int, modifier: int = 0) -> Tuple[List[int], int]:
    """执行骰子投掷，返回单次结果列表和总计"""
    rolls = [random.randint(1, face) for _ in range(count)]
    total = sum(rolls) + modifier
    return rolls, total

# ===================== 辅助函数：拆分检定参数（表达式+原因） =====================
def split_check_params(params: str) -> Tuple[str, str]:
    """
    拆分检定参数为「阈值/表达式」和「原因」
    规则：第一个空格前的部分为表达式，剩余部分为原因
    
    Args:
        params: 完整参数字符串（如"70 探索密室"）
        
    Returns:
        (表达式, 原因)
    """
    if not params.strip():
        return "", ""
    
    parts = params.strip().split(" ", 1)
    expr = parts[0]
    reason = parts[1] if len(parts) > 1 else ""
    return expr, reason

# ===================== 新增：属性导入解析函数（优化：去除=，支持属性名+数值） =====================
def parse_import_attr_params(params: str) -> Dict[str, int]:
    """
    解析/st/导入指令的属性参数，格式：属性名数值 多个属性用空格分隔
    示例："力量80 体质75" → {"力量":80, "体质":75}
    
    Args:
        params: 属性参数字符串
        
    Returns:
        解析后的属性字典 {属性名: 属性值}
        
    Raises:
        ValueError: 格式错误/值非法/属性名不存在
    """
    if not params.strip():
        raise ValueError("未输入任何属性参数")
    
    attr_dict = {}
    # 按空格拆分多个属性
    attr_pairs = params.strip().split()
    
    # 匹配属性名+数值的正则（属性名：非数字，数值：数字）
    attr_pattern = re.compile(r"([^0-9]+)(\d+)")
    
    for pair in attr_pairs:
        match = attr_pattern.match(pair)
        if not match:
            raise ValueError(f"属性格式错误：{pair}（正确格式：属性名数值，如力量80）")
        
        attr_name = match.group(1).strip()
        value_str = match.group(2).strip()
        
        # 验证属性名是否合法
        if attr_name not in VALID_ATTR_NAMES:
            raise ValueError(f"无效属性名：{attr_name}（支持属性：{', '.join(VALID_ATTR_NAMES)}）")
        
        # 验证属性值是否为数字
        if not value_str.isdigit():
            raise ValueError(f"属性值非法：{attr_name}{value_str}（必须是1-100的整数）")
        
        attr_value = int(value_str)
        # 验证属性值范围
        if attr_value < 1 or attr_value > 100:
            raise ValueError(f"属性值超出范围：{attr_name}{attr_value}（必须是1-100的整数）")
        
        attr_dict[attr_name] = attr_value
    
    return attr_dict

# ===================== 角色属性生成逻辑 =====================
def generate_character_attributes() -> Dict[str, int]:
    """
    生成跑团基础属性，公式：3D6×5
    Returns:
        字典格式：{属性缩写: 最终属性值}
    """
    attr_mapping = {
        "力量(STR)": "STR",
        "体质(CON)": "CON",
        "体型(SIZ)": "SIZ",
        "敏捷(DEX)": "DEX",
        "外貌(APP)": "APP",
        "智力(INT)": "INT",
        "意志(POW)": "POW",
        "教育(EDU)": "EDU",
        "幸运(LUCK)": "LUCK"
    }
    attr_results = {}
    
    for full_name, short_name in attr_mapping.items():
        rolls, sum_3d6 = roll_dice(3, 6)
        attr_results[short_name] = sum_3d6 * 5
    
    attr_results["总属性"] = sum(attr_results.values())
    return attr_results

# ===================== LLM调用工具 =====================
class CoCDiceTool(BaseTool):
    """CoC骰子工具 - 投掷克苏鲁跑团常用骰子"""
    name = "coc_dice_tool"
    description = "克苏鲁跑团骰子投掷工具，支持D100百分骰、D4/D6/D8/D10/D12/D20等多面骰，表达式格式为「[数量]d面数[±修正值]」（如d100、2d6+3）"
    parameters = [
        ("dice_expr", ToolParamType.STRING, "骰子表达式（格式：[数量]d面数[±修正值]，如d100、2d6+3）", True, None),
    ]
    available_for_llm = True

    async def execute(self, function_args: dict[str, Any]) -> dict[str, Any]:
        """执行骰子投掷（LLM调用入口）"""
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
                "原因说明": "",  # LLM调用暂不支持原因
                "单次结果": roll_detail,
                "修正值": modifier_str,
                "总计": total,
                "判定结果": judge_result.strip()
            }
            
            roll_template = config["dice"]["roll_template"]
            result_msg = render_template(roll_template, roll_data)
            
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
    """CoC骰子命令 - 支持/r/rd快捷指令、检定原因、默认1个骰子、属性导入（自动创建角色+无=格式）"""
    command_name = "coc_dice_command"
    command_description = f"""克苏鲁骰子投掷/检定/角色创建/角色查询/属性导入（支持角色绑定+持久化）
用法：
1. /r [表达式] [原因] 或 /掷骰 [表达式] [原因]（投掷骰子，表达式支持d100/2d6+3等，原因可选）
   示例：/r d100 探索密室 → 投掷1d100，原因：探索密室
2. /rd [阈值] [原因] 或 /检定 [阈值] [原因]（D100检定，阈值/原因可选）
   示例：/rd 70 躲避陷阱 → 阈值70的检定，原因：躲避陷阱
3. /创建角色（随机生成跑团基础属性并绑定到当前账号）
4. /查询角色（查看已绑定的角色属性）
5. /属性名（自动用绑定角色的对应属性检定，支持：{', '.join(VALID_ATTR_COMMANDS)}）
   示例：/力量 → 用你的力量属性值做D100检定
6. /st [属性数值] 或 /导入 [属性数值]（修改/创建角色属性，支持多属性，无需要=）
   示例：/st 力量80 体质75 → 把力量改为80，体质改为75（未创建角色则自动生成）
   支持属性：{', '.join(VALID_ATTR_NAMES)}（值范围1-100）"""
    
    # 扩展命令匹配规则：支持/st/导入/属性指令
    command_pattern = rf"^/(r|rd|st|导入|掷骰|检定|创建角色|查询角色|{'|'.join(VALID_ATTR_COMMANDS)})(\s+.*)?$"

    async def execute(self) -> Tuple[bool, str, bool]:
        """执行所有骰子/角色指令"""
        global USER_CHARACTER_DATA
        
        # ========== 提取用户ID ==========
        user_id = None
        try:
            if (hasattr(self.message, 'message_info') and 
                hasattr(self.message.message_info, 'user_info') and 
                hasattr(self.message.message_info.user_info, 'user_id')):
                user_id = str(self.message.message_info.user_info.user_id)
                logger.info(f"成功提取用户ID：{user_id}")
            else:
                logger.error("无法提取用户ID：属性层级缺失")
        except Exception as e:
            logger.error(f"提取用户ID失败：{e}")
        
        if not user_id:
            error_msg = "❌ 无法获取你的用户ID，无法执行指令！"
            await self.send_text(error_msg)
            return False, error_msg, True
        
        # ========== 解析指令（处理快捷指令） ==========
        raw_msg = self.message.raw_message.strip()
        # 提取指令前缀（如/r、/rd、/st、/导入、/力量）
        cmd_prefix = re.match(r"^/(\w+)", raw_msg).group(1) if re.match(r"^/(\w+)", raw_msg) else ""
        # 映射快捷指令
        if cmd_prefix in SHORT_CMD_MAP:
            original_cmd = SHORT_CMD_MAP[cmd_prefix]
            # 替换快捷指令为原指令（如/r d100 → /掷骰 d100，/st → /导入）
            raw_msg = raw_msg.replace(f"/{cmd_prefix}", f"/{original_cmd}", 1)
            cmd_prefix = original_cmd
        
        # 提取参数（指令后的所有内容）
        params = raw_msg[len(f"/{cmd_prefix}"):].strip()
        config = get_plugin_config()
        
        # ========== 新增：处理/导入指令（/st等效，优化：自动创建角色+无=格式） ==========
        if cmd_prefix == "导入":
            try:
                # 1. 解析属性参数
                import_attr_dict = parse_import_attr_params(params)
                
                # 2. 检查用户是否有角色，无则自动创建（3d6*5）
                is_auto_create = False
                if user_id not in USER_CHARACTER_DATA:
                    USER_CHARACTER_DATA[user_id] = generate_character_attributes()
                    is_auto_create = True
                    logger.info(f"用户{user_id}未创建角色，自动生成基础属性")
                
                # 3. 获取用户当前角色数据
                user_char = USER_CHARACTER_DATA[user_id].copy()
                # 4. 覆盖属性值（转换为缩写）
                modified_attrs = []
                for attr_name, attr_value in import_attr_dict.items():
                    attr_short = ATTR_NAME_TO_SHORT[attr_name]
                    old_value = user_char[attr_short]
                    user_char[attr_short] = attr_value
                    modified_attrs.append(f"🔹 {attr_name}({attr_short})：{old_value} → {attr_value}")
                
                # 5. 重新计算总属性
                total_attr = sum([user_char[short] for short in ATTR_NAME_TO_SHORT.values()])
                user_char["总属性"] = total_attr
                
                # 6. 更新全局数据并保存
                USER_CHARACTER_DATA[user_id] = user_char
                save_character_data(USER_CHARACTER_DATA)
                
                # 7. 构建自动创建提示
                auto_create_tip = config["import_attr"]["auto_create_tip"] if is_auto_create else config["import_attr"]["update_tip"]
                
                # 8. 渲染成功模板
                import_data = {
                    "自动创建提示": auto_create_tip,
                    "修改列表": "\n".join(modified_attrs),
                    "总属性": total_attr
                }
                success_template = config["import_attr"]["success_template"]
                success_msg = render_template(success_template, import_data)
                
                await self.send_text(success_msg)
                return True, success_msg, True
            
            except ValueError as e:
                # 渲染错误模板
                error_data = {
                    "错误原因": str(e),
                    "支持属性": ", ".join(VALID_ATTR_NAMES)
                }
                error_template = config["import_attr"]["error_template"]
                error_msg = render_template(error_template, error_data)
                await self.send_text(error_msg)
                return False, error_msg, True
            except Exception as e:
                logger.error(f"属性导入失败：{e}")
                error_msg = f"❌ 属性修改出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # ========== 处理属性检定指令（/力量、/体质等） ==========
        elif cmd_prefix in VALID_ATTR_COMMANDS:
            if params:
                error_msg = f"❌ /{cmd_prefix}命令无需参数！直接发送「/{cmd_prefix}」即可检定。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            if user_id not in USER_CHARACTER_DATA:
                error_msg = f"❌ 你还未绑定角色！发送「/创建角色」后再使用「/{cmd_prefix}」。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                attr_short, attr_full = ATTR_COMMAND_MAP[cmd_prefix]
                attr_value = USER_CHARACTER_DATA[user_id][attr_short]
                
                if not isinstance(attr_value, int) or attr_value < 1 or attr_value > 100:
                    error_msg = f"❌ 你的{attr_full}属性值异常（{attr_value}），无法检定！"
                    await self.send_text(error_msg)
                    return False, error_msg, True
                
                rolls, total = roll_dice(1, 100)
                success_thresh = config["dice"]["success_threshold"]
                fail_thresh = config["dice"]["fail_threshold"]
                
                if total <= success_thresh:
                    judge_result = "✨ 大成功！"
                elif total <= attr_value:
                    judge_result = "✅ 检定成功！"
                elif total >= fail_thresh:
                    judge_result = "💥 大失败！"
                else:
                    judge_result = "❌ 检定失败！"
                
                check_data = {
                    "属性全称": attr_full,
                    "阈值": attr_value,
                    "投掷结果": total,
                    "判定结果": judge_result.strip()
                }
                
                msg = render_template(config["dice"]["attr_check_template"], check_data)
                await self.send_text(msg)
                return True, msg, True
            
            except Exception as e:
                logger.error(f"{cmd_prefix}检定失败：{e}")
                error_msg = f"❌ {cmd_prefix}检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # ========== 处理/创建角色指令 ==========
        elif cmd_prefix == "创建角色":
            if params:
                error_msg = "❌ /创建角色命令无需参数！直接发送即可生成角色。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                attr_data = generate_character_attributes()
                USER_CHARACTER_DATA[user_id] = attr_data
                save_character_data(USER_CHARACTER_DATA)
                
                role_msg = render_template(config["character"]["output_template"], attr_data)
                role_msg += "\n\n✅ 角色已绑定！支持/{力量}/{体质}等指令自动检定，/r /掷骰、/rd /检定、/st /导入 修改属性 。"
                
                await self.send_text(role_msg)
                return True, role_msg, True
            
            except Exception as e:
                logger.error(f"创建角色失败：{e}")
                error_msg = f"❌ 创建角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # ========== 处理/查询角色指令 ==========
        elif cmd_prefix == "查询角色":
            if params:
                error_msg = "❌ /查询角色命令无需参数！直接发送即可查看。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            if user_id not in USER_CHARACTER_DATA:
                error_msg = "❌ 你还未绑定角色！发送「/创建角色」生成角色，或直接用/st指令自动创建。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                attr_data = USER_CHARACTER_DATA[user_id]
                query_msg = render_template(config["character"]["query_template"], attr_data)
                await self.send_text(query_msg)
                return True, query_msg, True
            
            except Exception as e:
                logger.error(f"查询角色失败：{e}")
                error_msg = f"❌ 查询角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # ========== 处理/检定指令（新增原因解析） ==========
        elif cmd_prefix == "检定":
            # 拆分阈值和原因
            threshold_str, reason = split_check_params(params)
            if not threshold_str:
                error_msg = "❌ 缺少检定阈值！用法：/检定 70 [原因] 或 /rd 70 [原因]。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            if not threshold_str.isdigit():
                error_msg = "❌ 检定阈值必须是数字！示例：/检定 70 躲避陷阱。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                check_threshold = int(threshold_str)
                if check_threshold < 1 or check_threshold > 99:
                    error_msg = "❌ 检定阈值范围必须是1-99！"
                    await self.send_text(error_msg)
                    return False, error_msg, True
                
                # 执行检定
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
                
                # 构建原因说明
                reason_desc = f"因为{reason}所以进行D100检定" if reason else ""
                
                check_data = {
                    "阈值": check_threshold,
                    "原因说明": reason_desc,
                    "投掷结果": total,
                    "判定结果": judge_result.strip()
                }
                
                msg = render_template(config["dice"]["check_template"], check_data)
                await self.send_text(msg)
                return True, msg, True
            
            except Exception as e:
                logger.error(f"检定失败：{e}")
                error_msg = f"❌ 检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # ========== 处理/掷骰指令（支持默认1个骰子+原因） ==========
        elif cmd_prefix == "掷骰":
            # 拆分表达式和原因
            dice_expr, reason = split_check_params(params)
            if not dice_expr:
                error_msg = "❌ 缺少骰子表达式！用法：/掷骰 d100 [原因] 或 /r d100 [原因]。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                # 解析表达式（自动补全默认1个骰子）
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
                
                # 构建原因说明
                reason_desc = f"因为{reason}所以进行{dice_expr}投掷" if reason else ""
                
                roll_data = {
                    "表达式": dice_expr,
                    "原因说明": reason_desc,
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
                logger.error(f"掷骰失败：{e}")
                error_msg = f"❌ 掷骰出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # ========== 未知指令 ==========
        else:
            error_msg = f"❌ 未知指令：/{cmd_prefix}，支持的指令：/r/rd/st/导入/掷骰/检定/创建角色/查询角色/属性名。"
            await self.send_text(error_msg)
            return False, error_msg, True

# ===================== 消息事件处理器 =====================
class CoCDiceEventHandler(BaseEventHandler):
    """监听「掷骰」关键词自动响应"""
    event_type = EventType.ON_MESSAGE
    handler_name = "coc_dice_handler"
    handler_description = "监听消息中的「掷骰」关键词，自动响应骰子投掷"

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
    """CoC骰子插件 - 支持快捷指令/检定原因/默认1个骰子/属性导入（自动创建+无=格式）"""
    plugin_name: str = "coc_dice_plugin"
    enable_plugin: bool = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name: str = "config.toml"

    config_section_descriptions = {
        "plugin": "插件基础配置",
        "dice": "骰子/检定相关配置（含自定义模板）",
        "character": "角色创建/查询模板配置",
        "import_attr": "属性导入指令模板配置"
    }

    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(
                type=str, 
                default="1.0.0", 
                description="配置文件版本"
            ),
            "enabled": ConfigField(
                type=bool, 
                default=True, 
                description="是否启用插件"
            )
        },
        "dice": {
            "show_detail": ConfigField(
                type=bool, 
                default=True, 
                description="是否显示单次投掷详情"
            ),
            "success_threshold": ConfigField(
                type=int, 
                default=5, 
                description="D100大成功阈值（≤该值为大成功）"
            ),
            "fail_threshold": ConfigField(
                type=int, 
                default=96, 
                description="D100大失败阈值（≥该值为大失败）"
            ),
            "default_message": ConfigField(
                type=str, 
                default="🎲 克苏鲁骰子投掷完成！", 
                description="骰子投掷默认提示消息"
            ),
            "roll_template": ConfigField(
                type=str,
                default="""🎲 投掷「{表达式}」结果：
{原因说明}
单次结果：{单次结果}
修正值：{修正值}
总计：{总计}
{判定结果}""",
                description="掷骰命令输出模板，支持变量：{表达式}/{原因说明}/{单次结果}/{修正值}/{总计}/{判定结果}"
            ),
            "check_template": ConfigField(
                type=str,
                default="""🎲 克苏鲁检定（阈值：{阈值}）
{原因说明}
投掷结果：{投掷结果}
{判定结果}""",
                description="检定命令输出模板，支持变量：{阈值}/{原因说明}/{投掷结果}/{判定结果}"
            ),
            "attr_check_template": ConfigField(
                type=str,
                default="""🎲 {属性全称}检定（阈值：{阈值}）
你的{属性全称}属性值：{阈值}
投掷结果：{投掷结果}
{判定结果}""",
                description="属性检定专用模板，支持变量：{属性全称}/{阈值}/{投掷结果}/{判定结果}"
            )
        },
        "character": {
            "output_template": ConfigField(
                type=str,
                default="""🎭 随机生成跑团基础属性：

🔹 力量(STR)：{STR}
🔹 体质(CON)：{CON}
🔹 体型(SIZ)：{SIZ}
🔹 敏捷(DEX)：{DEX}
🔹 外貌(APP)：{APP}
🔹 智力(INT)：{INT}
🔹 意志(POW)：{POW}
🔹 教育(EDU)：{EDU}
🔹 幸运(LUCK)：{LUCK}

📊 属性总值：{总属性}""",
                description="角色创建输出模板，支持变量：{STR}/{CON}/{SIZ}/{DEX}/{APP}/{INT}/{POW}/{EDU}/{LUCK}/{总属性}"
            ),
            "query_template": ConfigField(
                type=str,
                default="""🎭 你的绑定角色属性：

🔹 力量(STR)：{STR}
🔹 体质(CON)：{CON}
🔹 体型(SIZ)：{SIZ}
🔹 敏捷(DEX)：{DEX}
🔹 外貌(APP)：{APP}
🔹 智力(INT)：{INT}
🔹 意志(POW)：{POW}
🔹 教育(EDU)：{EDU}
🔹 幸运(LUCK)：{LUCK}

📊 属性总值：{总属性}
💡 提示：发送「/创建角色」可重新生成并覆盖当前角色
💡 支持指令：/{力量}/{体质}/{体型}/{敏捷}/{外貌}/{智力}/{意志}/{教育}/{幸运}（自动检定对应属性）
💡 快捷指令：/r [表达式] [原因] = /掷骰、/rd [阈值] [原因] = /检定
💡 属性修改：/st [属性数值] 或 /导入 [属性数值]（支持多属性，如：/st 力量80 体质75）""",
                description="角色查询输出模板，支持变量：{STR}/{CON}/{SIZ}/{DEX}/{APP}/{INT}/{POW}/{EDU}/{LUCK}/{总属性}"
            )
        },
        # 新增：属性导入模板配置
        "import_attr": {
            "success_template": ConfigField(
                type=str,
                default="""✅ 角色属性修改成功！
{自动创建提示}
修改的属性：
{修改列表}
当前角色属性总值：{总属性}
💡 发送「/查询角色」查看完整属性""",
                description="属性导入成功提示模板，支持变量：{自动创建提示}/{修改列表}/{总属性}"
            ),
            "auto_create_tip": ConfigField(
                type=str,
                default="🔔 检测到你未创建角色，已自动生成基础属性并覆盖指定值！",
                description="自动创建角色时的提示语"
            ),
            "update_tip": ConfigField(
                type=str,
                default="🔔 已覆盖你指定的属性值，未指定属性保留原有值！",
                description="更新已有角色属性时的提示语"
            ),
            "error_template": ConfigField(
                type=str,
                default="""❌ 属性修改失败：
{错误原因}
💡 正确格式：/st 力量80 体质75（属性值范围1-100）
💡 支持属性：{支持属性}""",
                description="属性导入失败提示模板，支持变量：{错误原因}/{支持属性}"
            )
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        return [
            (CoCDiceTool.get_tool_info(), CoCDiceTool),          
            (CoCDiceCommand.get_command_info(), CoCDiceCommand),
            (CoCDiceEventHandler.get_handler_info(), CoCDiceEventHandler),
        ]
    
    def on_plugin_stop(self):
        """插件停止时保存角色数据"""
        global USER_CHARACTER_DATA
        save_character_data(USER_CHARACTER_DATA)
        logger.info("插件停止，角色数据已保存")
