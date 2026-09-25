/**
 * 操作员名单。

 * 名单一度是写死在代码里的四个名字，现场只要有第五个人就没法选。
 * 这里改成可配置：默认给一份初始名单，之后由使用方在界面上增删，
 * 存在浏览器本地（一期单机，没有账号体系）。
 */

const STORAGE_KEY = 'pharmrelate.operators';

export const DEFAULT_OPERATORS = ['操作员甲', '操作员乙', '操作员丙', '操作员丁'];

export function loadOperators(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [...DEFAULT_OPERATORS];
    const parsed = JSON.parse(raw) as unknown;
    if (!Array.isArray(parsed)) return [...DEFAULT_OPERATORS];
    const cleaned = parsed
      .filter((item): item is string => typeof item === 'string')
      .map((item) => item.trim())
      .filter(Boolean);
    return cleaned.length ? cleaned : [...DEFAULT_OPERATORS];
  } catch {
    return [...DEFAULT_OPERATORS];
  }
}

export function saveOperators(names: string[]): string[] {
  const cleaned = [...new Set(names.map((item) => item.trim()).filter(Boolean))];
  const result = cleaned.length ? cleaned : [...DEFAULT_OPERATORS];
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(result));
  } catch {
    // 隐私模式等场景写不进去，不影响本次会话内生效
  }
  return result;
}

export function addOperator(names: string[], name: string): string[] {
  const value = name.trim();
  if (!value || names.includes(value)) return names;
  return saveOperators([...names, value]);
}

export function removeOperator(names: string[], name: string): string[] {
  return saveOperators(names.filter((item) => item !== name));
}

/** 仅供测试：清掉存储。 */
export function __resetOperatorsForTest(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // 忽略
  }
}
