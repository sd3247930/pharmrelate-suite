import { beforeEach, describe, expect, it } from 'vitest';

import {
  DEFAULT_OPERATORS,
  __resetOperatorsForTest,
  addOperator,
  loadOperators,
  removeOperator,
  saveOperators,
} from './operators';

describe('操作员名单', () => {
  beforeEach(() => {
    __resetOperatorsForTest();
    localStorage.clear();
  });

  it('首次使用时给出默认名单，而不是空列表', () => {
    expect(loadOperators()).toEqual(DEFAULT_OPERATORS);
  });

  it('可以增删并持久化', () => {
    let names = addOperator(loadOperators(), '赵六');
    expect(names).toContain('赵六');
    expect(loadOperators()).toContain('赵六');

    names = removeOperator(names, '赵六');
    expect(names).not.toContain('赵六');
    expect(loadOperators()).not.toContain('赵六');
  });

  it('忽略空白与重复', () => {
    const names = addOperator(DEFAULT_OPERATORS, '   ');
    expect(names).toEqual(DEFAULT_OPERATORS);
    expect(addOperator(DEFAULT_OPERATORS, '操作员乙')).toEqual(DEFAULT_OPERATORS);
  });

  it('去重后保存', () => {
    expect(saveOperators(['操作员乙', '操作员乙', ' 操作员丙 '])).toEqual(['操作员乙', '操作员丙']);
  });

  it('清空到没有有效名字时退回默认名单', () => {
    expect(saveOperators([])).toEqual(DEFAULT_OPERATORS);
    expect(saveOperators(['  '])).toEqual(DEFAULT_OPERATORS);
  });

  it('存储内容损坏时退回默认名单，不抛异常', () => {
    localStorage.setItem('pharmrelate.operators', '{ 这不是数组');
    expect(loadOperators()).toEqual(DEFAULT_OPERATORS);
  });
});
