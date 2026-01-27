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

# ===================== 新增：属性指令映射字典 =====================
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
            # 掷骰命令默认模板
            "roll_template": """🎲 投掷「{表达式}」结果：
单次投掷结果：{单次结果}
修正值：{修正值}
总计：{总计}
{判定结果}""",
            # 检定命令默认模板
            "check_template": """🎲 克苏鲁检定（阈值：{阈值}）
投掷结果：{投掷结果}
{判定结果}""",
            # 新增：属性检定专用模板
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
💡 支持指令：/{力量}/{体质}/{体型}/{敏捷}/{外貌}/{智力}/{意志}/{教育}/{幸运}（自动检定对应属性）"""
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
        logger.error(f"读取配置文件失败，使用默认配置：{e}")
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
        logger.warning(f"模板中包含未定义的变量：{e}")
        # 降级替换：只替换存在的变量，保留不存在的变量格式
        rendered = template
        for key, value in data.items():
            rendered = rendered.replace(f"{{{key}}}", str(value))
        return rendered

# ===================== 核心骰子逻辑 =====================
def parse_dice_expression(expr: str) -> Tuple[int, int, int]:
    """
    解析骰子表达式，支持格式：数量d面数[±修正值]
    示例：1d100 → (1,100,0)；2d6+3 → (2,6,3)；3d10-2 → (3,10,-2)
    
    Args:
        expr: 骰子表达式字符串
        
    Returns:
        (数量, 面数, 修正值)
        
    Raises:
        ValueError: 无效表达式
    """
    pattern = r"^(\d+)d(\d+)([+-]\d+)?$"
    match = re.match(pattern, expr.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"无效的骰子表达式：{expr}，请使用「数量d面数[±修正值]」格式（如 1d100、2d6+3）")
    
    count = int(match.group(1))
    face = int(match.group(2))
    modifier = int(match.group(3)) if match.group(3) else 0
    
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

# ===================== 角色属性生成逻辑 =====================
def generate_character_attributes() -> Dict[str, int]:
    """
    生成跑团基础属性，公式：3D6×5
    Returns:
        字典格式：{属性缩写: 最终属性值}，如 {"STR": 50, "CON": 55...}
    """
    # 定义基础属性映射（显示名: 缩写）
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
        # 3D6 投掷
        rolls, sum_3d6 = roll_dice(3, 6)
        # 最终值 = 3D6结果 ×5
        final_value = sum_3d6 * 5
        attr_results[short_name] = final_value
    
    # 计算总属性
    attr_results["总属性"] = sum(attr_results.values())
    return attr_results

# ===================== LLM调用工具（中文指令） =====================
class CoCDiceTool(BaseTool):
    """CoC骰子工具 - 投掷克苏鲁跑团常用骰子"""

    name = "coc_dice_tool"
    description = "克苏鲁跑团骰子投掷工具，支持D100百分骰、D4/D6/D8/D10/D12/D20等多面骰，表达式格式为「数量d面数[±修正值]」（如1d100、2d6+3）"
    parameters = [
        ("dice_expr", ToolParamType.STRING, "骰子表达式（格式：数量d面数[±修正值]，如1d100、2d6+3）", True, None),
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
            # 1. 读取配置（热重载）
            config = get_plugin_config()
            # 2. 解析并投掷骰子
            count, face, modifier = parse_dice_expression(dice_expr)
            rolls, total = roll_dice(count, face, modifier)
            
            # 3. 组装掷骰数据（用于模板渲染）
            roll_detail = " + ".join(map(str, rolls))
            modifier_str = f"{'+' if modifier > 0 else '-'}{abs(modifier)}" if modifier != 0 else "无"
            success_thresh = config["dice"]["success_threshold"]
            fail_thresh = config["dice"]["fail_threshold"]
            
            # 判定结果（仅1d100生效）
            judge_result = ""
            if face == 100 and count == 1:
                if total <= success_thresh:
                    judge_result = "✨ 大成功！"
                elif total >= fail_thresh:
                    judge_result = "💥 大失败！"
            
            # 4. 组装模板数据
            roll_data = {
                "表达式": dice_expr,
                "单次结果": roll_detail,
                "修正值": modifier_str,
                "总计": total,
                "判定结果": judge_result.strip()
            }
            
            # 5. 渲染模板
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

# ===================== 核心命令（/掷骰 /检定 /创建角色 /查询角色 /属性检定） =====================
class CoCDiceCommand(BaseCommand):
    """CoC骰子命令 - 响应中文指令：/掷骰 /检定 /创建角色 /查询角色 /属性检定"""

    command_name = "coc_dice_command"
    command_description = f"""克苏鲁骰子投掷/检定/角色创建/角色查询（支持角色绑定+持久化）
用法：
1. /掷骰 1d100（投掷任意骰子）
2. /检定 70（D100检定，阈值70）
3. /创建角色（随机生成跑团基础属性并绑定到当前账号）
4. /查询角色（查看已绑定的角色属性）
5. /属性名（自动用绑定角色的对应属性检定，支持：{', '.join(VALID_ATTR_COMMANDS)}）
   示例：/力量 → 用你的力量属性值做D100检定"""
    # 扩展命令匹配规则：支持/属性名指令
    command_pattern = rf"^/(掷骰|检定|创建角色|查询角色|{'|'.join(VALID_ATTR_COMMANDS)})(\s+.*)?$"

    async def execute(self) -> Tuple[bool, str, bool]:
        """执行中文骰子指令（主动发送结果到聊天）"""
        # ========== global声明前置 ==========
        global USER_CHARACTER_DATA
        
        # ========== 提取用户ID ==========
        user_id = None
        try:
            # 按指定路径提取用户ID：self.message.message_info.user_info.user_id
            if (hasattr(self.message, 'message_info') and 
                hasattr(self.message.message_info, 'user_info') and 
                hasattr(self.message.message_info.user_info, 'user_id')):
                user_id = str(self.message.message_info.user_info.user_id)
                logger.info(f"成功提取用户ID：{user_id}（路径：self.message.message_info.user_info.user_id）")
            else:
                logger.error("无法提取用户ID：缺失以下属性层级")
                logger.error(f"- self.message是否有message_info：{hasattr(self.message, 'message_info')}")
                if hasattr(self.message, 'message_info'):
                    logger.error(f"- self.message.message_info是否有user_info：{hasattr(self.message.message_info, 'user_info')}")
                if hasattr(self.message, 'message_info') and hasattr(self.message.message_info, 'user_info'):
                    logger.error(f"- self.message.message_info.user_info是否有user_id：{hasattr(self.message.message_info.user_info, 'user_id')}")
        except Exception as e:
            logger.error(f"提取用户ID时出错：{e}")
        
        # 检查用户ID是否获取成功
        if not user_id:
            error_msg = "❌ 无法获取你的用户ID，无法绑定/查询角色！"
            await self.send_text(error_msg)
            return False, error_msg, True
        
        # 提取指令前缀和参数
        raw_params = self.message.raw_message.strip()
        cmd_prefix = None
        # 识别属性检定指令（优先级最高）
        for attr_name in VALID_ATTR_COMMANDS:
            if raw_params.startswith(f"/{attr_name}"):
                cmd_prefix = f"/{attr_name}"
                break
        # 识别原有指令
        if not cmd_prefix:
            if "创建角色" in raw_params:
                cmd_prefix = "/创建角色"
            elif "查询角色" in raw_params:
                cmd_prefix = "/查询角色"
            elif "检定" in raw_params:
                cmd_prefix = "/检定"
            else:
                cmd_prefix = "/掷骰"
        
        params = raw_params[len(cmd_prefix):].strip()
        config = get_plugin_config()
        
        # ========== 新增：处理属性检定指令（/力量、/体质等） ==========
        attr_name = cmd_prefix.lstrip("/")  # 提取属性名（如/力量 → 力量）
        if attr_name in VALID_ATTR_COMMANDS:
            # 校验参数（属性检定指令不允许带参数）
            if params:
                error_msg = f"❌ /{attr_name}命令无需参数！直接发送「/{attr_name}」即可用你的{attr_name}属性检定。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            # 校验用户是否绑定角色
            if user_id not in USER_CHARACTER_DATA:
                error_msg = f"❌ 你还未绑定任何角色！发送「/创建角色」生成角色后，才能使用「/{attr_name}」指令检定。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                # 1. 获取属性映射（如力量 → (STR, 力量(STR))）
                attr_short, attr_full = ATTR_COMMAND_MAP[attr_name]
                # 2. 获取用户绑定角色的该属性值
                attr_value = USER_CHARACTER_DATA[user_id][attr_short]
                # 3. 校验属性值有效性
                if not isinstance(attr_value, int) or attr_value < 1 or attr_value > 100:
                    error_msg = f"❌ 你的{attr_full}属性值异常（{attr_value}），无法检定！"
                    await self.send_text(error_msg)
                    return False, error_msg, True
                
                # 4. 执行D100检定
                rolls, total = roll_dice(1, 100)
                success_thresh = config["dice"]["success_threshold"]
                fail_thresh = config["dice"]["fail_threshold"]
                
                # 5. 判定结果
                if total <= success_thresh:
                    judge_result = "✨ 大成功！"
                elif total <= attr_value:
                    judge_result = "✅ 检定成功！"
                elif total >= fail_thresh:
                    judge_result = "💥 大失败！"
                else:
                    judge_result = "❌ 检定失败！"
                
                # 6. 组装检定数据（用于模板渲染）
                check_data = {
                    "属性全称": attr_full,
                    "阈值": attr_value,
                    "投掷结果": total,
                    "判定结果": judge_result.strip()
                }
                
                # 7. 渲染属性检定专用模板
                attr_check_template = config["dice"]["attr_check_template"]
                msg = render_template(attr_check_template, check_data)
                
                await self.send_text(msg)
                return True, msg, True
            
            except Exception as e:
                logger.error(f"{attr_name}属性检定失败：{e}", exc_info=True)
                error_msg = f"❌ {attr_name}属性检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # ========== 原有指令逻辑（保持不变） ==========
        # 处理「/创建角色」指令
        elif cmd_prefix == "/创建角色":
            if params:
                error_msg = "❌ /创建角色命令无需参数！直接发送「/创建角色」即可生成并绑定随机属性"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                attr_data = generate_character_attributes()
                USER_CHARACTER_DATA[user_id] = attr_data
                save_character_data(USER_CHARACTER_DATA)
                char_template = config["character"]["output_template"]
                role_msg = render_template(char_template, attr_data)
                role_msg += "\n\n✅ 角色已成功绑定到你的账号！发送「/查询角色」可查看，支持/{力量}/{体质}等指令自动检定。"
                
                await self.send_text(role_msg)
                return True, role_msg, True
            
            except Exception as e:
                logger.error(f"创建角色失败：{e}", exc_info=True)
                error_msg = f"❌ 创建角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # 处理「/查询角色」指令
        elif cmd_prefix == "/查询角色":
            if params:
                error_msg = "❌ /查询角色命令无需参数！直接发送「/查询角色」即可查看绑定角色"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            if user_id not in USER_CHARACTER_DATA:
                error_msg = "❌ 你还未绑定任何角色！发送「/创建角色」可生成并绑定角色。"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                attr_data = USER_CHARACTER_DATA[user_id]
                query_template = config["character"]["query_template"]
                query_msg = render_template(query_template, attr_data)
                
                await self.send_text(query_msg)
                return True, query_msg, True
            
            except Exception as e:
                logger.error(f"查询角色失败：{e}", exc_info=True)
                error_msg = f"❌ 查询角色出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # 处理「/检定」指令
        elif cmd_prefix == "/检定":
            if not params:
                error_msg = "❌ 缺少参数！用法：\n/检定 70（D100检定，阈值70）"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            if not params.isdigit():
                error_msg = "❌ 检定值必须是数字！示例：/检定 70"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                check_threshold = int(params)
                if check_threshold < 1 or check_threshold > 99:
                    error_msg = "❌ 检定值范围必须是1-99！"
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
                
                check_data = {
                    "阈值": check_threshold,
                    "投掷结果": total,
                    "判定结果": judge_result.strip()
                }
                
                check_template = config["dice"]["check_template"]
                msg = render_template(check_template, check_data)
                
                await self.send_text(msg)
                return True, msg, True
            
            except Exception as e:
                logger.error(f"检定命令执行失败：{e}", exc_info=True)
                error_msg = f"❌ 检定出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
        
        # 处理「/掷骰」指令
        else:
            if not params:
                error_msg = "❌ 缺少参数！用法：\n/掷骰 1d100（投掷任意骰子）"
                await self.send_text(error_msg)
                return False, error_msg, True
            
            try:
                count, face, modifier = parse_dice_expression(params)
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
                    "表达式": params,
                    "单次结果": roll_detail,
                    "修正值": modifier_str,
                    "总计": total,
                    "判定结果": judge_result.strip()
                }
                
                roll_template = config["dice"]["roll_template"]
                msg = render_template(roll_template, roll_data)
                
                await self.send_text(msg)
                return True, msg, True
            
            except ValueError as e:
                error_msg = f"❌ 错误：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True
            except Exception as e:
                logger.error(f"掷骰命令执行失败：{e}", exc_info=True)
                error_msg = f"❌ 掷骰出错：{str(e)}"
                await self.send_text(error_msg)
                return False, error_msg, True

# ===================== 消息事件处理器（监听「掷骰」关键词） =====================
class CoCDiceEventHandler(BaseEventHandler):
    """CoC骰子事件处理器 - 监听包含「掷骰」的消息自动响应并发送结果到聊天"""

    event_type = EventType.ON_MESSAGE
    handler_name = "coc_dice_handler"
    handler_description = "监听消息中的「掷骰」关键词，自动响应CoC骰子投掷并发送结果到聊天"

    async def execute(self, message: MaiMessages | None) -> Tuple[bool, bool, str | None, None, None]:
        """监听消息并自动投掷骰子，结果直接发送到聊天"""
        if not message or not message.plain_text:
            return True, True, None, None, None
        
        # 匹配「掷骰」关键词 + 表达式（如：掷骰 1d100）
        msg_text = message.plain_text.strip()
        if "掷骰" in msg_text:
            match = re.search(r"掷骰\s+(\d+d\d+[+-]?\d*)", msg_text)
            if match:
                dice_expr = match.group(1)
                try:
                    # 1. 读取配置（热重载）
                    config = get_plugin_config()
                    # 2. 解析并投掷骰子
                    count, face, modifier = parse_dice_expression(dice_expr)
                    rolls, total = roll_dice(count, face, modifier)
                    
                    # 3. 组装掷骰数据
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
                        "单次结果": roll_detail,
                        "修正值": modifier_str,
                        "总计": total,
                        "判定结果": judge_result.strip()
                    }
                    
                    # 4. 渲染模板
                    roll_template = config["dice"]["roll_template"]
                    auto_msg = render_template(roll_template, roll_data)
                    
                    await self.send_text(auto_msg)
                except ValueError as e:
                    error_msg = f"❌ 自动投掷失败：{str(e)}"
                    await self.send_text(error_msg)
        
        return True, True, None, None, None

# ===================== 插件注册（配置文件为config.toml） =====================
@register_plugin
class CoCDicePlugin(BasePlugin):
    """CoC骰子插件 - 克苏鲁跑团专用骰子工具（角色绑定+持久化+属性自动检定）"""

    # 插件基本信息
    plugin_name: str = "coc_dice_plugin"
    enable_plugin: bool = True
    dependencies: List[str] = []
    python_dependencies: List[str] = []
    config_file_name: str = "config.toml"

    # 配置Schema（完整模板配置说明）
    config_section_descriptions = {
        "plugin": "插件基础配置",
        "dice": "骰子/检定相关配置（含自定义模板）",
        "character": "角色创建/查询模板配置"
    }

    config_schema: dict = {
        "plugin": {
            "config_version": ConfigField(type=str, default="1.0.0", description="配置文件版本"),
            "enabled": ConfigField(type=bool, default=True, description="是否启用插件")
        },
        "dice": {
            "show_detail": ConfigField(type=bool, default=True, description="是否显示单次投掷详情"),
            "success_threshold": ConfigField(type=int, default=5, description="D100大成功阈值（≤该值为大成功）"),
            "fail_threshold": ConfigField(type=int, default=96, description="D100大失败阈值（≥该值为大失败）"),
            "default_message": ConfigField(type=str, default="🎲 克苏鲁骰子投掷完成！", description="默认提示消息"),
            "roll_template": ConfigField(
                type=str,
                default="""🎲 投掷「{表达式}」结果：
单次投掷结果：{单次结果}
修正值：{修正值}
总计：{总计}
{判定结果}""",
                description="掷骰命令输出模板，支持变量：{表达式}/{单次结果}/{修正值}/{总计}/{判定结果}"
            ),
            "check_template": ConfigField(
                type=str,
                default="""🎲 克苏鲁检定（阈值：{阈值}）
投掷结果：{投掷结果}
{判定结果}""",
                description="检定命令输出模板，支持变量：{阈值}/{投掷结果}/{判定结果}"
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
💡 支持指令：/{力量}/{体质}/{体型}/{敏捷}/{外貌}/{智力}/{意志}/{教育}/{幸运}（自动检定对应属性）""",
                description="角色查询输出模板，支持变量：{STR}/{CON}/{SIZ}/{DEX}/{APP}/{INT}/{POW}/{EDU}/{LUCK}/{总属性}"
            )
        }
    }

    def get_plugin_components(self) -> List[Tuple[ComponentInfo, Type]]:
        """注册插件组件"""
        return [
            (CoCDiceTool.get_tool_info(), CoCDiceTool),          
            (CoCDiceCommand.get_command_info(), CoCDiceCommand),
            (CoCDiceEventHandler.get_handler_info(), CoCDiceEventHandler),
        ]
    
    def on_plugin_stop(self):
        """插件停止时保存角色数据（防止数据丢失）"""
        global USER_CHARACTER_DATA
        save_character_data(USER_CHARACTER_DATA)
        logger.info("插件停止，已保存角色数据")
