from collections import Counter

def calculate_char_coverage_set(correct_name: str, guess_text: str) -> float:
    """
    计算guess_text包含correct_name中字符的比例（去重版本）

    Args:
        correct_name: 正确答案
        guess_text: 用户猜测的答案

    Returns:
        float: 字符覆盖率 (0-1之间)
    """
    if not correct_name:
        return 0.0

    # 转换为集合去重
    correct_chars = set(correct_name)
    guess_chars = set(guess_text)

    # 计算匹配的字符数比例
    matched_chars = correct_chars & guess_chars
    coverage = len(matched_chars) / len(correct_chars)

    return coverage

def calculate_char_coverage_counter(correct_name: str, guess_text: str) -> float:
    """
    计算guess_text包含correct_name中字符的比例（不去重版本）

    Args:
        correct_name: 正确答案
        guess_text: 用户猜测的答案

    Returns:
        float: 字符覆盖率 (0-1之间)
    """
    if not correct_name:
        return 0.0

    # 使用Counter统计字符出现次数
    correct_counter = Counter(correct_name)
    guess_counter = Counter(guess_text)

    # 计算总字符数和匹配的字符数
    total_chars = sum(correct_counter.values())
    matched_chars = 0

    for char, count in correct_counter.items():
        matched_chars += min(count, guess_counter.get(char, 0))

    coverage = matched_chars / total_chars if total_chars > 0 else 0.0

    return coverage
